#!/usr/bin/env python3
"""
HOW MANY CARDS DIFFER, POSITION BY POSITION.

Two setups left to play a board each go their own way after the first card they disagree on,
so counting differences between two finished boards mostly counts the consequences of the
first one. This asks the second setup the SAME question the baseline was asked, at every
position of the baseline's own play - its exact request, replayed - and compares the answers.

    shadow.py RAW_BASELINE.json NAME OUT
"""
import json, os, sys, time
import lib

raw_path, name, out_name = sys.argv[1:4]
out = {"shadow": name, "of": os.path.basename(raw_path), "boards": []}
t_all = time.time()
tot = {"cards": 0, "differ": 0, "unforced": 0, "unforced_differ": 0}
for b in json.load(open(raw_path))["boards"]:
    rows = []
    for r in b["tables"]["self"]:
        params = dict(r["params"], room="shadow-" + str(r["params"].get("room")))
        st, js, dt, lines = lib.safe_call(name, "/lead" if r["kind"] == "lead" else "/play", params,
                                          what="shadow deal %s" % b["deal"])
        row = {"n": r["n"], "kind": r["kind"], "seat": r["seat"], "trick": r["trick"], "forced": r["forced"],
               "base": r["answer"], "card": js.get("card"), "seconds": dt, "base_seconds": r["seconds"]}
        row.update(lib.why(lines))
        rows.append(row)
        tot["cards"] += 1
        tot["differ"] += row["card"] != row["base"]
        if not r["forced"]:
            tot["unforced"] += 1
            tot["unforced_differ"] += row["card"] != row["base"]
    out["boards"].append({"deal": b["deal"], "differ": sum(x["card"] != x["base"] for x in rows), "cards": rows})
    out.update(totals=tot, wall_seconds=time.time() - t_all, crashes=lib.CRASHES)
    lib.dump(os.path.join(lib.HERE, "results", out_name + ".json"), out)
    print("deal %2d  differ %d of %d" % (b["deal"], out["boards"][-1]["differ"], len(rows)), flush=True)
print("done %.0fs" % (time.time() - t_all), tot, flush=True)
