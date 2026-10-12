#!/usr/bin/env python3
"""
Turn the result files into one table, and say what is larger than the noise.

    summary.py            reads results/A-self.json, results/<X>-vs-A.json, results/B-shadow.json
                          writes results/summary.json and results/summary.md

TRICKS GIVEN AWAY are counted against double dummy, per board. For the baseline they come from
its own four-handed play. For another setup X they come from its match against the baseline:
its declarer play from the table where it declares, its defence and its opening lead from the
table where it defends - so every setup's fifty-two cards a board are counted once.

IMPS are X's, per board, from the two tables of the match.

NOISE. Each figure is given with its standard error over the boards. A difference is called
larger than the noise when it is more than twice its standard error away from zero; when it
is not, "boards to settle" is how many boards would be needed for a difference of the size
seen to reach that, if it is real: (2 x standard deviation / mean) squared.
"""
import json, math, os, statistics as st
import lib

RES = os.path.join(lib.HERE, "results")


def load(name):
    p = os.path.join(RES, name + ".json")
    return json.load(open(p)) if os.path.exists(p) else None


def mean_se(xs):
    n = len(xs)
    if n == 0:
        return {"n": 0}
    m = sum(xs) / n
    sd = st.stdev(xs) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n > 1 else 0.0
    out = {"n": n, "mean": round(m, 3), "sd": round(sd, 3), "se": round(se, 3)}
    out["beyond_noise"] = bool(se and abs(m) > 2 * se)
    if m and sd and not out["beyond_noise"]:
        out["boards_to_settle"] = int(math.ceil((2 * sd / abs(m)) ** 2))
    return out


def layouts(cards, letter):
    """Of the setup's own calculated cards: how many rested on exactly 12 layouts, and on fewer than 50."""
    own = [c for c in cards if c["service"].startswith(letter)]
    calc = [c for c in own if c.get("path") == "Calculated" and c["kind"] == "play"]
    return {"cards": len(own), "unforced": sum(not c["forced"] for c in own), "calculated": len(calc),
            "on_12_layouts": sum(c.get("layouts") == 12 for c in calc),
            "under_50_layouts": sum(c.get("layouts", 999) < 50 for c in calc),
            "net_fallback": sum("fallback" in (c.get("rule") or "") for c in own),
            "seconds": round(sum(c["seconds"] for c in own), 1),
            "think_ms_per_calculated": round(sum(c.get("think_ms", 0) for c in calc) / len(calc)) if calc else None,
            "nn_ms_per_calculated": round(sum(c.get("nn_ms", 0) for c in calc) / len(calc)) if calc else None,
            "slowest_card_s": round(max([c["seconds"] for c in own] or [0]), 1)}


out = {"setups": {}}
a = load("A-self")
base = {}
if a:
    cards = []
    for b in a["boards"]:
        t = b["tables"]["self"]
        if t.get("error") or t.get("declarer_tricks") is None:
            continue
        base[b["deal"]] = {"declarer": t["dd_lost"]["declarer"], "defence": t["dd_lost"]["defence"],
                           "lead": t["dd_lost"]["lead"], "played": t["played"], "tricks": t["declarer_tricks"]}
        cards += t["cards"]
    out["setups"]["A"] = {
        "boards": len(base), "errors": len(a["boards"]) - len(base),
        "tricks_given_away_per_board": {k: mean_se([v[k] for v in base.values()]) for k in ("declarer", "defence", "lead")},
        "own_cards": layouts(cards, "A"), "wall_seconds": round(a["wall_seconds"]), "crashes": len(a.get("crashes") or []),
        "loadavg": [a.get("loadavg_start"), a.get("loadavg_end")]}

for x in ("B", "C", "D"):
    m = load("%s-vs-A" % x)
    if not m:
        continue
    rows, cards, imps, base_mismatch, base_checked = {}, [], [], 0, 0
    for b in m["boards"]:
        xd, bd = b["tables"].get("x_declares", {}), b["tables"].get("base_declares", {})
        if xd.get("declarer_tricks") is None or bd.get("declarer_tricks") is None or b["deal"] not in base:
            continue
        rows[b["deal"]] = {"declarer": xd["dd_lost"]["declarer"], "defence": bd["dd_lost"]["defence"],
                           "lead": bd["dd_lost"]["lead"]}
        cards += xd["cards"] + bd["cards"]
        if b.get("x_imps") is not None:
            imps.append(b["x_imps"])
        # THE BASELINE AGAINST ITSELF: while a table's play is still card for card the baseline's
        # own four-handed play, a baseline instance asked for the next card must give the same one.
        ref = base[b["deal"]]["played"]
        for t in (xd, bd):
            for c in t["cards"]:
                i = c["n"]
                if t["played"][:2 * i] != ref[:2 * i]:
                    break
                if c["service"].startswith("A"):
                    base_checked += 1
                    base_mismatch += c["answer"] != ref[2 * i:2 * i + 2]
    deals = sorted(rows)
    s = {"boards": len(rows), "errors": len(m["boards"]) - len(rows),
         "tricks_given_away_per_board": {k: mean_se([rows[d][k] for d in deals]) for k in ("declarer", "defence", "lead")},
         "tricks_against_A_per_board": {k: mean_se([rows[d][k] - base[d][k] for d in deals]) for k in ("declarer", "defence", "lead")},
         "imps_per_board_against_A": dict(mean_se(imps), total=sum(imps), won=sum(i > 0 for i in imps),
                                          lost=sum(i < 0 for i in imps), flat=sum(i == 0 for i in imps)),
         "own_cards": layouts(cards, x), "wall_seconds": round(m["wall_seconds"]), "crashes": len(m.get("crashes") or []),
         "baseline_repeats_itself": {"checked": base_checked, "different": base_mismatch},
         "loadavg": [m.get("loadavg_start"), m.get("loadavg_end")]}
    out["setups"][x] = s

sh = load("B-shadow")
if sh:
    t = sh["totals"]
    slow = [c for b in sh["boards"] for c in b["cards"]]
    out["B_position_by_position"] = dict(t, boards_with_a_difference=sum(1 for b in sh["boards"] if b["differ"]),
                                         boards=len(sh["boards"]), wall_seconds=round(sh["wall_seconds"]),
                                         seconds_B=round(sum(c["seconds"] for c in slow), 1),
                                         seconds_A_same_questions=round(sum(c["base_seconds"] for c in slow), 1))

json.dump(out, open(os.path.join(RES, "summary.json"), "w"), indent=1)


def f(d, digits=2):
    if not d or not d.get("n"):
        return "-"
    return ("%+." + str(digits) + "f ±%." + str(digits) + "f") % (d["mean"], d["se"])


def verdict(d):
    if not d or not d.get("n"):
        return "-"
    if d["beyond_noise"]:
        return "larger than the noise"
    return "within the noise" + (" (about %d boards to settle)" % d["boards_to_settle"] if d.get("boards_to_settle") else "")


L = ["# Card-play benchmark: results", "",
     "Figures are a mean per board ± one standard error. Tricks given away are against double dummy.", "",
     "| setup | boards | declarer | defence | lead | IMPs a board against A | calculated cards | on 12 layouts | run |",
     "|---|---|---|---|---|---|---|---|---|"]
for k, s in out["setups"].items():
    t, oc = s["tricks_given_away_per_board"], s["own_cards"]
    im = s.get("imps_per_board_against_A")
    L.append("| %s | %d | %s | %s | %s | %s | %d | %d (%.0f%%) | %d min |" % (
        k, s["boards"], f(t["declarer"])[1:], f(t["defence"])[1:], f(t["lead"])[1:], f(im) if im else "baseline",
        oc["calculated"], oc["on_12_layouts"], 100.0 * oc["on_12_layouts"] / max(1, oc["calculated"]),
        round(s["wall_seconds"] / 60)))
L += ["", "## Against the baseline, board by board", "",
      "| setup | declarer tricks | defence tricks | lead tricks | IMPs | won / lost / flat |", "|---|---|---|---|---|---|"]
for k, s in out["setups"].items():
    if k == "A":
        continue
    d, im = s["tricks_against_A_per_board"], s["imps_per_board_against_A"]
    L.append("| %s | %s, %s | %s, %s | %s, %s | %s, %s | %d / %d / %d |" % (
        k, f(d["declarer"]), verdict(d["declarer"]), f(d["defence"]), verdict(d["defence"]), f(d["lead"]),
        verdict(d["lead"]), f(im), verdict(im), im["won"], im["lost"], im["flat"]))
if "B_position_by_position" in out:
    p = out["B_position_by_position"]
    L += ["", "## B against A, the same question at every position of A's play", "",
          "%d of %d cards differ (%d of %d where there was a choice), on %d of %d boards." % (
              p["differ"], p["cards"], p["unforced_differ"], p["unforced"], p["boards_with_a_difference"], p["boards"]),
          "Answering those questions took B %.0f s and had taken A %.0f s." % (p["seconds_B"], p["seconds_A_same_questions"])]
open(os.path.join(RES, "summary.md"), "w").write("\n".join(L) + "\n")
print("\n".join(L))
