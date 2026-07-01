"""Offline tests for kali_ext/bench.py — classification, scoring math against
ground truth, report rendering, and multi-run comparison."""
import sys
sys.path.insert(0, ".")
from kali_ext import bench as b

P = F = 0
def ck(n, c):
    global P, F
    if c: P += 1; print("  PASS", n)
    else: F += 1; print("  FAIL", n)

print("== ground-truth catalog ==")
t = b.benchmark_targets()
ck("lists targets", len(t["targets"]) >= 3)
js = b.benchmark_targets("juice-shop")
ck("juice-shop expected set", js["expected_count"] == 15)
ck("unknown target -> error", b.benchmark_targets("nope")["ok"] is False)

print("== classification (CWE + keyword) ==")
ck("CWE-89 -> sqli", b._classify("something", "CWE-89") == "sqli")
ck("'SQL Injection' -> sqli", b._classify("SQL Injection in login") == "sqli")
ck("'stored XSS' -> xss", b._classify("Persisted (stored) XSS") == "xss")
ck("'IDOR' -> access-control", b._classify("IDOR on basket") == "access-control")
ck("'SSRF' -> ssrf", b._classify("Server-Side Request Forgery") == "ssrf")
ck("gibberish -> None", b._classify("purple monkey dishwasher") is None)

print("== scoring math ==")
# a run that finds 3 of juice-shop's classes, with 1 bogus finding
findings = [
    {"title": "SQL Injection - login bypass", "cwe": "CWE-89"},
    {"name": "DOM-based XSS in search"},
    {"category": "Broken Access Control", "title": "view another user's basket"},
    {"title": "Cat photo is low resolution"},   # unclassifiable -> false positive
]
s = b.score_run("juice-shop", findings)
ck("score ok", s["ok"])
ck("found sqli/xss/access-control", set(["sqli","xss","access-control"]).issubset(set(s["found_classes"])))
ck("3 true-positive classes", s["counts"]["true_positive_classes"] == 3)
ck("bogus finding counts as FP", s["counts"]["false_positive_classes"] >= 1)
ck("recall = 3/12 = 0.25", s["score"]["recall"] == 0.25)
ck("coverage 25%", s["score"]["coverage_pct"] == 25.0)
ck("missed classes listed", "ssrf" in s["missed_classes"])
# precision = tp/(tp+fp) = 3/(3+1) = 0.75
ck("precision 0.75", s["score"]["precision"] == 0.75)

print("== perfect + custom ground truth ==")
perfect = [{"cls": c} for c in js["classes"]]
sp = b.score_run("juice-shop", perfect)
ck("perfect coverage 100%", sp["score"]["coverage_pct"] == 100.0)
ck("perfect recall 1.0", sp["score"]["recall"] == 1.0)
custom = b.score_run("myapp", [{"title":"SQLi"}], ground_truth=[{"name":"SQLi","cls":"sqli"},{"name":"XSS","cls":"xss"}])
ck("custom ground truth works", custom["ok"] and custom["score"]["recall"] == 0.5)
ck("no ground truth -> error", b.score_run("unknownapp", findings)["ok"] is False)

print("== report + compare ==")
rep = b.benchmark_report(s)
ck("report renders", rep["ok"] and "Coverage" in rep["report_markdown"])
ck("report shows a miss (❌)", "❌" in rep["report_markdown"])
cmp = b.compare_runs([
    b.score_run("juice-shop", findings, tool="kali"),
    b.score_run("juice-shop", [{"title":"SQLi","cwe":"CWE-89"}], tool="othertool"),
])
ck("compare ranks by F1", cmp["ok"] and cmp["ranked"][0]["f1"] >= cmp["ranked"][1]["f1"])
ck("compare names a winner", cmp["winner"] == "kali")
ck("compare empty -> error", b.compare_runs([])["ok"] is False)

print(f"\n  {P} passed, {F} failed")
sys.exit(1 if F else 0)
