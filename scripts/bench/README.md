# The real-auction card-play benchmark

Compares two or more BEN setups on the same boards, the way the website uses BEN: over HTTP,
with `/bid`, `/lead` and `/play`, real dealers and vulnerabilities, and a real auction.

It came out of the measurement of 2026-10-10, which lived in a temporary folder. It was moved
here on 2026-10-12. Nothing in it changes the engine: every setup is a **copy** of the engine's
own `default_api.conf` with named keys changed, written outside the repository.

## What it measures

- **BEN bids each deal once.** The baseline bids all four seats; that auction and contract are
  then fixed for every setup (`data/deals60.json`). So what differs between setups is the card
  play alone, and the sampler has a real auction to work from - the older harness
  (`scripts/bench_card_play.py`) made one up, which tells the sampler nothing.
- **Tricks given away**, per board, against double dummy: every card is compared with the best
  card double dummy had at that position, after the board has been played.
- **IMPs against the baseline**, per board, from a two-table match: the setup declares against
  the baseline's defence at one table, and defends against the baseline's declarer play at the
  other.
- **How many cards rested on 12 layouts**, from the service's own `[ben-why]` line.
- **How many cards differ**, position by position (`shadow.py`): the second setup is asked the
  baseline's exact questions, so one early difference is not counted fifty times over.

## Set-up, three steps

No administrator rights and no Docker. Apple's Command Line Tools must be installed
(`xcode-select -p` prints a path).

1. **Python 3.12 and BEN's packages.** A standalone CPython 3.12 (python-build-standalone),
   a virtual environment made from it, then `pip install -r requirements.txt onnxruntime`.
   `onnxruntime` is only needed to run a setup on the ONNX models.
2. **The solver, built for this Mac.** `bash scripts/build-dds3-macos.sh <workdir> <that python>`
   - about 40 seconds. The `dds3` build shipped in `bin/dds3-darwin` does not load on this
   machine; `bin/dds3-linux`, which the service deploys, is not touched.
3. **Say where they are**, and check out the engine to be measured somewhere of its own:

   ```bash
   export BENCH_PYTHON=<venv>/bin/python
   export DDS3PKG=<workdir>/dds3pkg
   export BENCH_WORK=<a folder for services, logs and raw results>
   git worktree add --detach <engine dir> origin/main
   ```

On 2026-10-12 steps 1 and 2 were **not repeated**: the environment and the solver built on
2026-10-10 were still in that session's temporary folder and were used from there. A restart of
the machine may remove them; the two steps above rebuild them.

## A run

All from `scripts/bench/`, with `$BENCH_PYTHON`.

```bash
python mkconf.py A <engine> $BENCH_WORK/conf/A.conf          # the settings copy for a setup
python svc.py start A1 8201 <engine> $BENCH_WORK/conf/A.conf # one service; waits until it leads
python mkdeals.py 72 $BENCH_WORK/candidates.json             # candidate deals, fixed seed
python auctions.py A1 $BENCH_WORK/candidates.json 60         # the baseline bids; 60 kept
python play_run.py self A1 A-self                            # the baseline, all four seats
python play_run.py match B1 A2 B-vs-A                        # setup B against the baseline
python shadow.py $BENCH_WORK/raw-A-self.json B2 B-shadow     # B asked A's own questions
python summary.py                                            # results/summary.md
python svc.py stop A1 A2 B1 B2
```

A service answers one question at a time and its log is read by position, so **each service
serves one run**: a second run that needs the baseline gets a second baseline service.

## Things that will catch you out

- **BEN limits its callers to 100 requests a minute** on every route except `/play`
  (flask-limiter's `default_limits` in `gameapi.py`; the `--nolimit` flag is parsed and never
  used). A bid costs a tenth of a second here, so bidding 72 deals ran straight into it and
  every answer after the hundredth was `Rate limit exceeded`. `lib.py` keeps those routes to
  one request every 0.75 s per service.
- **Speed measured here is not Render's.** This machine has many fast cores; the service has
  two shared ones. Which cards are chosen carries over; how long they take does not.
- **With PIMC off no decision depends on the clock**, which is what makes it safe to run
  several services side by side. Any setting that gives a card a time budget breaks that.
- **Stop services by name** (`svc.py stop`), never with a pattern: `pkill -f gameapi.py`
  matches the shell that typed it.

## Files

```text
lib.py        services, the auction and play loops, double-dummy scoring, IMPs
svc.py        start / stop one service
mkconf.py     the settings copy for a setup (A, B, C, D)
mkdeals.py    candidate deals
auctions.py   the baseline bids each deal once -> data/deals60.json
play_run.py   self-play, or a two-table match against the baseline
shadow.py     the same questions asked of a second setup
summary.py    results/summary.json and results/summary.md
data/         the 60 boards with their fixed auctions
results/      one file per run, and the summary
```
