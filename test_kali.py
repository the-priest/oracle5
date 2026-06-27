#!/usr/bin/env python3
"""
test_kali.py — offline regression tests for Kali's load-bearing logic.

These lock down the paths the v2.3.1 audit flagged as under-verified, so a
future edit that quietly breaks one of them fails here instead of on a user's
machine (where Kali runs with root):

  • settings load/save round-trip + the *documented* provider migration
  • the self-edit write path: the ast syntax gate, the immutable GUARDRAIL
    guard, the timestamped backup, and the atomic replace
  • the ChatStore SQLite layer: create / append / read / count / cascade-delete
  • the CVE auto-chain: NVD -> KEV -> EPSS enrichment and the
    KEV -> EPSS -> CVSS ranking (driven by an INJECTED fake fetcher — no network)
  • parse_output structuring + product/version extraction

Everything here touches only the GTK-free modules (kali_core, kali_ext.pentest),
so it runs anywhere Python 3.10+ is — no display, no API keys, no network,
nothing installed beyond the stdlib.

Run any of:
    python3 tests/test_kali.py
    python3 -m unittest discover -s tests -v
    python3 -m pytest tests/ -q          # if pytest happens to be present
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Make the repo root importable whether run from root or from tests/.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "kali_ext"))

import kali_core  # noqa: E402
import kali_voice  # noqa: E402
import urllib.error  # noqa: E402

# kali_ext may be imported either as a package (kali_ext.pentest) or, when
# kali_ext/ is on the path directly, as a bare module (pentest). Try both so
# the suite works from any working directory.
try:
    from kali_ext import pentest  # noqa: E402
except Exception:  # pragma: no cover - fallback for bare-module layout
    import pentest  # type: ignore  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# Settings: defaults, round-trip, and the deliberate migration behaviour
# ─────────────────────────────────────────────────────────────────────────
class TestSettings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_settings = kali_core.SETTINGS_JSON
        kali_core.SETTINGS_JSON = Path(self._tmp.name) / "settings.json"

    def tearDown(self):
        kali_core.SETTINGS_JSON = self._orig_settings
        self._tmp.cleanup()

    def test_default_provider_is_locked_primary(self):
        # The locked primary for fresh installs is SiliconFlow. If this ever
        # changes, it must be a deliberate, reviewed decision — not a drift.
        self.assertEqual(
            kali_core.DEFAULT_SETTINGS["active_provider"], "siliconflow")

    def test_save_load_roundtrip(self):
        s = kali_core.load_settings()
        s["active_provider"] = "novita"
        s["temperature"] = 0.42
        kali_core.save_settings(s)

        loaded = kali_core.load_settings()
        self.assertEqual(loaded["active_provider"], "novita")
        self.assertAlmostEqual(loaded["temperature"], 0.42)
        # Untouched defaults must survive a round-trip.
        self.assertIn("max_tokens", loaded)

    def test_save_is_atomic_no_temp_left(self):
        kali_core.save_settings(kali_core.load_settings())
        leftovers = list(Path(self._tmp.name).glob("*.tmp")) + \
            list(Path(self._tmp.name).glob("*kali-tmp*"))
        self.assertEqual(leftovers, [], "atomic write left a temp file behind")

    def test_migration_legacy_groq_only_install_kept_on_groq(self):
        # DOCUMENTED behaviour: a pre-multi-provider config (no active_provider
        # key at all) is an upgrader whose Groq setup already works, so the
        # migration leaves them on Groq rather than silently switching them to
        # a provider they have no key for. A *fresh* install never hits this —
        # it gets siliconflow straight from DEFAULT_SETTINGS (tested above).
        # This test locks that intent: changing it should be a conscious call.
        merged = dict(kali_core.DEFAULT_SETTINGS)
        raw = {"temperature": 0.7}  # no active_provider -> legacy install
        kali_core._migrate_settings(merged, raw)
        self.assertEqual(merged["active_provider"], "groq")

    def test_migration_unknown_provider_falls_back_to_siliconflow(self):
        merged = dict(kali_core.DEFAULT_SETTINGS)
        merged["active_provider"] = "some_removed_provider"
        raw = {"active_provider": "some_removed_provider"}
        kali_core._migrate_settings(merged, raw)
        self.assertEqual(merged["active_provider"], "siliconflow")


# ─────────────────────────────────────────────────────────────────────────
# Provider registry integrity
# ─────────────────────────────────────────────────────────────────────────
class TestProviderRegistry(unittest.TestCase):
    def test_all_expected_providers_present(self):
        for key in ("siliconflow", "groq", "novita", "github", "google"):
            self.assertIn(key, kali_core.PROVIDERS_BY_KEY,
                          f"provider {key} missing from registry")

    def test_every_provider_has_a_nonempty_model_chain(self):
        for key, prov in kali_core.PROVIDERS_BY_KEY.items():
            self.assertTrue(prov.chain, f"{key} has an empty model chain")
            # default_model is a @property, not a method.
            self.assertTrue(prov.default_model,
                            f"{key} default_model is empty")

    def test_siliconflow_primary_model_is_deepseek_v4_flash(self):
        # The locked default model. Guards against an accidental reorder of the
        # chain that would silently change which model fresh installs use.
        sf = kali_core.PROVIDERS_BY_KEY["siliconflow"]
        self.assertEqual(sf.chain[0], "deepseek-ai/DeepSeek-V4-Flash")


# ─────────────────────────────────────────────────────────────────────────
# Self-edit write path: ast gate, guardrail guard, backup, atomic replace
# ─────────────────────────────────────────────────────────────────────────
_PERSONA_V1 = '''"""kali persona (test fixture)."""
# ===================================================================
#   GUARDRAIL — LOAD-BEARING.  DO NOT EDIT OR REMOVE THIS BLOCK.
#   - never run a side-effecting command without explicit approval
#   - the operator's sudo password is never shown to the model
#   END GUARDRAIL.  Edit freely below this line.
# ===================================================================

GREETING = "hello operator"
'''

# Same guardrail body, different code below it -> must be allowed.
_PERSONA_V2_OK = _PERSONA_V1.replace('"hello operator"', '"hi there"')

# Guardrail body tampered with -> must be refused.
_PERSONA_V2_TAMPERED = _PERSONA_V1.replace(
    "the operator's sudo password is never shown to the model",
    "the sudo password may be logged for debugging")


class TestWritePath(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        # Redirect backups into the temp dir so we never touch real user data.
        self._orig_data = kali_core.DATA_DIR
        kali_core.DATA_DIR = self.tmpdir

    def tearDown(self):
        kali_core.DATA_DIR = self._orig_data
        self._tmp.cleanup()

    def test_creates_file_and_reports_created(self):
        p = self.tmpdir / "note.txt"
        r = kali_core.tool_write_file(str(p), "first content\n")
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["created"])
        self.assertEqual(p.read_text(), "first content\n")

    def test_overwrite_makes_timestamped_backup(self):
        p = self.tmpdir / "note.txt"
        kali_core.tool_write_file(str(p), "v1\n")
        r = kali_core.tool_write_file(str(p), "v2\n")
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["created"])
        self.assertIsNotNone(r["backup"], "no backup recorded on overwrite")
        self.assertTrue(os.path.exists(r["backup"]), "backup file missing")
        self.assertEqual(Path(r["backup"]).read_text(), "v1\n")
        self.assertEqual(p.read_text(), "v2\n")

    def test_atomic_no_tmp_file_left(self):
        p = self.tmpdir / "note.txt"
        kali_core.tool_write_file(str(p), "x\n")
        leftovers = list(self.tmpdir.glob("*.kali-tmp"))
        self.assertEqual(leftovers, [], "atomic replace left a .kali-tmp file")

    def test_refuses_invalid_python_and_leaves_file_intact(self):
        p = self.tmpdir / "mod.py"
        kali_core.tool_write_file(str(p), "x = 1\n")
        r = kali_core.tool_write_file(str(p), "def broken(:\n  pass\n")
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("syntax_error"))
        # The original must be untouched — a bad edit can't corrupt source.
        self.assertEqual(p.read_text(), "x = 1\n")

    def test_guardrail_block_is_immutable(self):
        # A protected file is one named kali_persona.py (basename match).
        p = self.tmpdir / "kali_persona.py"
        r0 = kali_core.tool_write_file(str(p), _PERSONA_V1)
        self.assertTrue(r0["ok"], r0)  # new file: nothing to protect yet

        # Editing code OUTSIDE the guardrail is fine.
        r_ok = kali_core.tool_write_file(str(p), _PERSONA_V2_OK)
        self.assertTrue(r_ok["ok"], r_ok)
        self.assertIn("hi there", p.read_text())

        # Editing INSIDE the guardrail is refused, original preserved.
        before = p.read_text()
        r_bad = kali_core.tool_write_file(str(p), _PERSONA_V2_TAMPERED)
        self.assertFalse(r_bad["ok"])
        self.assertTrue(r_bad.get("guardrail_violation"))
        self.assertEqual(p.read_text(), before,
                         "guardrail-violating write still hit disk")

    def test_guardrail_block_cannot_be_dropped(self):
        p = self.tmpdir / "kali_persona.py"
        kali_core.tool_write_file(str(p), _PERSONA_V1)
        # Content with the guardrail removed entirely.
        no_guard = 'GREETING = "no guardrail here"\n'
        r = kali_core.tool_write_file(str(p), no_guard)
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("guardrail_violation"))


# ─────────────────────────────────────────────────────────────────────────
# ChatStore SQLite layer
# ─────────────────────────────────────────────────────────────────────────
class TestChatStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = kali_core.ChatStore(Path(self._tmp.name) / "chats.db")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_create_append_read_roundtrip(self):
        cid = self.store.create_chat("Test chat", "deepseek-ai/DeepSeek-V4-Flash")
        self.assertIsInstance(cid, int)
        self.assertGreater(cid, 0)

        self.store.add_message(cid, "user", "what ports are open?")
        self.store.add_message(cid, "assistant", "running nmap...")
        msgs = self.store.list_messages(cid)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "user")
        self.assertEqual(msgs[0].content, "what ports are open?")
        self.assertEqual(msgs[1].role, "assistant")
        self.assertEqual(self.store.count_messages(cid), 2)

    def test_message_meta_roundtrips_as_dict(self):
        cid = self.store.create_chat("meta", "m")
        self.store.add_message(cid, "assistant", "hi", meta={"tool": "audit"})
        msgs = self.store.list_messages(cid)
        self.assertEqual(msgs[0].meta.get("tool"), "audit")

    def test_delete_chat_cascades_to_messages(self):
        cid = self.store.create_chat("doomed", "m")
        self.store.add_message(cid, "user", "a")
        self.store.add_message(cid, "user", "b")
        self.assertEqual(self.store.count_messages(cid), 2)

        self.store.delete_chat(cid)
        self.assertIsNone(self.store.get_chat(cid))
        # ON DELETE CASCADE + PRAGMA foreign_keys=ON must have removed messages.
        self.assertEqual(self.store.list_messages(cid), [])

    def test_get_chat_roundtrip_and_listing(self):
        cid = self.store.create_chat("Recon notes", "m")
        chat = self.store.get_chat(cid)
        self.assertIsNotNone(chat)
        self.assertEqual(chat.title, "Recon notes")
        titles = [c.title for c in self.store.list_chats()]
        self.assertIn("Recon notes", titles)


# ─────────────────────────────────────────────────────────────────────────
# parse_output + product/version extraction
# ─────────────────────────────────────────────────────────────────────────
_NMAP_SAMPLE = """\
Nmap scan report for scanme.test (10.0.0.5)
Host is up (0.012s latency).
PORT     STATE  SERVICE VERSION
22/tcp   open   ssh     OpenSSH 9.6p1 Ubuntu 3ubuntu13
80/tcp   open   http    nginx 1.25.3
443/tcp  closed https
"""


class TestParseOutput(unittest.TestCase):
    def test_nmap_hosts_and_open_ports(self):
        r = pentest.parse_output("nmap", _NMAP_SAMPLE)
        self.assertTrue(r["ok"])
        self.assertEqual(r["tool"], "nmap")
        self.assertEqual(r["host_count"], 1)
        # 22 and 80 are open; 443 is closed and must NOT be counted.
        self.assertEqual(r["open_ports"], 2)
        self.assertIn("10.0.0.5", r["hosts"])
        ports = {p["port"] for p in r["hosts"]["10.0.0.5"]}
        self.assertEqual(ports, {"22", "80", "443"})

    def test_empty_input_is_safe(self):
        r = pentest.parse_output("nmap", "")
        self.assertTrue(r["ok"])
        self.assertEqual(r["host_count"], 0)

    def test_split_product_version(self):
        pv = pentest._split_product_version("OpenSSH 9.6p1 Ubuntu")
        self.assertIsNotNone(pv)
        product, version = pv
        self.assertEqual(product, "OpenSSH")
        self.assertTrue(version.startswith("9.6"))

        pv2 = pentest._split_product_version("nginx 1.25.3")
        self.assertIsNotNone(pv2)
        self.assertEqual(pv2[0], "nginx")
        self.assertTrue(pv2[1].startswith("1.25"))

    def test_split_product_version_bare_name_returns_none(self):
        # A bare service name with no version anchors no CVE lookup.
        self.assertIsNone(pentest._split_product_version("ssh"))
        self.assertIsNone(pentest._split_product_version(""))


# ─────────────────────────────────────────────────────────────────────────
# CVE auto-chain: NVD -> KEV -> EPSS enrichment + KEV/EPSS/CVSS ranking,
# driven entirely by an injected fake fetcher (no network).
# ─────────────────────────────────────────────────────────────────────────
def _fake_fetch(url: str):
    """Route by host and return correctly-shaped NVD / KEV / EPSS payloads."""
    if "nvd.nist.gov" in url:
        return {"vulnerabilities": [
            {"cve": {
                "id": "CVE-2021-LOWNOKEV",
                "descriptions": [{"lang": "en", "value": "low sev, no kev"}],
                "metrics": {"cvssMetricV31": [
                    {"cvssData": {"baseScore": 4.0, "baseSeverity": "MEDIUM"}}]},
            }},
            {"cve": {
                "id": "CVE-2021-HIGHNOKEV",
                "descriptions": [{"lang": "en", "value": "high cvss, no kev"}],
                "metrics": {"cvssMetricV31": [
                    {"cvssData": {"baseScore": 9.8, "baseSeverity": "CRITICAL"}}]},
            }},
            {"cve": {
                "id": "CVE-2021-KEVHIT",
                "descriptions": [{"lang": "en", "value": "exploited in wild"}],
                "metrics": {"cvssMetricV31": [
                    {"cvssData": {"baseScore": 7.5, "baseSeverity": "HIGH"}}]},
            }},
        ]}
    if "cisa.gov" in url:  # KEV catalog
        return {"vulnerabilities": [
            {"cveID": "CVE-2021-KEVHIT", "dateAdded": "2022-03-01",
             "knownRansomwareCampaignUse": "Known",
             "vulnerabilityName": "Test KEV", "dueDate": "2022-03-15"},
        ]}
    if "first.org" in url:  # EPSS
        return {"data": [
            {"cve": "CVE-2021-LOWNOKEV", "epss": 0.01, "percentile": 0.10},
            {"cve": "CVE-2021-HIGHNOKEV", "epss": 0.50, "percentile": 0.92},
            {"cve": "CVE-2021-KEVHIT", "epss": 0.20, "percentile": 0.70},
        ]}
    return {}


class TestCveAutoChain(unittest.TestCase):
    def setUp(self):
        # The KEV catalog is process-cached; clear it so tests don't bleed.
        try:
            pentest._KEV_CACHE["map"] = None
            pentest._KEV_CACHE["at"] = 0
        except Exception:
            pass

    def test_lookup_ranks_kev_first_then_epss(self):
        r = pentest.cve_lookup("testprod", "1.0", fetch_json=_fake_fetch)
        self.assertTrue(r["ok"], r)
        ids = [c["id"] for c in r["cves"]]
        self.assertEqual(len(ids), 3)
        # KEV hit must rank first regardless of its lower CVSS/EPSS.
        self.assertEqual(ids[0], "CVE-2021-KEVHIT")
        # Among the non-KEV CVEs, higher EPSS ranks above lower EPSS.
        self.assertLess(ids.index("CVE-2021-HIGHNOKEV"),
                        ids.index("CVE-2021-LOWNOKEV"))

    def test_enrichment_flags_are_attached(self):
        r = pentest.cve_lookup("testprod", "1.0", fetch_json=_fake_fetch)
        by_id = {c["id"]: c for c in r["cves"]}
        self.assertTrue(by_id["CVE-2021-KEVHIT"]["kev"])
        self.assertTrue(by_id["CVE-2021-KEVHIT"]["kev_ransomware"])
        self.assertEqual(by_id["CVE-2021-HIGHNOKEV"]["epss"], 0.5)
        self.assertFalse(by_id["CVE-2021-HIGHNOKEV"]["kev"])

    def test_no_fetcher_returns_nvd_url_not_crash(self):
        # Degraded mode: with no HTTP stack wired, it must hand back the NVD
        # URL for the model to read, not raise.
        r = pentest.cve_lookup("openssh", "9.6")
        self.assertTrue(r["ok"])
        self.assertIn("nvd.nist.gov", r["nvd_url"])

    def test_enrich_with_cves_autochains_from_a_scan(self):
        parsed = pentest.parse_output("nmap", _NMAP_SAMPLE)
        enriched = pentest.enrich_with_cves(parsed, fetch_json=_fake_fetch)
        self.assertIn("cve_enrichment", enriched)
        # The scan had versioned services (OpenSSH 9.6, nginx 1.25.3), so the
        # auto-chain must have attempted at least one lookup.
        self.assertGreaterEqual(
            enriched["cve_enrichment"].get("looked_up", 0), 1)


# ─────────────────────────────────────────────────────────────────────────
# Voice STT provider failover (the SiliconFlow-403 -> Groq-Whisper fix)
# ─────────────────────────────────────────────────────────────────────────
def _http_error(code):
    return urllib.error.HTTPError("http://stt.test", code, "err", {}, None)


class TestSttFailover(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.wav = Path(self._tmp.name) / "rec.wav"
        self.wav.write_bytes(b"RIFF" + b"\0" * 60)  # any bytes; transcribe reads them
        self._orig_post = kali_voice._post_multipart

    def tearDown(self):
        kali_voice._post_multipart = self._orig_post
        self._tmp.cleanup()

    def _stt(self, settings):
        return kali_voice.SpeechToText(lambda: settings)

    def test_falls_back_to_groq_when_siliconflow_403s(self):
        # The reported failure: SiliconFlow key works for chat but the
        # transcription endpoint returns 403. With a Groq key present, voice
        # must transparently fall back to Groq Whisper instead of failing.
        def fake_post(url, *a, **k):
            if "siliconflow" in url:
                raise _http_error(403)
            if "groq" in url:
                return '{"text": "ports are open"}'
            raise _http_error(404)
        kali_voice._post_multipart = fake_post

        stt = self._stt({
            "active_provider": "siliconflow",
            "siliconflow_api_key": "sk-sf",
            "groq_api_key": "gsk-groq",
            "stt_provider": "auto",
        })
        text, err = stt.transcribe(str(self.wav))
        self.assertIsNone(err, f"expected fallback success, got: {err}")
        self.assertEqual(text, "ports are open")

    def test_single_provider_403_still_surfaces_error(self):
        # Only SiliconFlow configured -> nothing to fall back to -> the 403
        # message surfaces, exactly as before. No regression for 1-key users.
        kali_voice._post_multipart = lambda url, *a, **k: (_ for _ in ()).throw(
            _http_error(403))
        stt = self._stt({
            "active_provider": "siliconflow",
            "siliconflow_api_key": "sk-sf",
            "stt_provider": "auto",
        })
        text, err = stt.transcribe(str(self.wav))
        self.assertEqual(text, "")
        self.assertIn("403", err)

    def test_400_does_not_thrash_providers(self):
        # A 400 (bad request) is not retryable: it must NOT trigger a second
        # provider call, since the same audio will fail there too.
        calls = []

        def fake_post(url, *a, **k):
            calls.append(url)
            raise _http_error(400)
        kali_voice._post_multipart = fake_post

        stt = self._stt({
            "active_provider": "siliconflow",
            "siliconflow_api_key": "sk-sf",
            "groq_api_key": "gsk-groq",
            "stt_provider": "auto",
        })
        text, err = stt.transcribe(str(self.wav))
        self.assertEqual(text, "")
        self.assertEqual(len(calls), 1, "400 must not fall through to a 2nd provider")

    def test_no_keys_gives_clear_message(self):
        stt = self._stt({"active_provider": "siliconflow", "stt_provider": "auto"})
        text, err = stt.transcribe(str(self.wav))
        self.assertEqual(text, "")
        self.assertIn("key", err.lower())

    def test_recording_is_cleaned_up_after_transcription(self):
        kali_voice._post_multipart = lambda url, *a, **k: '{"text": "ok"}'
        stt = self._stt({
            "active_provider": "groq",
            "groq_api_key": "gsk",
            "stt_provider": "auto",
        })
        stt.transcribe(str(self.wav))
        self.assertFalse(self.wav.exists(), "temp recording was not removed")


if __name__ == "__main__":
    unittest.main(verbosity=2)