#!/usr/bin/env python3
"""
Play the fixed boards and score every card against double dummy.

    play_run.py self  A        OUT    A plays all four seats
    play_run.py match X  A     OUT    two tables a board: X declares against A's defence,
                                      and A declares against X's defence

In a match, X's IMPs on a board are the difference between the declaring side's score at the
two tables, at the board's real vulnerability: X declaring better, or X defending better,
both show up as IMPs to X. The auction and the contract are the ones in data/deals60.json.

Writes OUT.json (what is committed: no requests, no raw logs) and BENCH_WORK/raw-<OUT>.json
(everything, which shadow.py needs).
"""
import json, os, sys, time
import lib
from lib import SEATS

mode = sys.argv[1]
if mode == "self":
    x, base, out_name = sys.argv[2], sys.argv[2], sys.argv[3]
    tables = [("self", x, x)]
else:
    x, base, out_name = sys.argv[2], sys.argv[3], sys.argv[4]
    tables = [("x_declares", x, base), ("base_declares", base, x)]

out_path = os.path.join(lib.HERE, "results", out_name + ".json")
raw_path = os.path.join(lib.WORK, "raw-" + out_name + ".json")
out = {"mode": mode, "x": x, "base": base, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
       "loadavg_start": os.getloadavg(), "boards": []}
raw = {"boards": []}
t_all = time.time()
for d in lib.load_deals():
    hands = lib.hands_of(d)
    c, vul = d["contract"], d["vul"]
    decl = c["declarer_i"]
    b = {"deal": d["deal"], "board": d["board"], "vul": vul, "contract": c["text"], "dd_tricks": d["dd_tricks"],
         "tables": {}}
    rb = {"deal": d["deal"], "tables": {}}
    for table, declarer, defence in tables:
        owner = {s: (declarer if s % 2 == decl % 2 else defence) for s in range(4)}
        tag = "%s-%s-d%02d" % (out_name, table[0], d["deal"])
        t0 = time.time()
        try:
            p = lib.run_play(hands, d["dealer"], "" if vul == "None" else vul, d["ctx"], c["strain"], decl, owner,
                             tag, d["board"], tournament="imps", details="false")
            tr = p["declarer_tricks"]
            t = {"declarer": declarer, "defence": defence, "declarer_tricks": tr, "error": p.get("error"),
                 "dd_lost": lib.score_play(p["records"], c["strain"], decl),
                 "declarer_score": lib.decl_score(c, vul, tr) if tr is not None else None,
                 "played": p.get("played"), "cards": [lib.slim(r) for r in p["records"]]}
            rb["tables"][table] = [{k: v for k, v in r.items() if k not in ("snapshot", "dd_values")}
                                   for r in p["records"]]
        except Exception as ex:
            t = {"declarer": declarer, "defence": defence, "error": "%s: %s" % (type(ex).__name__, str(ex)[:300])}
        t["seconds"] = time.time() - t0
        b["tables"][table] = t
    if mode == "match":
        a, o = b["tables"]["x_declares"], b["tables"]["base_declares"]
        if a.get("declarer_score") is not None and o.get("declarer_score") is not None:
            b["x_imps"] = lib.imps(a["declarer_score"] - o["declarer_score"])
    out["boards"].append(b)
    raw["boards"].append(rb)
    out["crashes"] = lib.CRASHES
    out["wall_seconds"] = time.time() - t_all
    lib.dump(out_path, out)
    lib.dump(raw_path, raw)
    print("deal %2d %-6s dd %2d | " % (d["deal"], c["text"], d["dd_tricks"]) + " | ".join(
        "%s %s made %s lost %s %.0fs%s" % (k, v.get("declarer"), v.get("declarer_tricks"), v.get("dd_lost"),
                                            v["seconds"], " ERR " + v["error"] if v.get("error") else "")
        for k, v in b["tables"].items()) + ("" if mode == "self" else " | %s imps %s" % (x, b.get("x_imps"))),
        flush=True)
out["loadavg_end"] = os.getloadavg()
lib.dump(out_path, out)
print("done %.0fs" % (time.time() - t_all), flush=True)
