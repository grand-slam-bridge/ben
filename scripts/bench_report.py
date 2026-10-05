#!/usr/bin/env python3
"""
Read the benchmark's per-setting JSON and print the comparison (2026-10-05).

    python3 scripts/bench_report.py /tmp/bench10/out

Reports, per setting: tricks given away per board as declarer and in defence, how often
the card differed from double dummy, PIMC's zero-playout and rejected counts, and time
per card as a RATIO to the deployed setting - first three tricks and the rest apart,
because the early tricks are where the cost is and this machine's absolute times mean
nothing against Render.

Then the opening leads on their own, then the worst individual decisions.
"""
import json
import os
import sys
import glob

ORDER = ["deployed", "stop8", "upstream", "pimc-off", "net-alone", "lead100"]
HONOURS = "AKQJ"
NEXT_LOWER = {"A": "K", "K": "Q", "Q": "J", "J": "T"}


def load(d):
    out = {}
    for f in glob.glob(os.path.join(d, "results-*.json")):
        try:
            r = json.load(open(f))
        except Exception as ex:
            print("  (could not read %s: %s)" % (os.path.basename(f), ex))
            continue
        out[r["label"]] = r
    return out


def card_times(boards):
    """(first three tricks, the rest) as lists of seconds."""
    early, late = [], []
    for b in boards:
        for trick, dt in b.get("cards", []):
            (early if trick < 3 else late).append(dt)
    return early, late


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def suit_of(card):
    return card[0]


def rank_of(card):
    return card[1]


def hand_suit(pbn, suit):
    """The cards held in one suit of a PBN hand, e.g. 'AQ9'."""
    i = "SHDC".index(suit)
    parts = pbn.split(".")
    return parts[i] if i < len(parts) else ""


def lead_flags(lead):
    """(net rated it unlikely, trump honour, unsupported honour)."""
    card = lead.get("card") or ""
    if len(card) < 2:
        return False, False, False
    s, r = suit_of(card), rank_of(card)
    # What the lead net gave the card it actually chose.
    nn = None
    for c in lead.get("candidates") or []:
        if c.get("card") == card or c.get("card") == s + "x":
            nn = c.get("insta_score")
            break
    # lead_threshold is 0.20 - below it a card is not even simulated, so a chosen lead
    # the net scored under that is one the net thought unlikely.
    unlikely = (nn is not None and nn < 0.20)
    trump_honour = (lead.get("trump") == s and r in HONOURS)
    held = hand_suit(lead.get("hand") or "", s)
    unsupported = (r in HONOURS and NEXT_LOWER.get(r, "") not in held)
    return unlikely, trump_honour, unsupported


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bench10/out"
    res = load(d)
    if not res:
        print("no results in " + d)
        return 1

    base = res.get("deployed")
    base_early, base_late = card_times(base["boards"]) if base else ([], [])

    print("\n=== PER SETTING (%d deals) ===\n" % (base["deals"] if base else 0))
    hdr = ("%-11s %7s %7s %8s %8s %7s %7s %7s %8s %8s" %
           ("setting", "boards", "errors", "lostDecl", "lostDef", "differs",
            "pimc0", "pimcRej", "t1-3", "t4-13"))
    print(hdr)
    print("-" * len(hdr))
    for label in ORDER:
        r = res.get(label)
        if not r:
            print("%-11s  (not run)" % label)
            continue
        b = r["boards"]
        n = len(b) or 1
        e, l = card_times(b)
        re_ = mean(e) / mean(base_early) if base_early and mean(base_early) else 0
        rl = mean(l) / mean(base_late) if base_late and mean(base_late) else 0
        print("%-11s %7d %7d %8.2f %8.2f %7.1f %7d %7d %8s %8s" % (
            label, len(b), len(r["errors"]),
            sum(x["lost"]["declarer"] for x in b) / n,
            sum(x["lost"]["defence"] for x in b) / n,
            sum(x["differs"] for x in b) / n,
            sum(x.get("zero_playouts", 0) for x in b),
            sum(x.get("pimc_rejected", 0) for x in b),
            ("%.2fx" % re_) if re_ else "-",
            ("%.2fx" % rl) if rl else "-"))
    print("\nlostDecl / lostDef = tricks given away per board; differs = cards per board")
    print("that were not a double-dummy best card; t1-3 / t4-13 = seconds per card as a")
    print("ratio to deployed (this machine, so only the ratio means anything).")

    print("\n=== OPENING LEADS ===\n")
    hdr2 = "%-11s %7s %10s %12s %14s %10s" % (
        "setting", "leads", "lostTrick", "netUnlikely", "trumpHonour", "unsupHon")
    print(hdr2)
    print("-" * len(hdr2))
    for label in ORDER:
        r = res.get(label)
        if not r:
            continue
        leads = [x["lead"] for x in r["boards"] if x.get("lead")]
        if not leads:
            print("%-11s  (none)" % label)
            continue
        f = [lead_flags(x) for x in leads]
        print("%-11s %7d %10.2f %12d %14d %10d" % (
            label, len(leads), sum(x["lost"] for x in leads) / len(leads),
            sum(1 for u, _, _ in f if u), sum(1 for _, t, _ in f if t),
            sum(1 for _, _, h in f if h)))
    print("\nlostTrick = tricks the lead itself gave away, per board. netUnlikely = the")
    print("lead net scored the chosen card under lead_threshold (0.20). unsupHon = an")
    print("honour led without the honour immediately below it.")

    if base:
        print("\n=== WORST CARDS, deployed ===")
        allw = []
        for b in base["boards"]:
            for w in b.get("worst", []):
                w = dict(w); w["deal"] = b["deal"]; w["contract"] = b["contract"]
                allw.append(w)
        allw.sort(key=lambda x: -x["lost"])
        for w in allw[:5]:
            print("\n  deal %s  %s  trick %s  %s played %s, better %s  (-%g tricks)" % (
                w["deal"], w["contract"], w["trick"], w["seat"], w["played"],
                "/".join(w["better"]), w["lost"]))
            print("    hand %s     rule: %s" % (w["hand"], w.get("who")))
            for c in w.get("candidates", [])[:4]:
                print("      %s" % json.dumps(c))

        print("\n=== WORST LEADS, deployed ===")
        leads = [dict(x["lead"], deal=x["deal"]) for x in base["boards"] if x.get("lead")]
        leads.sort(key=lambda x: -x["lost"])
        for L in leads[:3]:
            u, t, h = lead_flags(L)
            print("\n  deal %s  %s  led %s from %s  (-%g tricks)  best %s" % (
                L["deal"], L["contract"], L["card"], L["hand"], L["lost"],
                "/".join(L.get("best", []))))
            print("    rule: %s   net-unlikely=%s trump-honour=%s unsupported-honour=%s"
                  % (L.get("who"), u, t, h))
            for c in L.get("candidates", [])[:4]:
                print("      %s" % json.dumps(c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
