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
