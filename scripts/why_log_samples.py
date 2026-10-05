"""
Sample [ben-why] lines, without starting BEN.

The decision code needs TensorFlow and the native BGADLL, so the only way to see what a
line LOOKS like - and the only way to check that the keys it reads are the keys
CardResp/BidResp actually emit - is to build real response objects and drive the
formatters with them. That is what this does. It needs numpy and nothing else.

    python3 scripts/why_log_samples.py        # run from the repo root

Nine cases, including the three that are easy to get wrong: a decision where PIMC was
thrown out, a shortcut path with no candidates at all, and a path that never called
Why.start() - analysis and autoplay do not go through the routes, and must still not
raise. The last case feeds it NaN, None, inf and embedded newlines, because a log line
is not worth a dropped card.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from objects import Card, CardResp, CandidateCard, BidResp, CandidateBid
from nn.whylog import Why, log_lead, log_play, log_bid

def cc(sym, nn, dd=None, pmake=None, imp=None, msg=None):
    return CandidateCard(card=Card.from_symbol(sym), insta_score=nn,
                         expected_tricks_dd=dd, p_make_contract=pmake,
                         expected_score_imp=imp, msg=msg)

print("-- 1. the case that could not be traced: defending 4S, leads the KS from KJ4 --")
Why.start("room7/12")
Why.note(pimc_weight=0.25, pimc_rejected=False, engine="PIMCDef", playouts=100)
Why.card("SK", dd_tricks=2.40, dd_make=0.62, pimc_tricks=3.10, pimc_make=0.81,
         mrg_tricks=2.58, mrg_make=0.67)
Why.card("S4", dd_tricks=2.55, dd_make=0.66, pimc_tricks=2.20, pimc_make=0.55,
         mrg_tricks=2.46, mrg_make=0.63)
Why.dropped("SJ", 0.004, 0.02)
log_play(CardResp(card=Card.from_symbol("SK"),
                  candidates=[cc("SK", 0.412, 2.58, 0.67, 1.20),
                              cc("S4", 0.301, 2.46, 0.63, 0.40)],
                  samples=["x"] * 200, shape=-1, hcp=-1, quality=0.42,
                  who="PIMC-BEN-IMP", claim=-1).to_dict(), "W", 5, "Calculated")

print("-- 2. a shortcut that never reaches a net --")
Why.start("room7/12")
log_play(CardResp(card=Card.from_symbol("H7"), candidates=[], samples=[], shape=-1,
                  hcp=-1, quality=None, who="Forced", claim=-1).to_dict(), "N", 9, "Forced")

print("-- 3. PIMC thrown out for the whole decision --")
Why.start("-")
Why.note(pimc_weight=None, pimc_rejected=True,
         pimc_reject_reason="zero-trick PIMC outlier", engine="PIMC", playouts=14)
Why.card("HA", dd_tricks=9.10, dd_make=0.74, mrg_tricks=9.10, mrg_make=0.74)
log_play(CardResp(card=Card.from_symbol("HA"), candidates=[cc("HA", 0.88, 9.10, 0.74, 2.1)],
                  samples=["x"] * 120, shape=-1, hcp=-1, quality=0.31,
                  who="PIMC-BEN-IMP", claim=-1).to_dict(), "S", 2, "Calculated")

print("-- 4. opening lead chosen by simulation --")
Why.start("room7/12")
log_lead(CardResp(card=Card.from_symbol("D3"),
                  candidates=[cc("D3", 0.219, 9.80, 0.41, 1.20),
                              cc("SK", 0.402, 10.60, 0.22, -0.90, msg="suit adjust=-0.5")],
                  samples=["x"] * 200, shape=-1, hcp=-1, quality=0.55,
                  who="Simulation (IMP)", claim=-1).to_dict(),
         "W", "4SE", "KJ4.A82.Q973.T52", 0.999)

print("-- 5. opening lead taken straight from the net --")
Why.start("-")
log_lead(CardResp(card=Card.from_symbol("HA"), candidates=[cc("HA", 0.9971)],
                  samples=[], shape=-1, hcp=-1, quality=None,
                  who="NN - best", claim=-1).to_dict(),
         "N", "3NTS", "A2.AKQ5.J983.764", 0.99)

def cb(b, nn, score=None, imp=None, tricks=None, adj=None, who=None):
    return CandidateBid(bid=b, insta_score=nn, expected_score=score, expected_imp=imp,
                        expected_tricks=tricks, adjust=adj, alert=None, who=who,
                        explanation=None)
print("-- 6. a bid that searched, and one that did not --")
Why.start("room7/12")
log_bid(BidResp(bid="4S", candidates=[cb("4S", 0.61, imp=1.42, tricks=10.1, adj=0),
                                      cb("3S", 0.28, imp=0.30, tricks=9.8, adj=0)],
                samples=["x"] * 120, shape=-1, hcp=-1, who="Simulation",
                quality=0.35, alert=None, explanation=None).to_dict(),
        "S", "N", "NS", "P-1S-P")
Why.start("-")
log_bid(BidResp(bid="PASS", candidates=[cb("PASS", 0.993)], samples=[], shape=-1, hcp=-1,
                who="NN", quality=None, alert=None, explanation=None).to_dict(),
        "E", "N", "", "P-1S")

print("-- 7. card CODES, as the real call sites pass them (0=SA .. 51=C2) --")
Why.start("-")
Why.note(pimc_weight=0.25, pimc_rejected=False, playouts=100)
Why.card(0, dd_tricks=2.4, dd_make=0.62, pimc_tricks=3.1, pimc_make=0.81)
Why.dropped(9, 0.004, 0.02)
log_play(CardResp(card=Card.from_code(0), candidates=[cc("SA", 0.5, 2.5, 0.6)],
                  samples=[], shape=-1, hcp=-1, quality=0.4,
                  who="PIMC-BEN-IMP", claim=-1).to_dict(), "E", 3, "Calculated")

print("-- 8. nothing recorded at all (analysis / autoplay never call start) --")
import nn.whylog as W
W.Why._local.__dict__.pop('d', None)
Why.card(0, dd_tricks=1.0); Why.dropped(1, 0.1, 0.2); Why.note(x=1)
log_play(CardResp(card=Card.from_code(0), candidates=[], samples=[], shape=-1, hcp=-1,
                  quality=None, who="BEN-IMP", claim=-1).to_dict(), "E", 3, "Calculated")

print("-- 9. junk in, still one line out --")
Why.start("-")
Why.card(0, dd_tricks=float('nan'), dd_make=None)
Why.note(pimc_weight=float('inf'))
log_play({"card": "SA", "who": "a\nrule\twith\nnewlines", "candidates": [{"card": "SA"}]},
         "E", 3, "Calculated")
log_lead({"card": "SA", "who": None, "candidates": [{"card": "SA", "insta_score": None}]},
         "W", None, None, None)
log_bid({"bid": None, "who": None}, "S", None, None, None)
log_play(None, "E", 3, "Calculated")
print("-- survived --")
