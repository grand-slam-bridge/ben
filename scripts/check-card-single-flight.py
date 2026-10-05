#!/usr/bin/env python3
"""
ONE COMPUTATION PER QUESTION (2026-10-05).

_card_decide is the whole of the fix for a 19.5 s first card: an identical /lead or
/play that arrives while one is being computed JOINS it instead of queueing behind it,
and one that finished in the last minute is answered from the result.

It is pure Python - time, threading, copy, a Lock - so unlike everything else in this
repo it can actually be run here. It is lifted straight out of gameapi.py rather than
copied, so this cannot drift from what ships.

    python3 scripts/check-card-single-flight.py

Exits non-zero on any failure.
"""
import os
import re
import sys
import threading
import time

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "gameapi.py")

src = open(SRC, newline="").read().replace("\r\n", "\n")
block = re.search(r"CARD_CACHE_TTL = .*?\n(?:.*?\n)*?                _card_running\.pop\(key, None\)\n", src)
assert block, "could not find the single-flight block in gameapi.py"
ns = {"time": time, "threading": threading, "Lock": threading.Lock}
exec("import copy\n" + block.group(0), ns)
_card_decide, _card_key = ns["_card_decide"], ns["_card_key"]

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("  ok   " if ok else "  FAIL ") + name + ("  - " + detail if detail else ""))


# ---- 1. two identical questions at once: one computation, the other joins ----
calls = []
def slow(tag):
    def go():
        calls.append(tag)
        time.sleep(0.40)
        return {"card": "D3", "computed_by": tag}
    return go

key = _card_key("lead", hand="K93.AKT3.643.KJ5", seat="E", dealer="N", vul="", ctx="P-1D-P")
out = {}
def ask(tag):
    out[tag] = _card_decide(key, slow(tag))

a = threading.Thread(target=ask, args=("A",)); a.start()
time.sleep(0.05)                                   # B arrives while A is still thinking
b = threading.Thread(target=ask, args=("B",)); b.start()
a.join(); b.join()

sources = sorted(v[1] for v in out.values())
check("two identical asks ran ONE computation", len(calls) == 1, "compute ran %d time(s)" % len(calls))
check("one is fresh and one joined", sources == ["fresh", "joined"], "sources %s" % sources)
check("both got the same card", out["A"][0]["card"] == out["B"][0]["card"] == "D3")
check("the joiner got the leader's answer",
      out["A"][0]["computed_by"] == out["B"][0]["computed_by"] == calls[0])
check("they are separate objects, not one shared", out["A"][0] is not out["B"][0])

# ---- 2. a third ask afterwards is answered from the finished result ----
calls.clear()
value, source = _card_decide(key, slow("C"))
check("an ask after it finished is cached", source == "cached" and not calls,
      "source=%s, computed %d more time(s)" % (source, len(calls)))
check("the cached card is the same one", value["card"] == "D3")

# ---- 3. a DIFFERENT question is never confused with it ----
calls.clear()
other = _card_key("lead", hand="K93.AKT3.643.KJ5", seat="E", dealer="N", vul="", ctx="P-1D-P-1S")
value, source = _card_decide(other, slow("D"))
check("one more call in the auction is a different question", source == "fresh" and len(calls) == 1)

# the key must notice every parameter that matters
base = dict(hand="A2.AKQ5.J983.764", seat="N", dealer="N", vul="NS", ctx="P-1N-P", played="D3HA")
distinct = {_card_key("play", **base)}
for field in base:
    changed = dict(base); changed[field] = base[field] + "X"
    distinct.add(_card_key("play", **changed))
check("every parameter changes the key", len(distinct) == len(base) + 1,
      "%d distinct keys from %d one-field changes" % (len(distinct), len(base)))
check("lead and play with the same parameters are different questions",
      _card_key("lead", **base) != _card_key("play", **base))

# ---- 4. a failing computation is reported to the joiner, not waited out ----
calls.clear()
boom = _card_key("play", hand="x", seat="S", dealer="N", vul="", ctx="", played="")
def fails():
    calls.append("boom")
    time.sleep(0.30)
    raise RuntimeError("BEN fell over")

errs = {}
def ask_bad(tag):
    try:
        _card_decide(boom, fails)
        errs[tag] = None
    except Exception as ex:
        errs[tag] = str(ex)

t0 = time.time()
x = threading.Thread(target=ask_bad, args=("A",)); x.start()
time.sleep(0.05)
y = threading.Thread(target=ask_bad, args=("B",)); y.start()
x.join(); y.join()
took = time.time() - t0
check("a failure reaches both, once", errs == {"A": "BEN fell over", "B": "BEN fell over"},
      str(errs))
check("the joiner is told at once, not after the 90 s timeout", took < 5,
      "both returned in %.2f s" % took)
check("a failure is not cached - the next ask tries again",
      _card_decide(boom, lambda: {"card": "SA"})[1] == "fresh")

# ---- 5. the cache expires ----
ns["CARD_CACHE_TTL"] = 0.25
calls.clear()
ttlkey = _card_key("lead", hand="ttl", seat="W", dealer="W", vul="", ctx="")
_card_decide(ttlkey, slow("E"))
check("still cached inside the window", _card_decide(ttlkey, slow("F"))[1] == "cached")
time.sleep(0.30)
check("recomputed once the window has passed", _card_decide(ttlkey, slow("G"))[1] == "fresh")

# ---- 6. nothing is left behind ----
check("no computation left marked as running", not ns["_card_running"],
      "%d left" % len(ns["_card_running"]))

# ---- 7. the real saving, as a timing ----
ns["CARD_CACHE_TTL"] = 60.0
NINE = 0.9                                  # a 9 s first card, scaled down by ten
def ninesec():
    time.sleep(NINE)
    return {"card": "SQ"}
slowkey = _card_key("play", hand="first", seat="W", dealer="N", vul="", ctx="1N-P-P-P", played="")
t0 = time.time()
th = threading.Thread(target=lambda: _card_decide(slowkey, ninesec)); th.start()
time.sleep(0.10)                            # the site's retry, arriving while BEN thinks
_card_decide(slowkey, ninesec)
th.join()
joined = time.time() - t0
check("a retry costs the wait, not another computation",
      joined < NINE * 1.6, "both answered in %.2f s; queued it would be ~%.2f s" % (joined, NINE * 2))

bad = [r for r in results if not r[1]]
print("\n%s: %d of %d checks passed" % ("FAIL" if bad else "PASS", len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
