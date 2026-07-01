"""
engage — engagement state for Kali: authorised scope, an asset graph, and a loot
store.  The persistent memory of a single job.

Where the evidence ledger records *what happened* (an append-only, hashed log),
this module models *what is currently true* about the engagement, so the
operator — and the model — can reason over the whole job instead of just the
last command.  Three parts, all local, all propose/read-only:

  1. SCOPE — the authorised target list.  `scope_set` records the hosts / CIDRs
     / domains you're allowed to touch; `scope_check` answers "is this target in
     scope?" and FAILS CLOSED (unknown or unparseable ⇒ NOT in scope).  This is
     the authorisation boundary the model is told to consult before proposing
     any active command.  It records and checks scope; it does not itself run or
     block anything (the run gate + operator do that) — but it turns "am I
     allowed to hit this?" from a judgement call into a checkable fact.

  2. ASSET GRAPH — a structured picture of the engagement: hosts, the services
     on them, findings against them, and any access obtained.  `asset_record`
     adds/updates a node; `graph_query` returns the current state.  This is what
     lets Kali answer "which hosts have I confirmed SSH on / where do I have a
     foothold / what's left" — the queryable state most open-source AI-pentest
     tools lack.

  3. LOOT — credentials / hashes / tokens captured during the engagement
     (stored locally, on the operator's own box, for an authorised job — the
     same thing Metasploit's creds database does).  Secrets are REDACTED in
     every output.  `loot_reuse` suggests where a captured credential might be
     worth trying next — other IN-SCOPE hosts running the same service — as
     SUGGESTIONS for the operator, never an automatic credential attack.

Design contract (kali_ext/__init__.py): imports NOTHING from the Kali core;
pure stdlib; GTK-free; trivially unit-testable offline.  State persists as one
JSON file per engagement under ~/.config/kali/engagements/.  Every write is
fail-safe — a state write must never break the caller.  Nothing here attacks
anything, generates a payload, or fires a credential; it records scope, models
state, and reasons over it.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_DEFAULT_ENGAGEMENT = "default"


def _safe_name(name: Optional[str]) -> str:
    name = (name or "").strip() or _DEFAULT_ENGAGEMENT
    name = _SAFE_NAME_RE.sub("-", name).strip("-.") or _DEFAULT_ENGAGEMENT
    return name[:64]


def _base(base_dir: Optional[Path]) -> Path:
    if base_dir is None:
        base_dir = Path(os.path.expanduser("~")) / ".config" / "kali" / "engagements"
    return Path(base_dir)


def _path(engagement: str, base_dir: Optional[Path]) -> Path:
    return _base(base_dir) / f"{_safe_name(engagement)}.json"


def _load(engagement: str, base_dir: Optional[Path]) -> Dict[str, Any]:
    p = _path(engagement, base_dir)
    if not p.exists():
        return {"engagement": _safe_name(engagement), "scope": [],
                "assets": {}, "loot": []}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        # be forgiving about shape
        d.setdefault("scope", [])
        d.setdefault("assets", {})
        d.setdefault("loot", [])
        d["engagement"] = _safe_name(engagement)
        return d
    except Exception:
        return {"engagement": _safe_name(engagement), "scope": [],
                "assets": {}, "loot": []}


def _save(state: Dict[str, Any], base_dir: Optional[Path]) -> bool:
    try:
        with _LOCK:
            d = _base(base_dir)
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{_safe_name(state.get('engagement'))}.json"
            tmp = p.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)  # atomic
        return True
    except Exception:
        return False


# ═════════════════════════════════════════════════════════════════════
# SCOPE — the authorised target list.  Fails closed.
# ═════════════════════════════════════════════════════════════════════

def _host_of(target: str) -> str:
    """Extract a bare host from a URL / host:port / raw host."""
    t = (target or "").strip()
    if not t:
        return ""
    # strip scheme
    t = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", t)
    # strip path/query
    t = t.split("/", 1)[0].split("?", 1)[0]
    # strip userinfo
    if "@" in t:
        t = t.rsplit("@", 1)[1]
    # strip :port (but keep IPv6 in brackets intact)
    if t.startswith("["):
        m = re.match(r"^\[([^\]]+)\]", t)
        return m.group(1) if m else t
    if t.count(":") == 1:  # host:port
        t = t.split(":", 1)[0]
    return t.strip().lower().rstrip(".")


def _norm_scope_entry(s: str) -> str:
    return _host_of(s) if "://" in s or "/" not in s else s.strip().lower()


def _match_one(host: str, rule: str) -> bool:
    """Does `host` fall under a single scope `rule`?  Rules may be an exact
    host, a domain (covers its subdomains), an IP, or a CIDR."""
    rule = (rule or "").strip().lower().rstrip(".")
    if not rule or not host:
        return False

    # CIDR / IP-range rule
    if "/" in rule:
        try:
            net = ipaddress.ip_network(rule, strict=False)
            try:
                return ipaddress.ip_address(host) in net
            except ValueError:
                return False  # host isn't an IP; a CIDR rule can't cover a name
        except ValueError:
            pass  # not a CIDR; fall through to string logic

    # exact IP rule
    try:
        ipaddress.ip_address(rule)
        return host == rule
    except ValueError:
        pass

    # domain rule: exact, or a subdomain of it
    if host == rule:
        return True
    if host.endswith("." + rule):
        return True
    # wildcard "*.example.com"
    if rule.startswith("*."):
        bare = rule[2:]
        return host == bare or host.endswith("." + bare)
    return False


def scope_set(targets: Any, engagement: str = "default", mode: str = "replace",
              base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Record the AUTHORISED scope for an engagement — the hosts / domains /
    CIDRs you have written permission to test.  `mode` = replace | add.
    Returns the stored scope.  This is the list scope_check enforces; keep it
    tight and accurate — it's your authorisation boundary."""
    if isinstance(targets, str):
        parts = re.split(r"[\s,;]+", targets.strip())
    elif isinstance(targets, (list, tuple)):
        parts = list(targets)
    else:
        parts = []
    cleaned = []
    for p in parts:
        p = str(p or "").strip()
        if not p:
            continue
        cleaned.append(_norm_scope_entry(p))
    cleaned = list(dict.fromkeys(cleaned))  # dedup, keep order

    st = _load(engagement, base_dir)
    if mode == "add":
        st["scope"] = list(dict.fromkeys(st.get("scope", []) + cleaned))
    else:
        st["scope"] = cleaned
    ok = _save(st, base_dir)
    return {"ok": ok, "engagement": st["engagement"], "scope": st["scope"],
            "count": len(st["scope"]),
            "note": "Only test targets you are authorised to. scope_check fails "
                    "closed — anything not matched here is treated as out of scope."}


def scope_show(engagement: str = "default",
               base_dir: Optional[Path] = None) -> Dict[str, Any]:
    st = _load(engagement, base_dir)
    return {"ok": True, "engagement": st["engagement"],
            "scope": st.get("scope", []), "count": len(st.get("scope", []))}


def scope_check(target: str, engagement: str = "default",
                base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Is `target` within the engagement's authorised scope?  FAILS CLOSED:
    if scope is unset, or the target can't be parsed, or nothing matches, it is
    reported OUT of scope.  Consult this before proposing any active command
    against a target."""
    st = _load(engagement, base_dir)
    scope = st.get("scope", [])
    host = _host_of(target)
    if not scope:
        return {"ok": True, "target": target, "host": host, "in_scope": False,
                "matched": None,
                "reason": "no scope set for this engagement — set scope_set first; "
                          "treating as OUT of scope until then."}
    if not host:
        return {"ok": True, "target": target, "host": host, "in_scope": False,
                "matched": None, "reason": "could not parse a host from the target."}
    for rule in scope:
        if _match_one(host, rule):
            return {"ok": True, "target": target, "host": host, "in_scope": True,
                    "matched": rule, "reason": f"{host} matches authorised scope entry '{rule}'."}
    return {"ok": True, "target": target, "host": host, "in_scope": False,
            "matched": None,
            "reason": f"{host} matches no authorised scope entry — OUT of scope. "
                      f"Do not run active commands against it."}


# ═════════════════════════════════════════════════════════════════════
# ASSET GRAPH — hosts, services, findings, access.
# ═════════════════════════════════════════════════════════════════════

def _apply_asset(st: Dict[str, Any], host: str, service: str = "", port: Any = None,
                 finding: str = "", access: str = "", note: str = "") -> Optional[str]:
    """Mutate st['assets'] in place for `host`; returns the normalised host key
    (or None if no host).  Shared by asset_record and loot_record so a single
    save covers both."""
    h = _host_of(host) or (host or "").strip().lower()
    if not h:
        return None
    node = st["assets"].get(h) or {
        "host": h, "services": [], "findings": [], "access": [],
        "notes": [], "first_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if service or port not in (None, ""):
        svc = str(service or "").strip()
        p = str(port).strip() if port not in (None, "") else ""
        label = f"{svc}/{p}".strip("/") or svc or p
        if label and label not in node["services"]:
            node["services"].append(label)
    if finding:
        f = str(finding).strip()
        if f and f not in node["findings"]:
            node["findings"].append(f)
    if access:
        a = str(access).strip()
        if a and a not in node["access"]:
            node["access"].append(a)
    if note:
        n = str(note).strip()
        if n and n not in node["notes"]:
            node["notes"].append(n)
    node["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    st["assets"][h] = node
    return h


def asset_record(engagement: str = "default", host: str = "",
                 service: str = "", port: Any = None, finding: str = "",
                 access: str = "", note: str = "",
                 base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Add or update a host in the engagement graph.  Any of service/port,
    finding, access, or note extend the node.  Idempotent: recording the same
    service twice doesn't duplicate it.  `access` records a foothold level
    (e.g. 'authenticated user', 'RCE as www-data', 'domain user')."""
    if not (_host_of(host) or (host or "").strip()):
        return {"ok": False, "error": "a host is required"}
    st = _load(engagement, base_dir)
    h = _apply_asset(st, host, service, port, finding, access, note)
    ok = _save(st, base_dir)
    return {"ok": ok, "engagement": st["engagement"], "host": h,
            "node": st["assets"].get(h)}


def graph_query(engagement: str = "default", host: str = "",
                base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Return the current engagement graph — every host with its services,
    findings and access — or a single host if `host` is given.  Use it to
    answer 'what do I know / where do I have access / what's left'."""
    st = _load(engagement, base_dir)
    assets = st.get("assets", {})
    if host:
        h = _host_of(host) or host.strip().lower()
        node = assets.get(h)
        if not node:
            return {"ok": False, "error": f"no host '{h}' recorded yet"}
        return {"ok": True, "engagement": st["engagement"], "host": node}
    hosts = list(assets.values())
    with_access = [h["host"] for h in hosts if h.get("access")]
    n_services = sum(len(h.get("services", [])) for h in hosts)
    n_findings = sum(len(h.get("findings", [])) for h in hosts)
    return {
        "ok": True,
        "engagement": st["engagement"],
        "summary": (f"{len(hosts)} host(s), {n_services} service(s), "
                    f"{n_findings} finding(s); footholds on "
                    f"{len(with_access)} host(s)"
                    + (f": {', '.join(with_access)}" if with_access else "")),
        "host_count": len(hosts),
        "hosts_with_access": with_access,
        "hosts": sorted(hosts, key=lambda h: h["host"]),
        "in_scope_count": len(st.get("scope", [])),
    }


# ═════════════════════════════════════════════════════════════════════
# LOOT — captured credentials.  Secrets redacted in all output.
# ═════════════════════════════════════════════════════════════════════

def _redact_secret(s: str) -> str:
    s = str(s or "")
    if not s:
        return ""
    if len(s) <= 3:
        return "***"
    return s[0] + "***" + s[-1] + f" ({len(s)} chars)"


def loot_record(engagement: str = "default", host: str = "", kind: str = "credential",
                username: str = "", secret: str = "", service: str = "",
                note: str = "", base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Record a captured credential / hash / token for the engagement (stored
    locally; the secret is REDACTED in every output).  `kind` = credential |
    hash | token | key.  Ties the loot to the host and service it belongs to so
    loot_reuse can reason about where it might apply next."""
    h = _host_of(host) or (host or "").strip().lower()
    if not h and not username and not secret:
        return {"ok": False, "error": "need at least a host, username, or secret"}
    st = _load(engagement, base_dir)
    entry = {
        "id": len(st.get("loot", [])) + 1,
        "host": h, "kind": (kind or "credential").strip().lower(),
        "username": str(username or "").strip(),
        "secret": str(secret or ""),  # stored; never emitted raw by this module
        "service": str(service or "").strip(),
        "note": str(note or "").strip(),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    st.setdefault("loot", []).append(entry)
    # mirror the credential onto the asset as an access hint — same state,
    # single save (do NOT call asset_record here; that would reload and clobber
    # this loot append).
    if h:
        _apply_asset(st, host=h, service=entry["service"],
                     note=f"loot: {entry['kind']} for {entry['username'] or '?'}")
    ok = _save(st, base_dir)
    view = dict(entry)
    view["secret"] = _redact_secret(entry["secret"])
    return {"ok": ok, "engagement": st["engagement"], "loot": view,
            "note": "Secret stored locally and redacted here. Authorised-engagement "
                    "data only."}


def loot_list(engagement: str = "default",
              base_dir: Optional[Path] = None) -> Dict[str, Any]:
    st = _load(engagement, base_dir)
    out = []
    for e in st.get("loot", []):
        v = dict(e)
        v["secret"] = _redact_secret(e.get("secret", ""))
        out.append(v)
    return {"ok": True, "engagement": st["engagement"], "count": len(out),
            "loot": out}


def loot_reuse(engagement: str = "default",
               base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Suggest where captured credentials might be worth trying next: other
    IN-SCOPE hosts in the graph that run the SAME service as a host where a
    credential was captured, and that don't already have that credential.

    These are SUGGESTIONS for the operator — a lateral-movement lead — not an
    automatic credential attack. The operator decides whether to try them, and
    each attempt still goes through the approval gate and scope check."""
    st = _load(engagement, base_dir)
    loot = st.get("loot", [])
    assets = st.get("assets", {})
    scope = st.get("scope", [])
    if not loot:
        return {"ok": True, "engagement": st["engagement"], "suggestions": [],
                "note": "no loot recorded yet"}

    def _svc_name(label: str) -> str:
        return label.split("/", 1)[0].strip().lower()

    # map service-name -> set of hosts exposing it
    svc_hosts: Dict[str, set] = {}
    for h, node in assets.items():
        for label in node.get("services", []):
            svc_hosts.setdefault(_svc_name(label), set()).add(h)

    def _in_scope(host: str) -> bool:
        return any(_match_one(host, r) for r in scope) if scope else False

    suggestions = []
    for cred in loot:
        svc = _svc_name(cred.get("service", ""))
        if not svc:
            continue
        origin = cred.get("host", "")
        candidates = svc_hosts.get(svc, set()) - {origin}
        for cand in sorted(candidates):
            if scope and not _in_scope(cand):
                continue  # never suggest reuse outside authorised scope
            suggestions.append({
                "credential": {
                    "kind": cred.get("kind"),
                    "username": cred.get("username") or "?",
                    "captured_on": origin,
                    "service": cred.get("service"),
                },
                "try_against": cand,
                "because": f"{cand} also runs {svc}; "
                           f"the {cred.get('kind','credential')} from {origin} "
                           f"may be reused there.",
            })
    return {
        "ok": True,
        "engagement": st["engagement"],
        "count": len(suggestions),
        "suggestions": suggestions,
        "note": "Lateral-movement leads for the operator to consider — not an "
                "automatic attack. Every attempt still needs approval and an "
                "in-scope check. Only ever suggests IN-SCOPE hosts.",
    }


# ═════════════════════════════════════════════════════════════════════
# GRAPH INGEST — turn parsed scan output straight into engagement state, so
# the graph maintains itself from what was actually run (operator, not planner).
# ═════════════════════════════════════════════════════════════════════

def _extract_host(row: Dict[str, Any]) -> str:
    for k in ("host", "ip", "url", "matched-at", "matched_at", "target",
              "hostport", "address"):
        v = row.get(k)
        if v:
            return _host_of(str(v))
    return ""


def graph_ingest(parsed: Any, engagement: str = "default",
                 base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Populate the engagement graph from a parsed scan result (the dict
    returned by pentest.parse_output or codescan.parse_scan, or a bare list of
    findings).  Best-effort: pulls host, service/port, and a finding label out
    of each row and records them.  This is what lets the graph maintain itself
    from what was actually executed instead of hand bookkeeping.  Pure state —
    records nothing about scope enforcement, runs nothing."""
    rows: List[Dict[str, Any]] = []
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except Exception:
            return {"ok": False, "error": "parsed must be a dict or list"}
    if isinstance(parsed, dict):
        if isinstance(parsed.get("findings"), list):
            rows = [r for r in parsed["findings"] if isinstance(r, dict)]
        elif isinstance(parsed.get("hosts"), list):
            rows = [r for r in parsed["hosts"] if isinstance(r, dict)]
        else:
            rows = [parsed]
    elif isinstance(parsed, list):
        rows = [r for r in parsed if isinstance(r, dict)]
    if not rows:
        return {"ok": False, "error": "no records found to ingest"}

    st = _load(engagement, base_dir)
    n_hosts = set()
    n_services = 0
    n_findings = 0
    for row in rows:
        host = _extract_host(row)
        if not host:
            continue
        service = str(row.get("service") or row.get("tech") or
                      row.get("webserver") or row.get("scheme") or "").strip()
        port = row.get("port") or row.get("status_code") or ""
        # a finding label: template/name/title, or a version banner
        finding = str(row.get("name") or row.get("template") or
                      row.get("title") or "").strip()
        sev = str(row.get("severity") or "").strip()
        if finding and sev:
            finding = f"[{sev}] {finding}"
        before = st["assets"].get(host, {})
        before_svc = len(before.get("services", []))
        before_find = len(before.get("findings", []))
        _apply_asset(st, host=host, service=service,
                     port=port if service or port else None,
                     finding=finding)
        after = st["assets"].get(host, {})
        n_hosts.add(host)
        n_services += len(after.get("services", [])) - before_svc
        n_findings += len(after.get("findings", [])) - before_find
    ok = _save(st, base_dir)
    return {
        "ok": ok,
        "engagement": st["engagement"],
        "summary": f"ingested {len(n_hosts)} host(s), +{n_services} service(s), "
                   f"+{n_findings} finding(s) into the graph",
        "hosts_touched": sorted(n_hosts),
    }
