"""Offline tests for kali_ext/engage.py — scope (fail-closed), asset graph,
loot (redacted), in-scope-only reuse, and scan->state ingest."""
import sys, tempfile
sys.path.insert(0, ".")
from pathlib import Path
from kali_ext import engage as e

P = F = 0
def ck(n, c):
    global P, F
    if c: P += 1; print("  PASS", n)
    else: F += 1; print("  FAIL", n)

d = Path(tempfile.mkdtemp()); E = "acme"

print("== SCOPE (fail-closed authorisation) ==")
ck("no scope -> OUT", e.scope_check("10.0.0.5", E, base_dir=d)["in_scope"] is False)
e.scope_set("10.0.0.0/24, *.acme.com, 192.168.1.10", E, base_dir=d)
ck("IP in CIDR -> in", e.scope_check("10.0.0.5", E, base_dir=d)["in_scope"] is True)
ck("IP outside CIDR -> out", e.scope_check("10.0.1.5", E, base_dir=d)["in_scope"] is False)
ck("subdomain of wildcard -> in", e.scope_check("https://app.acme.com/login", E, base_dir=d)["in_scope"] is True)
ck("wildcard base -> in", e.scope_check("acme.com", E, base_dir=d)["in_scope"] is True)
ck("unrelated domain -> out", e.scope_check("evil.com", E, base_dir=d)["in_scope"] is False)
ck("exact IP rule -> in", e.scope_check("192.168.1.10:8080", E, base_dir=d)["in_scope"] is True)
ck("URL w/ port+path parses host", e.scope_check("http://app.acme.com:443/x?y=1", E, base_dir=d)["in_scope"] is True)
ck("garbage target -> out", e.scope_check("!!!", E, base_dir=d)["in_scope"] is False)

print("== ASSET GRAPH ==")
e.asset_record(E, host="10.0.0.5", service="ssh", port=22, base_dir=d)
e.asset_record(E, host="10.0.0.5", service="http", port=80, finding="default creds", base_dir=d)
e.asset_record(E, host="10.0.0.5", service="ssh", port=22, base_dir=d)  # dup
e.asset_record(E, host="10.0.0.6", service="ssh", port=22, access="authenticated user", base_dir=d)
g = e.graph_query(E, base_dir=d)
ck("two hosts", g["host_count"] == 2)
ck("dup service not duplicated", len(e.graph_query(E, host="10.0.0.5", base_dir=d)["host"]["services"]) == 2)
ck("access surfaced", "10.0.0.6" in g["hosts_with_access"])

print("== LOOT (redacted, persisted) ==")
r = e.loot_record(E, host="10.0.0.6", kind="credential", username="admin", secret="SuperSecret123", service="ssh", base_dir=d)
ck("recorded", r["ok"])
ck("secret redacted in return", "SuperSecret123" not in str(r) and "***" in r["loot"]["secret"])
ck("secret persisted for operator", "SuperSecret123" in (d / "acme.json").read_text())

print("== LOOT REUSE (in-scope only) ==")
sug = e.loot_reuse(E, base_dir=d)
ck("suggests same-service host", any(s["try_against"] == "10.0.0.5" for s in sug["suggestions"]))
ck("not the origin host", all(s["try_against"] != "10.0.0.6" for s in sug["suggestions"]))
e.asset_record(E, host="203.0.113.9", service="ssh", port=22, base_dir=d)
ck("never out-of-scope", all(s["try_against"] != "203.0.113.9" for s in e.loot_reuse(E, base_dir=d)["suggestions"]))

print("== GRAPH INGEST (scan -> state) ==")
d2 = Path(tempfile.mkdtemp()); E2 = "ingest"
parsed = {"ok": True, "tool": "nuclei", "findings": [
    {"host": "10.0.0.5", "template": "exposed-git", "severity": "medium", "name": "Exposed .git"},
    {"host": "http://10.0.0.5:8080/", "name": "Login panel", "severity": "info"},
    {"host": "10.0.0.7", "service": "ssh", "port": 22, "name": "OpenSSH 9.6"}]}
r = e.graph_ingest(parsed, engagement=E2, base_dir=d2)
ck("ingest ok", r["ok"])
ck("2 distinct hosts", len(r["hosts_touched"]) == 2)
g2 = e.graph_query(E2, base_dir=d2)
ck("host in graph", any(h["host"] == "10.0.0.5" for h in g2["hosts"]))
ck("severity-tagged finding", any("[medium]" in f for h in g2["hosts"] for f in h["findings"]))
ck("garbage -> ok:false", e.graph_ingest("not json", engagement=E2, base_dir=d2)["ok"] is False)

print("== robustness ==")
ck("asset needs host", e.asset_record(E, host="", base_dir=d)["ok"] is False)
ck("empty graph ok", e.graph_query("none", base_dir=d)["host_count"] == 0)

print(f"\n  {P} passed, {F} failed")
sys.exit(1 if F else 0)
