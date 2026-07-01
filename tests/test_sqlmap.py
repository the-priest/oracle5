"""Offline tests for pentest.sqlmap_plan — command construction, clamps,
injection-safe quoting, the detect→enumerate→dump ladder, and the guarantee it
never builds SQLi-to-RCE."""
import sys
sys.path.insert(0, ".")
from kali_ext import pentest as p

P = F = 0
def ck(n, c):
    global P, F
    if c: P += 1; print("  PASS", n)
    else: F += 1; print("  FAIL", n)

r = p.sqlmap_plan(target="http://t/item?id=1", mode="detect", level=3, risk=2)
ck("detect ok", r["ok"])
ck("quotes URL", "-u 'http://t/item?id=1'" in r["command"])
ck("--batch present", "--batch" in r["command"])
ck("level+risk set", "--level=3" in r["command"] and "--risk=2" in r["command"])
ck("marked active", r["risk"] == "active")
ck("proposes, does not run", "command" in r and "stdout" not in r)

r2 = p.sqlmap_plan(target="http://t/?id=1", mode="detect", level=99, risk=99)
ck("level clamps to 5", "--level=5" in r2["command"])
ck("risk clamps to 3 + warns", "--risk=3" in r2["command"] and any("risk=3" in w for w in r2["warnings"]))

r3 = p.sqlmap_plan(target="http://t/login", mode="detect", data="user=a&pass=b",
                   cookie="SESS=1", headers="X-Api: k\nX-Two: v")
ck("--data", "--data 'user=a&pass=b'" in r3["command"])
ck("--cookie", "--cookie 'SESS=1'" in r3["command"])
ck("headers -> two --header", r3["command"].count("--header") == 2)

evil = "http://t/?id=1'; rm -rf /; echo '"
ck("quote-escapes malicious target", "'\\''" in p.sqlmap_plan(target=evil, mode="detect")["command"])

ck("enum dbs", "--dbs" in p.sqlmap_plan(target="http://t/?id=1", mode="enumerate")["command"])
ck("enum tables", p.sqlmap_plan(target="http://t/?id=1", mode="enumerate", db="shop")["command"].endswith("--tables"))
ck("enum columns", "--columns" in p.sqlmap_plan(target="http://t/?id=1", mode="enumerate", db="shop", table="users")["command"])

ck("dump needs table", p.sqlmap_plan(target="http://t/?id=1", mode="dump", db="shop")["ok"] is False)
rd = p.sqlmap_plan(target="http://t/?id=1", mode="dump", db="shop", table="users")
ck("dump builds + warns", rd["ok"] and "--dump" in rd["command"] and any("minimum" in w for w in rd["warnings"]))

allc = " ".join(p.sqlmap_plan(target="http://t/?id=1", mode=m)["command"] for m in ("detect", "enumerate"))
ck("never builds --os-shell/--os-pwn", "--os-shell" not in allc and "--os-pwn" not in allc)

ck("request_file -r", "-r " in p.sqlmap_plan(request_file="/tmp/req.txt", mode="detect")["command"])
ck("bad mode -> error", p.sqlmap_plan(target="http://t/?id=1", mode="exploit")["ok"] is False)
ck("empty target -> error", p.sqlmap_plan(mode="detect")["ok"] is False)

print(f"\n  {P} passed, {F} failed")
sys.exit(1 if F else 0)
