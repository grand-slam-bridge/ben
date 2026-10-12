#!/usr/bin/env python3
"""
Deal the candidate boards. The same seed as the harness and the 2026-10-10 measurement, so the
first twenty are the deals those used. Standard board numbers, dealer and vulnerability.

    mkdeals.py N OUT.json
"""
import json, sys
import lib
from lib import H

n, out_path = int(sys.argv[1]), sys.argv[2]
out = []
for i, hands in enumerate(H.make_deals(n, seed=20261005)):
    board, dealer, vul = lib.board_info(i)
    tbl, _ = lib.dd_table(hands)
    out.append({"deal": i, "board": board, "dealer": dealer, "vul": vul, "pbn": H.deal_pbn(hands),
                "hands": {s: H.hand_pbn(hands[k]) for k, s in enumerate("NESW")},
                "cards": {s: [H.card_str(c) for c in hands[k]] for k, s in enumerate("NESW")},
                "dd_table_strain_SHDCN_by_decl_NESW": tbl})
json.dump(out, open(out_path, "w"), indent=1)
assert lib.score(4, "S", 0, True, 10) == 620 and lib.score(3, "N", 0, False, 10) == 430
assert lib.score(4, "S", 1, True, 7) == -800 and lib.score(7, "N", 0, False, 13) == 1520
assert lib.imps(430 - (-50)) == 10 and lib.imps(-10) == 0 and lib.imps(-1400) == -16
print("dealt", n, "->", out_path)
