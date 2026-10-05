# Benchmarking BEN's card play — what runs here, and what does not

2026-10-05, branch `bench/card-play-quality`.

## Item 2 — this machine against the deployed stack

macOS 26.0, Darwin arm64. **Verdict: BEN can almost run here, but not quite — the double-dummy
solver will not load, and that is exactly what the benchmark measures against.**

| Requirement | Status | Detail |
|---|---|---|
| Python 3.12 | **installed** | No Homebrew, no admin. Installed a standalone CPython 3.12.15 (python-build-standalone) into the scratchpad — no admin needed. |
| TensorFlow 2.18.1 + Keras 3.5.0 | **installed** | arm64 wheels, `pip install` into a 3.12 venv. The models load in 0.3 s. |
| .NET | **not needed** | The brief assumed .NET for PIMC and BBA. It is no longer required: both ship as native ctypes libraries. |
| PIMC (BGADLL) | **loads** | `bin/BGA/macos/arm64/BGADLL.dylib` — `ctypes.CDLL` succeeds, `is_available()` true. |
| BBA (EPBot) | **loads** | `bin/BBA/macos/arm64/libEPBot.dylib` — loads. |
| **DDS (`dds3`)** | **CANNOT LOAD** | `bin/dds3-darwin/dds3/_dds3.so` is arm64 Mach-O and present, but `dlopen` fails: `Symbol not found: __ZNSt3__113__hash_memoryEPKvm`. |
| Docker | **not available** | Would have sidestepped all of the above. |

### Why the solver will not load, precisely

`__ZNSt3__113__hash_memoryEPKvm` is `std::__1::__hash_memory`, a **libc++ ABI symbol**. The shipped
`_dds3.so` was built against a newer libc++ than this machine's `/usr/lib/libc++.1.dylib` exports.
It is **not** a Python-version problem — it fails identically under 3.9 and 3.12, and the error is
from `dlopen`, before Python ever looks at the module. No newer libc++ is present (no Xcode, no
Command Line Tools copy), and the system one cannot be replaced.

**What would fix it:** rebuild DDS from source for this machine (`bazel build -c opt
//python:dds3_wheel_dist` in the DDS repository), or run the benchmark on Linux — the Render
container, or any Linux box, where `bin/dds3-linux` is the build that is actually deployed.

## Items 3, 5, 6, 7 — not run

Every one of these compares BEN's card against double dummy, and ranks settings by tricks given
away. Without a solver there is no yardstick, and BEN cannot even choose a card:
`get_cards_dd_evaluation` is on the main play path. **No numbers are reported for them, because
none were produced.** Running them needs a Linux host; nothing about the design is blocked, only
this machine.

## Item 4 — how the opening lead is chosen

This is read from the code and needs no solver, so it is answered in full.

In plain words, in order:

1. **The lead network proposes.** `get_opening_lead_candidates` runs `lead_nt_model` or
   `lead_suit_model` depending on the strain, which gives a probability for every card. Cards not
   in hand are removed and the rest rescaled.
2. **A shortlist is cut.** Everything scoring above `lead_threshold` is kept, and at least
   `min_opening_leads` cards are kept whatever their score.
3. **If the network is nearly certain, that is the lead.** If the top card's score is above
   `lead_accept_nn`, it is played and no simulation happens at all. `who` reads `NN - best`.
4. **Otherwise BEN simulates.** `sample_boards_for_auction_opening_lead` deals are dealt and
   filtered against the auction; up to `sample_hands_opening_lead` of the survivors are kept.
   **Double dummy then solves all of them once for every shortlisted lead** — which is why the
   opening lead is the most expensive decision BEN makes.
5. **If the samples are poor, the network wins anyway.** With `use_biddingquality_in_eval` set and
   a negative quality, the top network card is taken. `who` reads `NN - bad quality samples`.
6. **Otherwise the simulation decides**, by expected IMPs or matchpoints when
   `use_real_imp_or_mp_opening_lead` is set, else by expected tricks or chance of defeating the
   contract. `who` reads `Simulation (IMP)` and so on.
7. **Two hand-tuned adjustments are added to the simulated score**, never to the network score:
   `reward_lead_partner_suit` for leading partner's bid suit, and `trump_lead_penalty` against
   leading trumps — a four-number penalty, the larger middle value being for leading from a bare
   queen of trumps.

### Every setting that weighs the net against double dummy

| Setting | Ours | Upstream | What it does |
|---|---|---|---|
| `lead_accept_nn` | 0.999 | 0.999 | Above this the net wins outright and no solving happens |
| `lead_threshold` | 0.20 | 0.20 | Minimum net score to be simulated at all |
| `min_opening_leads` | 4 | 4 | Cards always simulated, however low the net rates them |
| `use_biddingquality_in_eval` | True | True | Poor samples hand the decision back to the net |
| `use_real_imp_or_mp_opening_lead` | True | True | Score by IMPs/matchpoints rather than tricks |
| `double_dummy` | True | True | Double dummy rather than the single-dummy estimator |
| `sample_hands_opening_lead` | 200 | 200 | Layouts solved **per candidate lead** |
| `sample_boards_for_auction_opening_lead` | 20000 | 20000 | Deals dealt before filtering |
| `reward_lead_partner_suit` | 0.5 | 0.5 | Added to partner's suit |
| `trump_lead_penalty` | [0.2, 0.2, 0.5, 0.2] | same | Subtracted from trump leads |

**Every one of these is identical to upstream.** Nothing was changed in this branch.

### The fault item 4 asks to look for

The brief names it exactly: a lead that is only safe because declarer can see all four hands.
Step 6 ranks leads by a **double-dummy** average, and double dummy never misguesses — so a lead
that works only because declarer would misplay, or that gives nothing away only because the solver
knows where every card is, scores better than it deserves. Steps 3 and 5 are the two places the
network overrides that, and `reward_lead_partner_suit` / `trump_lead_penalty` are hand-tuned
corrections bolted on afterwards for the same reason. **Measuring how often this bites is
precisely item 4's unrun half**, and it needs the solver.

---

# Update, 2026-10-05 — the solver is built; the benchmark is not run

Branch `bench/card-play-harness`.

## Item 1 — the solver, built from source ✅

`xcode-select --install` reported **Command Line Tools are already installed**, so there was no
popup to click. Apple clang 17 compiles and links C++ fine.

Bazel is **not** needed. The DDS repository builds its Python interface with bazel, but that
interface is pybind11 over two source files, so clang++ compiles it directly against the 40
library sources. `scripts/build-dds3-macos.sh` does exactly that, in about 40 seconds, and runs
its own self-test. It writes **outside the repository** and leaves `bin/dds3-linux` — the build the
service deploys — untouched.

Two things the bazel build supplies that the script has to reproduce by hand: `<dds/dds.hpp>` is
included with a prefix bazel adds via `include_prefix`, so the script stages a `dds/` symlink; and
the sources live in nine subdirectories under `library/src`, not just the top one.

Verified: `par NS 990` and 0 tricks to East against AKQ in every suit — both correct.

## Item 2 — partly proven

**The opening lead works, twice.** With the deployed settings and the built solver:

```text
hand K93.AKT3.643.KJ5, contract 2D  ->  D3   who=Simulation (IMP)  1.21 s
3NT by North, East on lead          ->  CK   who=Simulation (IMP)  1.27 s
```

The first of those **reproduces the live `[ben-why]` line exactly** — same hand, same contract,
same card, same rule. That is the strongest evidence available that this local setup matches the
deployed one.

Everything loads: `BBA 8740`, `SuitC 0.9.0.9`, `PIMC 0.9.9.1`, `PIMCDef 0.9.9.1`,
`DDSolver 3.0.0 Max threads 2`. **No .NET is required** — PIMC and BBA are native ctypes
libraries now. PIMC's own bundled DDS needs
`DYLD_LIBRARY_PATH=<repo>/bin/BGA/macos/arm64` and a `libdds.dylib` name it will find.

**A card in the play is not yet proven.** Calling `play_api` directly raised
`'NoneType' object has no attribute 'set_hcp_constraints'` — the per-seat PIMC objects are set up
by the `/play` route's own preamble, which a direct call skips. This is a fault in how I drove it,
not a missing dependency: every component the card path needs is loaded. Starting `gameapi.py` and
asking `/play` over HTTP is what settles it, and that is the next step.

## Items 3–7 — NOT RUN

No numbers are reported, and none are invented. These need item 2 finished first, and then a
self-play harness driving four robots through 52 cards, scoring every card against double dummy,
across six settings and 100 deals — roughly 31,000 card decisions. At the ~1.2 s per decision
measured above for a lead, that is hours of compute, beyond what this session had left after
building the solver.

What now exists that did not before: **a working solver on this machine**, a reproducible script
to rebuild it, and a verified local setup that reproduces a live decision card-for-card. The
benchmark is now a matter of running it rather than of whether it can run at all.

---

# Update 2 — the harness runs; the service dies after two or three boards

Branch `bench/card-play-harness`.

## What now works

- `/play` returns a card over HTTP with the built solver and the deployed settings,
  `who=PIMC-BEN-IMP`, so PIMC is genuinely in the decision.
- The harness plays a full board — 52 cards, every one scored against double dummy — in
  about 78 seconds, and its scorer is validated by re-solving every card (78 cards, exact).
- The six settings are generated as copies of `default_api.conf`; the repository's own
  config is never touched.

## The blocker

**The service dies silently after two or three boards.** Both settings that got as far as
playing ended identically: the log stops in the middle of a `/play` request with **no
traceback, no `Fatal Python error`, nothing**. The benchmark then gets
`Connection refused` for every remaining board — 2 boards scored, 8 errors.

A silent death with no Python-level message is a **native crash**: something in
`BGADLL.dylib` (PIMC) or the solver aborts the process without Python seeing it. The
evidence that it is PIMC rather than the harness:

- a single board played by hand earlier completed all 52 cards, so it is not the first
  card or the setup that is wrong;
- the last request before each death is an ordinary `/play` mid-trick;
- `[ben-slow]` shows one card at 11.5 s with `worst=pimc` shortly before the deployed
  service stopped.

**This is a macOS-only finding until shown otherwise.** The deployed service runs Linux
with a different BGADLL build, and nothing here says that one crashes. It does mean the
benchmark cannot be completed on this machine until the crash is pinned down.

## What would move it forward

1. Run the harness against `pimc-off` first. If that setting survives 10 boards while
   the PIMC ones do not, the crash is PIMC's and the point is proved cheaply.
2. Catch the native fault: run the service under `lldb`, or check
   `~/Library/Logs/DiagnosticReports` for a crash report naming `BGADLL.dylib`.
3. Or run the whole benchmark on Linux, where `bin/dds3-linux` and the Linux BGADLL are
   the builds that actually deploy — which was the original recommendation and remains
   the fastest route to the numbers.

No results are reported. Two boards from one setting is not a sample, and the settings
cannot be compared on it.

---

# Update, 2026-10-05 (second session) — the runs, and three infrastructure faults

## Item 1 — the previous run did not finish

`out/` from the previous session held only `api-deployed.log`. **No results JSON at all**:
the run was killed when that session ended, before a single setting completed. Nothing from it
could be reported, so it was rerun.

## Three faults in getting a run started, all of them mine, all now fixed

1. **`pkill -f "gameapi.py"` killed my own shell.** The pattern matches any process whose command
   line *contains* that string — including the shell that was about to launch the run, because the
   launch command mentioned it. Exit 144 (SIGTERM), and `/tmp/bench10` was never created. Stale
   processes must be killed **by PID**, found with `ps | grep '[g]ameapi'`.
2. **Two services from the previous session were still holding port 8085**, so the first relaunch
   talked to a service running the *old* configuration. This is the same contamination the previous
   session hit, surviving across sessions.
3. **The service dies silently under `bench_run_all.sh`'s launch but not under a plain one.**
   With `--config <copy>.conf` it served 15 cards and vanished — no traceback, no `Fatal Python
   error`, just gone, which reaches the harness as `RemoteDisconnected` and then
   `Connection refused`. Started the same way but *without* `--config`, the identical deals play
   fine. **This is unexplained and is the thing to fix before the full run can be trusted**: either
   the config copy differs in some way that matters, or passing `--config` takes a path that
   crashes natively.

## What the deployed setting looks like so far

Two boards, which is not a result:

```text
deal 1/10  5NN  declarer gave away 1.0, defence 1.0   (85 s)
deal 2/10  5CE  declarer gave away 0.0, defence 0.0   (39 s)
```

Timing, from the service's own `[ben-time]` lines: trick-one cards cost 5–8 s and later cards
0.6 s. The early cost is real and is what the warm-up and the first-card work were about. Note
`playouts=10` on some early cards against a configured 100 — PIMC is being starved of its one
second while the harness's own DDS competes for the same two cores, so **quality measured this way
is not quality on an idle box**. The harness should record cards as played and score them in a
second pass; that change is not made yet.

## Not reported

Items 2–5 of this brief: there is no six-setting comparison, and two boards of one setting cannot
support one. **No numbers are given for tricks lost per setting, PIMC rejection rates, lead
quality or worst cards**, because they were not measured.

---

# The deployed setting, 10 deals — first real result (2026-10-05)

`deployed: 10 boards, 0 errors, 676 s, 520 BEN calls`. Contracts fixed in advance from the
double-dummy table; robots in all four seats; every card scored against DDS.

## Tricks given away

| | per board | boards affected |
|---|---|---|
| as declarer | **1.20** | 7 of 10 |
| in defence | **0.70** | 6 of 10 |

Only **15 of 520 cards** were not a double-dummy best card — 2.9%. The damage is concentrated:
one board (deal 5, 6NT) accounts for 5 of the 12 declarer tricks on its own.

| deal | contract | decl | def | bad cards | lead | lead rule |
|---|---|---|---|---|---|---|
| 0 | 5NN | 1 | 1 | 2 | CQ | NN - bad quality samples |
| 1 | 5CE | 0 | 0 | 0 | SA | Simulation (IMP) |
| 2 | 5HN | 1 | 1 | 2 | D9 | NN - bad quality samples |
| 3 | 4SE | 0 | 1 | 1 | CA | Simulation (IMP) |
| 4 | 2HN | 1 | 2 | 3 | SK | Simulation (IMP) |
| 5 | 6NN | **5** | 0 | 2 | CQ | NN - bad quality samples |
| 6 | 6HE | 1 | 0 | 1 | DK | Simulation (IMP) |
| 7 | 3NW | 1 | 1 | 2 | C9 | Simulation (IMP) |
| 8 | 5NN | 2 | 1 | 2 | S9 | NN - bad quality samples |
| 9 | 4CE | 0 | 0 | 0 | DK | Simulation (IMP) |

## Opening leads

**Every one of the ten leads was a double-dummy best card — 0.00 tricks lost.** No trump honours
were led. Two were unsupported honours (CQ without the jack, twice — both on boards where the
lead rule was `NN - bad quality samples`), and two were cards the lead net itself scored below
`lead_threshold` (0.20). Neither cost anything here.

Worth noting for the bigger run: **4 of 10 leads were chosen by `NN - bad quality samples`**, the
path that abandons the simulation because the sampler could not find layouts consistent with the
auction. That is the benchmark's own doing — the auction is fabricated (`5N-P-P-P`), so it carries
no information and the sampler has little to work from. On real auctions that path should be rarer.

## PIMC was starved, and by how much

Measured from the service's own `[ben-time]` lines across all 416 calculated cards:

```text
playouts: min 0   median 100   mean 69   max 100   (configured 100)
   reached 100:  266 of 416  (64%)
   reached  50:  282 of 416  (68%)
   zero playouts: 30 of 416  (7%)
```

So **PIMC completed its full 100 playouts on only 64% of cards**, and on 30 cards it completed
none at all — which is exactly the 30 the harness counted as PIMC-set-rejected, since a decision
with no playouts has no usable PIMC values. Mean 69 of 100 is a 31% shortfall.

The cause was the harness solving a DDS position for every card **while BEN was thinking**, on the
same two cores the service is configured to use. Fixed: the board is now played first and scored
afterwards (see the commit "Score the cards after the board, not while BEN is thinking").

Time per calculated card: median 0.5 s, **max 73.7 s**. The maximum is worth remembering when
setting the site's 20 s first-attempt budget.

## Item 4 — the `--config` crash: the diagnosis was wrong

The previous session concluded the service "dies silently with `--config <copy>.conf` but not with
a plain launch". **That is not what is happening.** Compared line by line:

- **The config copy is byte-for-byte identical** to `src/config/default_api.conf` (`diff` is empty).
  It cannot be the cause of anything.
- Both launches load the solver: `PIMC enabled. Version 0.9.9.1 DDS: haglund`, zero
  "Unable to load shared library" lines in either.
- The `bench_run_all.sh`-style launch gives the service the right environment, checked from the
  running process: `cwd=.../src`, `DYLD_LIBRARY_PATH=.../bin/BGA/macos/arm64`, `PYTHONPATH`
  pointing at the built `dds3`, `BEN_HOME` correct, and `Loading config file /tmp/.../stop8.conf`.

**What the crash actually was.** `~/Library/Logs/DiagnosticReports` holds three reports, all at
21:29:05, all the same shape: `SIGABRT`, and the faulting thread is inside **`BGADLL.dylib`** —
PIMC's own native library — calling `abort()`. Not Python, not the config, not the loader. BGADLL
is a .NET Native AOT library and aborts the whole process on an unhandled exception.

**And it is intermittent, not deterministic.** Since those 21:29 reports there has been **no new
crash report at all**, while the service has served **625 cards** — 520 for the completed deployed
run (plain launch) and 105+ for a `stop8` run started exactly the `bench_run_all.sh` way, both
still healthy. 15 cards before a crash in one run and 625 without one in the next is a flaky
native fault, not a property of how the service is started.

So there is nothing to "fix" in the launch; the earlier conclusion was a coincidence read as a
cause. What a long run needs instead is **tolerance**: `bench_run_all.sh` should notice a dead
service, restart it, and retry or skip the board, rather than turning one abort into ten failed
boards. That change is not made yet.
