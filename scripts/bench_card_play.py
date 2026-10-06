#!/usr/bin/env python3
"""
CARD-PLAY BENCHMARK: how many tricks does BEN give away? (2026-10-05)

Robots in all four seats play fixed deals at a contract fixed in advance, so only the
CARD PLAY is under test - no bidding, no contract luck. Every card is scored against
double dummy: DDS is asked what every legal card is worth to the player on play, and the
card BEN chose is compared with the best of them. The difference is the trick it gave
away, and those are added up per board.

The same is done for the opening lead, reported separately, because the lead is chosen by
a different mechanism (see docs/bench-card-play-quality.md) and is the one decision made
without sight of dummy.

BEN answers over HTTP, exactly as the site asks it - /lead for the opening lead and /play
for every card after - so what is measured is the deployed path and not an internal
short-cut. DDS runs in this process.

    python3 scripts/bench_card_play.py --deals 10 --out results.json
    python3 scripts/bench_card_play.py --self-test        # scoring only, no service

The service must already be running with the settings under test; this script does not
start it. See scripts/bench_run_all.sh, which starts one per setting.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

RANKS = "AKQJT98765432"
SUITS = "SHDC"
SEATS = "NESW"


# ---------------------------------------------------------------- cards

def card_str(c):
    """0-51 -> 'SA'. Suit-major, ace high, the same order BEN's symbols use."""
    return SUITS[c // 13] + RANKS[c % 13]


def card_code(s):
    return SUITS.index(s[0]) * 13 + RANKS.index(s[1])


def hand_pbn(cards):
    suits = [[], [], [], []]
    for c in sorted(cards):
        suits[c // 13].append(RANKS[c % 13])
    return ".".join("".join(s) for s in suits)


def deal_pbn(hands, first="N"):
    """PBN with the deal written from `first` clockwise."""
    order = [(SEATS.index(first) + i) % 4 for i in range(4)]
    return first + ":" + " ".join(hand_pbn(hands[i]) for i in order)


def make_deals(n, seed=20261005):
    """The same n deals every run, so settings are compared on identical hands."""
    import random
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        deck = list(range(52))
        rng.shuffle(deck)
        out.append([sorted(deck[i * 13:(i + 1) * 13]) for i in range(4)])
    return out


def contract_score(level, strain, tricks):
    """
    Duplicate score for a made contract, not vulnerable, undoubled. Only ever used to
    RANK contracts when fixing one in advance, so the fine print (insult, part-score
    bonuses at the margin) does not change which deal gets which contract.
    """
    per = 30 if strain in (0, 1, 4) else 20            # majors and NT 30, minors 20
    base = per * level + (10 if strain == 4 else 0)    # NT first trick is 40
    over = (tricks - 6 - level) * per
    if base >= 100:
        bonus = 300                                    # game, not vulnerable
        if level == 6:
            bonus += 500
        elif level == 7:
            bonus += 1000
    else:
        bonus = 50
    # A lower level scoring the same is the one a human would bid, so break ties downward
    # by shaving a point per level. It only ever decides between equal scores.
    return base + over + bonus - level


# ---------------------------------------------------------------- double dummy

class DD:
    """Just the two things this benchmark needs from the solver."""

    def __init__(self):
        import dds3
        self.dds3 = dds3
        self.ctx = dds3.SolverContext()

    def best_contract(self, hands):
        """
        The contract fixed in advance, from the double-dummy table: the highest-scoring
        contract anybody can make. No bidding is involved, so what is measured is the
        card play and never the auction - and it is the same contract for every setting,
        because it depends on the deal alone.

        res_table[strain][declarer], strain 0-4 = S H D C NT, declarer 0-3 = N E S W.
        """
        res = self.dds3.calc_all_tables_pbn([deal_pbn(hands)], mode=0)
        tables = res.get("tables") or []
        if not tables:
            return None
        rt = tables[0]["res_table"]
        best = None
        for strain in range(5):
            for decl in range(4):
                tricks = rt[strain][decl]
                level = tricks - 6
                if level < 1:
                    continue
                sc = contract_score(level, strain, tricks)
                if best is None or sc > best[0]:
                    best = (sc, level, strain, decl)
        if best is None:
            return None
        _, level, strain, decl = best
        return str(level) + "SHDCN"[strain], decl

    def card_values(self, hands, trump, leader, current_trick):
        """
        What every legal card is worth to the player on play, in tricks for THEIR side.

        current_trick is a list of 0-3 card codes already played to this trick, and
        `leader` is the seat index that led it. Returns {card_code: tricks}.
        """
        to_play = (leader + len(current_trick)) % 4
        pbn = deal_pbn(hands, SEATS[to_play])
        suit = [0, 0, 0]
        rank = [0, 0, 0]
        for i, c in enumerate(current_trick[:3]):
            suit[i] = c // 13
            rank[i] = 14 - (c % 13)
        r = self.dds3.solve_board_pbn(
            pbn, trump=trump, first=leader,
            current_trick_suit=tuple(suit), current_trick_rank=tuple(rank),
            target=-1, solutions=3, mode=1, context=self.ctx)
        out = {}
        for i in range(r["cards"]):
            s, rk, sc = r["suit"][i], r["rank"][i], r["score"][i]
            out[s * 13 + (14 - rk)] = sc
            # `equals` is a bitmask of equally-ranked cards that score the same.
            eq = r["equals"][i]
            for bit in range(2, 15):
                if eq & (1 << bit):
                    out[s * 13 + (14 - bit)] = sc
        return out


# ---------------------------------------------------------------- BEN over HTTP

class Ben:
    # 90 s dropped a board: upstream lost deal 7 to "TimeoutError: timed out", and a
    # dropped board is worse than a slow one because the settings no longer share the
    # same deals. The slowest single card measured here was 73.7 s, and upstream is
    # ~1.8x deployed on early cards, so 300 s leaves real headroom.
    def __init__(self, base, timeout=300):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.calls = 0
        self.time = 0.0

    def get(self, path, params):
        url = self.base + path + "?" + urllib.parse.urlencode(params)
        t0 = time.time()
        with urllib.request.urlopen(url, timeout=self.timeout) as r:
            body = r.read().decode("utf-8")
        dt = time.time() - t0
        self.calls += 1
        self.time += dt
        return json.loads(body), dt


def ctx_for(contract, declarer_i, dealer_i):
    """
    An auction that ends in the contract we fixed, so BEN sees a consistent position.

    Everyone passes until the declarer bids it and three pass. It is not a REAL auction -
    it carries no information - which is deliberate: the benchmark is about card play, and
    a fabricated auction that implied a system would bias the sampling.
    """
    calls = []
    seat = dealer_i
    while seat != declarer_i:
        calls.append("P")
        seat = (seat + 1) % 4
    calls.append(contract)
    calls += ["P", "P", "P"]
    return "-".join(calls)


# ---------------------------------------------------------------- one board

def play_board(ben, dd, hands, contract, declarer_i, dealer_i, trace=None):
    """
    Play one board out, then score it.

    TWO PASSES, AND THE ORDER MATTERS (2026-10-05). The first version solved a DDS
    position for every card AS IT WAS PLAYED, which put the scorer on the same two cores
    as the service - and the service is itself configured for two DDS threads and two
    PIMC threads. PIMC is given one second of wall clock (pimc_wait) and simply completes
    fewer playouts when it is starved, so the first run measured a BEN that had been
    given 10 playouts where the config asks for 100. That is not the robot anybody
    deploys, and no comparison between settings could survive it.

    So nothing is solved while BEN is thinking. The board is played first, recording the
    position before every card, and the solver runs afterwards over that record. The
    numbers are identical - double dummy does not care when it is asked - and BEN gets
    the machine to itself.
    """
    strain = contract[1]
    trump = {"S": 0, "H": 1, "D": 2, "C": 3, "N": 4}[strain]
    ctx = ctx_for(contract, declarer_i, dealer_i)
    dummy_i = (declarer_i + 2) % 4
    remaining = [set(h) for h in hands]
    hands = [list(h) for h in hands]          # originals, for the API params
    leader = (declarer_i + 1) % 4
    played_str = []
    lost = {"declarer": 0.0, "defence": 0.0}
    differs = 0
    cards_timed = []           # (trick_index, seconds)
    lead_info = None
    worst = []                 # (lost, detail)
    zero_playouts = 0
    pimc_rejected = 0
    playouts_seen = []
    record = []                # every card, with the position before it, to score later

    for trick in range(13):
        current = []
        trick_leader = leader
        for step in range(4):
            to_play = (trick_leader + step) % 4
            # The position is REMEMBERED here and solved after the board, so the solver
            # never competes with BEN for a core.
            snapshot = ([sorted(r) for r in remaining], trick_leader, list(current))

            if trick == 0 and step == 0:
                params = dict(hand=hand_pbn(remaining[to_play]), seat=SEATS[to_play],
                              dealer=SEATS[dealer_i], vul="", ctx=ctx, details="true")
                resp, dt = ben.get("/lead", params)
            else:
                # BEN wants the ORIGINAL hands and works out what is left from `played`.
                # Sending the remaining cards gets "Dummy should have 13 cards" the moment
                # dummy has played one.
                api_seat = declarer_i if to_play == dummy_i else to_play
                params = dict(hand=hand_pbn(hands[api_seat]),
                              dummy=hand_pbn(hands[dummy_i]),
                              seat=SEATS[api_seat], dealer=SEATS[dealer_i], vul="",
                              ctx=ctx, played="".join(played_str), details="true")
                resp, dt = ben.get("/play", params)

            raw = resp.get("card")
            if not raw:
                return {"error": "no card: " + json.dumps(resp)[:200], "trick": trick}
            code = card_code(raw)
            if code not in remaining[to_play]:
                return {"error": "card %s not in %s's hand" % (raw, SEATS[to_play]), "trick": trick}

            record.append({
                "snapshot": snapshot, "code": code, "raw": raw,
                "trick": trick, "seat": to_play, "lead": (trick == 0 and step == 0),
                "hand": hand_pbn(remaining[to_play]),
                "who": resp.get("who"),
                "candidates": (resp.get("candidates") or [])[:5],
                "seconds": dt,
            })

            msg = json.dumps(resp)
            if "SET REJECTED" in msg:
                pimc_rejected += 1
            # PIMC writes "<combinations> - <examined> - <playouts>" into each candidate's
            # msg. Reading the playouts back is the only way to see whether PIMC got the
            # time the config gives it, or was starved by something else on the cores.
            for c in (resp.get("candidates") or []):
                m = re.search(r"(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", str(c.get("msg") or ""))
                if m:
                    n = int(m.group(3))
                    playouts_seen.append(n)
                    if n == 0:
                        zero_playouts += 1
                    break

            cards_timed.append((trick, dt))
            remaining[to_play].discard(code)
            current.append(code)
            played_str.append(raw)

        # who won the trick
        lead_suit = current[0] // 13
        bestpos, bestrank = 0, -1
        for i, c in enumerate(current):
            s, r = c // 13, 14 - (c % 13)
            if trump != 4 and s == trump:
                rr = r + 100
            elif s == lead_suit:
                rr = r
            else:
                rr = -1
            if rr > bestrank:
                bestrank, bestpos = rr, i
        leader = (trick_leader + bestpos) % 4

    # ---- SECOND PASS: now that BEN is idle, score what was played ----
    lead_info = None
    for r in record:
        hands_now, trick_leader, current = r["snapshot"]
        values = dd.card_values(hands_now, trump, trick_leader, current)
        best = max(values.values()) if values else 0
        got = values.get(r["code"], best)
        delta = best - got
        bestcards = [card_str(c) for c, v in values.items() if v == best]
        if delta > 0:
            differs += 1
            side = "declarer" if r["seat"] in (declarer_i, dummy_i) else "defence"
            lost[side] += delta
            worst.append((delta, {
                "trick": r["trick"] + 1, "seat": SEATS[r["seat"]], "played": r["raw"],
                "better": bestcards[:4], "lost": delta, "hand": r["hand"],
                "who": r["who"], "candidates": r["candidates"][:4],
            }))
        if r["lead"]:
            lead_info = {"card": r["raw"], "lost": delta, "who": r["who"],
                         "hand": r["hand"], "candidates": r["candidates"],
                         "best": bestcards[:4], "contract": contract,
                         "trump": strain, "seconds": r["seconds"]}

    worst.sort(key=lambda x: -x[0])
    return {"lost": lost, "differs": differs, "cards": cards_timed, "lead": lead_info,
            "worst": [w[1] for w in worst[:6]],
            "zero_playouts": zero_playouts, "pimc_rejected": pimc_rejected,
            "playouts": playouts_seen}


# ---------------------------------------------------------------- scoring self-test

def self_test():
    """
    Check the SCORER before trusting it, on positions worked out by hand.

    If this is wrong everything downstream is wrong in a way that looks plausible, so it
    is checked against deals whose double-dummy answer is obvious to a human.
    """
    dd = DD()
    ok = True

    def check(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(("  ok   " if good else "  FAIL ") + name + "  got %s want %s" % (got, want))

    # 1. North has every ace-king-queen; East on lead in notrump takes nothing.
    hands = [[card_code(s + r) for s in "SHDC" for r in "AKQ"],
             [card_code(s + r) for s in "SHDC" for r in "T98"],
             [card_code(s + r) for s in "SHDC" for r in "765"],
             [card_code(s + r) for s in "SHDC" for r in "432"]]
    hands = [sorted(h)[:13] for h in hands]
    v = dd.card_values(hands, 4, 1, [])
    check("top hand: every East lead is worth 0 tricks to East", set(v.values()), {0})

    # 2. The same deal with East on lead in SPADES: still nothing.
    v = dd.card_values(hands, 0, 1, [])
    check("top hand in spades: still 0 for East", set(v.values()), {0})

    # 3. A position where one card matters: South must cash the setting trick.
    #    South: SA, nothing else useful. North on lead would be different.
    hands2 = [sorted([card_code(x) for x in ("S2", "H2", "D2")]),
              sorted([card_code(x) for x in ("S3", "H3", "D3")]),
              sorted([card_code(x) for x in ("SA", "H4", "D4")]),
              sorted([card_code(x) for x in ("S4", "H5", "D5")])]
    v = dd.card_values(hands2, 4, 2, [])   # South on lead, notrump
    best = max(v.values())
    check("South leading SA from a 3-card ending wins exactly 1", best, 1)
    check("  and the ace is one of the best cards", v[card_code("SA")], 1)

    # 3b. THE CHECK THAT ACTUALLY VALIDATES THE SCORER, on a random full deal.
    #
    # For every legal card: play it, re-solve the resulting position, and confirm the
    # value the scorer gave the card equals what the side really achieves afterwards.
    # Tricks already won by that side are added back, since the re-solve only counts
    # tricks still to come. If this holds for every card the scorer is sound - a hand
    # worked out by eye only ever checks one position, and gets it wrong (an earlier
    # version of this test asserted a heart was worth less than the ace here; it is not).
    import random as _r
    rng = _r.Random(99)
    bad = 0
    for _ in range(3):
        deck = list(range(52)); rng.shuffle(deck)
        h = [sorted(deck[i*13:(i+1)*13]) for i in range(4)]
        for trump in (4, 0):
            leader = 0
            vals = dd.card_values(h, trump, leader, [])
            for c, want in vals.items():
                rest = [sorted(set(x)) for x in h]
                rest[leader].remove(c)
                # after one card the next player is on play, same trick
                after = dd.card_values(rest, trump, leader, [c])
                # the leader's side gets at most (13 - what the opponents can take)
                opp_best = max(after.values()) if after else 0
                got = 13 - opp_best
                if got != want:
                    bad += 1
    check("every card's value matches a re-solve after playing it (78 cards)", bad, 0)

    # 4. equals expansion: in a suit where two cards are touching, both must be scored.
    hands3 = [sorted([card_code(x) for x in ("SK", "SQ", "H2")]),
              sorted([card_code(x) for x in ("S2", "S3", "H3")]),
              sorted([card_code(x) for x in ("SA", "S4", "H4")]),
              sorted([card_code(x) for x in ("S5", "S6", "H5")])]
    v = dd.card_values(hands3, 4, 0, [])   # North on lead
    check("touching honours are both scored (SK and SQ present)",
          card_code("SK") in v and card_code("SQ") in v, True)

    print("\n%s: scoring self-test" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deals", type=int, default=10)
    ap.add_argument("--base", default="http://127.0.0.1:8085")
    ap.add_argument("--out", default=None)
    ap.add_argument("--label", default="deployed")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--seed", type=int, default=20261005)
    a = ap.parse_args()

    if a.self_test:
        return self_test()

    dd = DD()
    ben = Ben(a.base)
    deals = make_deals(a.deals, a.seed)

    boards, errors = [], []
    t0 = time.time()
    for i, hands in enumerate(deals):
        chosen = dd.best_contract(hands)
        if not chosen:
            errors.append({"deal": i, "error": "no makeable contract"})
            continue
        contract, declarer_i = chosen
        try:
            r = play_board(ben, dd, hands, contract, declarer_i, 0)
        except Exception as ex:
            r = {"error": "%s: %s" % (type(ex).__name__, str(ex)[:200])}
        r["deal"] = i
        r["contract"] = contract + SEATS[declarer_i]
        if r.get("error"):
            errors.append(r)
        else:
            boards.append(r)
        done = i + 1
        print("  deal %d/%d  %s  lost D %.1f / d %.1f  (%.0f s elapsed)" % (
            done, len(deals), r["contract"],
            r.get("lost", {}).get("declarer", 0), r.get("lost", {}).get("defence", 0),
            time.time() - t0), flush=True)

    out = {"label": a.label, "deals": a.deals, "seconds": time.time() - t0,
           "boards": boards, "errors": errors,
           "ben_calls": ben.calls, "ben_seconds": ben.time}
    if a.out:
        with open(a.out, "w") as f:
            json.dump(out, f)
    print("\n%s: %d boards, %d errors, %.0f s, %d BEN calls" % (
        a.label, len(boards), len(errors), out["seconds"], ben.calls))
    return 0


if __name__ == "__main__":
    sys.exit(main())
