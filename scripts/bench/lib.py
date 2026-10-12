"""
Shared helpers for the real-auction card-play benchmark (scripts/bench/README.md).

Measuring only. It talks HTTP to BEN services started by svc.py, asks them exactly what the
website asks, and scores every card against double dummy afterwards. Nothing in here touches
the engine.

From the measurement of 2026-10-10, where it lived in a temporary folder; moved here on
2026-10-12 with the hard-coded paths and the two fixed service names taken out.

    BENCH_WORK     where services, logs and raw results go (default: scripts/bench/work, untracked)
    BENCH_PYTHON   the interpreter that runs BEN (the virtual environment's python)
    DDS3PKG        the folder holding the dds3 package built for this machine
"""
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("BENCH_WORK") or os.path.join(HERE, "work")
SVC = os.path.join(WORK, "services")
sys.path.insert(0, os.path.dirname(HERE))                # scripts/, for bench_card_play
if os.environ.get("DDS3PKG"):
    sys.path.insert(0, os.environ["DDS3PKG"])
import bench_card_play as H

SEATS = "NESW"


class _Services(dict):
    """name -> its registry entry, read from BENCH_WORK/services/<name>.json when first asked."""
    def __init__(self, field):
        super().__init__()
        self.field = field

    def __missing__(self, name):
        with open(os.path.join(SVC, name + ".json")) as f:
            v = json.load(f)[self.field]
        self[name] = v
        return v


BASE = _Services("url")
LOG = _Services("log")
VULS = ["None", "NS", "EW", "Both", "NS", "EW", "Both", "None", "EW", "Both", "None", "NS", "Both", "None", "NS", "EW"]
STRAINS = "SHDCN"


def board_info(deal_i):
    """deal index 0.. -> standard board number 1.., dealer, vulnerability (16-board cycle)."""
    n = deal_i + 1
    return n, SEATS[(n - 1) % 4], VULS[(n - 1) % 16]


DEALS = os.path.join(HERE, "data", "deals60.json")


def load_deals(path=None):
    return json.load(open(path or DEALS))


def hands_of(d):
    return [sorted(H.card_code(c) for c in d["cards"][s]) for s in SEATS]


# ------------------------------------------------------------ services

def pid_of(name):
    pid = None
    try:
        for line in open(os.path.join(SVC, "pids")):
            p = line.split()
            if len(p) == 2 and p[0] == name:
                pid = int(p[1])
    except FileNotFoundError:
        pass
    return pid


def alive(name):
    pid = pid_of(name)
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def probe(name, timeout=120):
    try:
        st, js, dt, _ = call(name, "/lead", dict(hand="AK32.T98.765.432", seat="E", dealer="N", vul="",
                                                 ctx="1N-P-3N-P-P-P", details="false"), timeout=timeout, logs=False)
        return st == 200 and bool(js.get("card"))
    except Exception:
        return False


def restart(name):
    """Start OUR service again (only ever our own pid). Returns seconds until a real /lead answered."""
    t0 = time.time()
    pid = pid_of(name)
    try:
        os.kill(pid, 9)
    except Exception:
        pass
    time.sleep(1)
    out = open(LOG[name], "a")
    out.write("\n[measure] RESTART %s at %s\n" % (name, time.strftime("%H:%M:%S")))
    out.flush()
    p = subprocess.Popen([os.path.join(SVC, "run_%s.sh" % name)], stdout=out, stderr=subprocess.STDOUT,
                         start_new_session=True)
    with open(os.path.join(SVC, "pids"), "a") as f:
        f.write("%s %d\n" % (name, p.pid))
    while time.time() - t0 < 300:
        time.sleep(1)
        if probe(name, timeout=30):
            return time.time() - t0
    raise RuntimeError("service %s did not come back" % name)


CRASHES = []

# BEN LIMITS ITS OWN CALLERS: 100 requests a minute on every route but /play, counted per
# address (gameapi.py, flask-limiter's default_limits; --nolimit is parsed and never used).
# A bid costs about a tenth of a second here, so an auction-only run goes straight through
# it and every answer after the hundredth is "Rate limit exceeded". The engine is not ours
# to change, so the benchmark keeps under the limit instead: at most one request every
# 0.75 s to those routes, per service. /play is exempt for a local caller and is not paced.
PACED_SECONDS = 0.75
_last_paced = {}


def _pace(name, path):
    if path == "/play":
        return
    key = (name, path)
    wait = PACED_SECONDS - (time.time() - _last_paced.get(key, 0))
    if wait > 0:
        time.sleep(wait)
    _last_paced[key] = time.time()


def call(name, path, params, timeout=300, logs=True):
    """One GET. Returns (http_status, json_or_{}, seconds, [ben-* log lines printed during it])."""
    url = BASE[name] + path + "?" + urllib.parse.urlencode(params)
    _pace(name, path)
    off = os.path.getsize(LOG[name]) if logs else 0
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode("utf-8")
            st = r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        st = e.code
    dt = time.time() - t0
    try:
        js = json.loads(body)
    except Exception:
        js = {"raw": body[:300]}
    lines = []
    if logs:
        time.sleep(0.005)
        with open(LOG[name], "rb") as f:
            f.seek(off)
            for ln in f.read().decode("utf-8", "replace").splitlines():
                if ln.startswith("[ben-") or ln.startswith("[robot-"):
                    lines.append(ln[:1500])
    return st, js, dt, lines


def safe_call(name, path, params, timeout=300, what=""):
    """call(), but a dead service is restarted and the question retried ONCE; every crash is recorded."""
    for attempt in (0, 1):
        try:
            return call(name, path, params, timeout=timeout)
        except Exception as ex:
            dead = not alive(name)
            CRASHES.append({"service": name, "path": path, "what": what, "error": "%s: %s" % (type(ex).__name__, str(ex)[:200]),
                            "process_dead": dead, "attempt": attempt, "at": time.strftime("%H:%M:%S"), "params": params})
            with open(os.path.join(WORK, "crashes.jsonl"), "a") as f:   # every crash, all runs
                f.write(json.dumps(CRASHES[-1]) + "\n")
            if attempt == 1:
                raise
            if dead or not probe(name, timeout=20):
                restart(name)
    raise RuntimeError("unreachable")


# ------------------------------------------------------------ auction

def norm_call(raw):
    r = str(raw or "").strip().upper()
    if r in ("PASS", "P", "--", "PA"):
        return "P"
    if r in ("X", "DB", "DOUBLE"):
        return "X"
    if r in ("XX", "RD", "REDOUBLE"):
        return "XX"
    if len(r) >= 2 and r[0] in "1234567" and r[1:] in ("C", "D", "H", "S", "N", "NT"):
        return r[0] + r[1]
    return None


class Auction:
    def __init__(self, dealer):
        self.dealer_i = SEATS.index(dealer)
        self.calls = []

    def turn(self):
        return (self.dealer_i + len(self.calls)) % 4

    def ctx(self):
        return "-".join(self.calls)

    def over(self):
        c = self.calls
        if len(c) == 4 and all(x == "P" for x in c):
            return True
        return len(c) >= 4 and c[-3:] == ["P", "P", "P"] and any(x not in ("P",) for x in c)

    def last_bid(self):
        for i in range(len(self.calls) - 1, -1, -1):
            if self.calls[i][0] in "1234567":
                return i
        return None

    def legal(self, call):
        if call == "P":
            return True
        lb = self.last_bid()
        if call[0] in "1234567":
            if lb is None:
                return True
            a, b = self.calls[lb], call
            return (int(b[0]), "CDHSN".index(b[1])) > (int(a[0]), "CDHSN".index(a[1]))
        if lb is None:
            return False
        after = self.calls[lb + 1:]
        bidder_side = (self.dealer_i + lb) % 2
        me_side = self.turn() % 2
        if call == "X":
            return me_side != bidder_side and all(x == "P" for x in after)
        if call == "XX":
            if "X" not in after or "XX" in after:
                return False
            xi = lb + 1 + after.index("X")
            return me_side == bidder_side and all(x == "P" for x in self.calls[xi + 1:])
        return False

    def contract(self):
        """None if passed out, else dict(level, strain, doubled 0/1/2, declarer_i, text)."""
        lb = self.last_bid()
        if lb is None:
            return None
        bid = self.calls[lb]
        after = self.calls[lb + 1:]
        dbl = 2 if "XX" in after else (1 if "X" in after else 0)
        side = (self.dealer_i + lb) % 2
        decl = None
        for i, c in enumerate(self.calls):
            if c[0] in "1234567" and c[1] == bid[1] and (self.dealer_i + i) % 2 == side:
                decl = (self.dealer_i + i) % 4
                break
        return {"level": int(bid[0]), "strain": bid[1], "doubled": dbl, "declarer_i": decl,
                "text": bid + ("X" * dbl) + SEATS[decl]}


def score(level, strain, doubled, vul, tricks):
    """Duplicate score for the DECLARING side."""
    need = level + 6
    if tricks < need:
        d = need - tricks
        if not doubled:
            return -(100 if vul else 50) * d
        if vul:
            s = 200 + 300 * (d - 1)
        else:
            s = 100 + 200 * (min(d, 3) - 1) + 300 * max(0, d - 3)
            if d == 1:
                s = 100
        return -s * (2 if doubled == 2 else 1)
    per = 20 if strain in "CD" else 30
    base = per * level + (10 if strain == "N" else 0)
    base *= (1, 2, 4)[doubled]
    s = base
    s += (500 if vul else 300) if base >= 100 else 50
    if level == 6:
        s += 750 if vul else 500
    if level == 7:
        s += 1500 if vul else 1000
    over = tricks - need
    if doubled == 0:
        s += over * per
    else:
        s += over * (200 if vul else 100) * (2 if doubled == 2 else 1)
        s += 50 * doubled
    return s


IMP_TABLE = [20, 50, 90, 130, 170, 220, 270, 320, 370, 430, 500, 600, 750, 900, 1100, 1300, 1500, 1750, 2000, 2250,
             2500, 3000, 3500, 4000]


def imps(diff):
    a = abs(diff)
    n = 0
    for t in IMP_TABLE:
        if a >= t:
            n += 1
    return n if diff >= 0 else -n


def vul_of(side_ns, vul):
    return vul == "Both" or (vul == "NS" and side_ns) or (vul == "EW" and not side_ns)


def ns_score(contract, vul, tricks):
    """Score from North-South's point of view. contract None = passed out."""
    if contract is None:
        return 0
    ns = contract["declarer_i"] % 2 == 0
    s = score(contract["level"], contract["strain"], contract["doubled"], vul_of(ns, vul), tricks)
    return s if ns else -s


_dd = None


def dd():
    global _dd
    if _dd is None:
        _dd = H.DD()
    return _dd


def dd_table(hands):
    """res_table[strain 0-4 = S H D C NT][declarer 0-3 = N E S W], and par."""
    res = dd().dds3.calc_all_tables_pbn([H.deal_pbn(hands)], mode=0)
    return res["tables"][0]["res_table"], res


def bid_request(name, hand_cards, seat_i, dealer, vul, ctx, tag, board, website=True):
    params = dict(hand=H.hand_pbn(hand_cards), seat=SEATS[seat_i], dealer=dealer,
                  vul="" if vul == "None" else vul, ctx=ctx, tournament="imps", room=tag, board=board,
                  details="false")
    return params


def run_auction(hands, dealer, vul, owner, tag, board, log=None):
    """owner: seat index -> 'fork'/'orig'. Returns dict(calls, contract, records)."""
    a = Auction(dealer)
    recs = []
    while not a.over():
        s = a.turn()
        name = owner[s]
        params = bid_request(name, hands[s], s, dealer, vul, a.ctx(), "%s-b%02d" % (tag, len(a.calls)), board)
        st, js, dt, lines = safe_call(name, "/bid", params, what="bid %s deal %s" % (tag, board))
        c = norm_call(js.get("bid"))
        rec = {"n": len(a.calls), "seat": SEATS[s], "service": name, "seconds": dt, "status": st, "answer": js.get("bid"),
               "who": js.get("who"), "params": params, "log": lines}
        if c is None or not a.legal(c):
            rec["error"] = "illegal or missing call: %s" % json.dumps(js)[:200]
            recs.append(rec)
            return {"calls": a.calls, "contract": None, "records": recs, "error": rec["error"]}
        recs.append(rec)
        a.calls.append(c)
        if len(a.calls) > 60:
            return {"calls": a.calls, "contract": None, "records": recs, "error": "auction too long"}
    return {"calls": a.calls, "ctx": a.ctx(), "contract": a.contract(), "records": recs}


# ------------------------------------------------------------ play

def legal_cards(remaining, current):
    if current:
        suit = current[0] // 13
        f = [c for c in remaining if c // 13 == suit]
        if f:
            return f
    return list(remaining)


def run_play(hands, dealer, vul_param, ctx, strain, declarer_i, owner, tag, board, tournament=None, details="true"):
    """
    Play 13 tricks. owner: seat index -> service (dummy's cards are asked of declarer's owner).
    Returns dict(records, declarer_tricks) - positions are recorded and scored afterwards by score_play().
    """
    trump = {"S": 0, "H": 1, "D": 2, "C": 3, "N": 4}[strain]
    dummy_i = (declarer_i + 2) % 4
    remaining = [set(h) for h in hands]
    orig_hands = [list(h) for h in hands]
    leader = (declarer_i + 1) % 4
    played = []
    recs = []
    decl_tricks = 0
    for trick in range(13):
        current = []
        tl = leader
        for step in range(4):
            tp = (tl + step) % 4
            snap = ([sorted(r) for r in remaining], tl, list(current))
            legal = legal_cards(remaining[tp], current)
            if trick == 0 and step == 0:
                role = "opening lead"
                name = owner[tp]
                params = dict(hand=H.hand_pbn(remaining[tp]), seat=SEATS[tp], dealer=dealer, vul=vul_param, ctx=ctx,
                              details=details, room="%s-c%02d" % (tag, len(played)), board=board)
                path = "/lead"
            else:
                api = declarer_i if tp == dummy_i else tp
                name = owner[api]
                role = ("declarer from dummy" if tp == dummy_i else "declarer from own hand" if tp == declarer_i
                        else "defender")
                params = dict(hand=H.hand_pbn(orig_hands[api]), dummy=H.hand_pbn(orig_hands[dummy_i]), seat=SEATS[api],
                              dealer=dealer, vul=vul_param, ctx=ctx, played="".join(played), details=details,
                              room="%s-c%02d" % (tag, len(played)), board=board)
                if tournament:
                    params["tournament"] = tournament
                path = "/play"
            st, js, dt, lines = safe_call(name, path, params, what="%s deal %s" % (tag, board))
            raw = js.get("card")
            rec = {"n": len(played), "kind": "lead" if path == "/lead" else "play", "seat": SEATS[tp], "role": role,
                   "service": name, "trick": trick + 1, "seconds": dt, "status": st, "answer": raw,
                   "forced": len(legal) == 1, "n_legal": len(legal), "who": js.get("who"), "quality": js.get("quality"),
                   "candidates": (js.get("candidates") or [])[:6], "snapshot": snap, "hand": H.hand_pbn(remaining[tp]),
                   "params": params, "log": lines}
            recs.append(rec)
            if not raw or H.card_code(raw) not in legal:
                rec["error"] = "no/illegal card: %s" % json.dumps(js)[:200]
                return {"records": recs, "error": rec["error"], "declarer_tricks": None}
            code = H.card_code(raw)
            remaining[tp].discard(code)
            current.append(code)
            played.append(raw)
        ls = current[0] // 13
        bp, br = 0, -1
        for i, c in enumerate(current):
            s, r = c // 13, 14 - (c % 13)
            rr = r + 100 if (trump != 4 and s == trump) else (r if s == ls else -1)
            if rr > br:
                br, bp = rr, i
        leader = (tl + bp) % 4
        if leader in (declarer_i, dummy_i):
            decl_tricks += 1
    return {"records": recs, "declarer_tricks": decl_tricks, "played": "".join(played)}


def score_play(recs, strain, declarer_i):
    """Second pass, as the harness does: score every card against double dummy. Mutates recs (dd_lost, dd_best)."""
    trump = {"S": 0, "H": 1, "D": 2, "C": 3, "N": 4}[strain]
    dummy_i = (declarer_i + 2) % 4
    lost = {"declarer": 0, "defence": 0, "lead": 0}
    for r in recs:
        if "snapshot" not in r or r.get("error"):
            continue
        hn, tl, cur = r["snapshot"]
        vals = dd().card_values(hn, trump, tl, cur)
        best = max(vals.values()) if vals else 0
        got = vals.get(H.card_code(r["answer"]), best)
        r["dd_lost"] = best - got
        r["dd_best"] = [H.card_str(c) for c, v in vals.items() if v == best]
        r["dd_values"] = {H.card_str(c): v for c, v in vals.items()}
        side = "declarer" if SEATS.index(r["seat"]) in (declarer_i, dummy_i) else "defence"
        lost[side] += r["dd_lost"]
        if r["kind"] == "lead":
            lost["lead"] += r["dd_lost"]
    return lost


def dump(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


# ------------------------------------------------------------ services: start and stop

def start(name, port, engine, conf):
    """
    Start one BEN service from an engine checkout with one settings file, and wait until it
    answers a real opening lead. The environment is the Dockerfile's: two threads inside an
    operation, one between, two for OpenMP.
    """
    py = os.environ["BENCH_PYTHON"]
    dds3 = os.environ["DDS3PKG"]
    os.makedirs(SVC, exist_ok=True)
    os.makedirs(os.path.join(WORK, "logs"), exist_ok=True)
    log = os.path.join(WORK, "logs", name + ".log")
    run = os.path.join(SVC, "run_%s.sh" % name)
    with open(run, "w") as f:
        f.write("#!/bin/bash\ncd %s/src\n" % engine)
        f.write("export BEN_HOME=%s TF_CPP_MIN_LOG_LEVEL=3 PYTHONPATH=%s DYLD_LIBRARY_PATH=%s/bin/BGA/macos/arm64\n"
                % (engine, dds3, engine))
        f.write('export TF_NUM_INTRAOP_THREADS=2 TF_NUM_INTEROP_THREADS=1 OMP_NUM_THREADS=2 CUDA_VISIBLE_DEVICES="" '
                "PYTHONUNBUFFERED=1\n")
        f.write("exec %s gameapi.py --host 127.0.0.1 --port %d --config %s\n" % (py, int(port), conf))
    os.chmod(run, 0o755)
    with open(os.path.join(SVC, name + ".json"), "w") as f:
        json.dump({"name": name, "url": "http://127.0.0.1:%d" % int(port), "log": log, "engine": engine,
                   "conf": conf, "port": int(port)}, f)
    BASE.pop(name, None)
    LOG.pop(name, None)
    open(log, "a").close()
    return restart(name)


def stop(name):
    pid = pid_of(name)
    try:
        os.kill(pid, 15)
    except Exception:
        pass


# ------------------------------------------------------------ what a card rested on

_WHY = re.compile(r"^\[ben-why\] (play|lead) ")


def why(lines):
    """From the service's own [ben-why] line for this card: path, rule, layouts (n) and fit (q)."""
    out = {}
    for ln in lines or []:
        if not _WHY.match(ln):
            continue
        head = ln.split(" :: ")[0]
        m = re.search(r" path=(\S+)", head)
        if m:
            out["path"] = m.group(1)
        m = re.search(r" rule=(.*?)(?= pimc=| n=|$)", head)
        if m:
            out["rule"] = m.group(1)
        m = re.search(r" n=(\d+)", head)
        if m:
            out["layouts"] = int(m.group(1))
        m = re.search(r" q=(-?[0-9.]+)", head)
        if m:
            out["quality"] = float(m.group(1))
    for ln in lines or []:
        if ln.startswith("[robot-time] "):
            for key in ("think_ms", "nn_ms", "solve_ms", "fresh", "deals"):
                m = re.search(r" %s=(\d+)" % key, ln)
                if m:
                    out[key] = int(m.group(1))
    return out


def slim(rec):
    """A card's record without the request, the position and the raw log - what is committed."""
    keep = ("n", "kind", "seat", "role", "service", "trick", "seconds", "status", "answer", "forced", "n_legal",
            "who", "dd_lost", "dd_best", "error")
    out = {k: rec[k] for k in keep if k in rec}
    out.update(why(rec.get("log")))
    return out


def decl_vul(contract, vul):
    return vul_of(contract["declarer_i"] % 2 == 0, vul)


def decl_score(contract, vul, tricks):
    """Duplicate score for the declaring side at the board's real vulnerability."""
    return score(contract["level"], contract["strain"], contract["doubled"], decl_vul(contract, vul), tricks)
