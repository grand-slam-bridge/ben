#!/usr/bin/env python3
"""
BEN BIDS EACH DEAL ONCE, and that auction and contract are then fixed for every setup.

The baseline service bids all four seats, asked the way the website asks. A deal that is
passed out has no card play to measure and is left out; the first WANT deals that reach a
contract are written to data/deals60.json, each with its auction, and that file is what every
later run plays. So every setup declares the same contract after the same auction, and what
differs between them is the card play alone.

    auctions.py SERVICE CANDIDATES.json WANT
"""
import json, sys, time
import lib

name, cand_path, want = sys.argv[1], sys.argv[2], int(sys.argv[3])
owner = {i: name for i in range(4)}
kept, skipped = [], []
t0 = time.time()
for d in lib.load_deals(cand_path):
    if len(kept) == want:
        break
    hands = lib.hands_of(d)
    a = lib.run_auction(hands, d["dealer"], d["vul"], owner, "auc-d%02d" % d["deal"], d["board"])
    c = a.get("contract")
    if a.get("error"):
        # A deal is left out for being passed out and for nothing else. An answer that is not
        # a call - a rate limit, a fault - stops the run: skipping it would quietly change
        # which boards every setup is measured on.
        sys.exit("deal %d: %s" % (d["deal"], a["error"]))
    if not c:
        skipped.append({"deal": d["deal"], "why": "passed out", "calls": a["calls"]})
        print("deal %2d  left out: %s" % (d["deal"], skipped[-1]["why"]), flush=True)
        continue
    d = dict(d, auction=a["calls"], ctx=a["ctx"], contract=c,
             dd_tricks=d["dd_table_strain_SHDCN_by_decl_NESW"]["SHDCN".index(c["strain"])][c["declarer_i"]])
    kept.append(d)
    print("deal %2d  bd %2d %s %-4s  %-6s dd %2d  %s" % (d["deal"], d["board"], d["dealer"], d["vul"], c["text"],
          d["dd_tricks"], a["ctx"]), flush=True)
if len(kept) < want:
    sys.exit("only %d deals reached a contract, wanted %d - deal more candidates" % (len(kept), want))
json.dump(kept, open(lib.DEALS, "w"), indent=1)
json.dump({"bid_by": name, "seconds": time.time() - t0, "kept": len(kept), "left_out": skipped},
          open(lib.DEALS.replace(".json", "-auctions.json"), "w"), indent=1)
print("kept %d, left out %d, %.0f s -> %s" % (len(kept), len(skipped), time.time() - t0, lib.DEALS))
