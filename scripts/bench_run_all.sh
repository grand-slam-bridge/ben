#!/bin/bash
#
# Run the card-play benchmark across the six settings (2026-10-05).
#
# Each setting is a COPY of default_api.conf with only the named keys changed, written to
# a temp directory. The repository's own config is never touched, so nothing here can
# alter what the service deploys.
#
#   bash scripts/bench_run_all.sh <workdir> <python> <deals>
#
# The service is restarted for each setting - settings are read once at start-up - and the
# results land in <workdir>/results-<label>.json.
#
set -u
R="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${1:?workdir}"; PY="${2:?python}"; DEALS="${3:-10}"
DDS3="${DDS3PKG:-$WORK/dds3pkg}"
mkdir -p "$WORK/conf" "$WORK/out"

# key=value pairs per setting; everything else stays exactly as deployed.
set_conf() {
  local label="$1"; shift
  local src="$R/src/config/default_api.conf"
  local dst="$WORK/conf/$label.conf"
  cp "$src" "$dst"
  for kv in "$@"; do
    local k="${kv%%=*}" v="${kv#*=}"
    # only replace an existing key, never add one
    if grep -qE "^$k *=" "$dst"; then
      sed -i '' -E "s|^$k *=.*|$k = $v|" "$dst" 2>/dev/null || sed -i -E "s|^$k *=.*|$k = $v|" "$dst"
    else
      echo "  !! $label: no such key $k" >&2
    fi
  done
  echo "$dst"
}

declare -a LABELS=(deployed stop8 upstream pimc-off net-alone lead100)

conf_for() {
  case "$1" in
    deployed)  set_conf deployed ;;
    stop8)     set_conf stop8 pimc_stop_trick_declarer=8 pimc_stop_trick_defender=8 ;;
    upstream)  set_conf upstream pimc_wait=3 pimc_max_playouts=200 \
                        pimc_stop_trick_declarer=8 pimc_stop_trick_defender=8 ;;
    pimc-off)  set_conf pimc-off pimc_use_declaring=False pimc_use_defending=False \
                        pimc_use_discarding=False ;;
    # "the neural net alone, no search" AS FAR AS THE SETTINGS CAN EXPRESS IT (2026-10-06).
    #
    # It was double_dummy=False, which routes the lead through single_dummy_estimates and
    # the sd model. THAT PATH IS DEAD IN THIS BUILD: it assembles a 165-feature vector
    # assuming 32-card encodings - 32 + 5 + 4*32, which is exactly the sd model's input -
    # but this config is model_version 3 with n_cards_bidding = 24, so
    # self.handbidding.reshape(32) throws "cannot reshape array of size 24 into shape
    # (32,)" on EVERY lead. The service answered 400 to all of them, served 0 cards, and
    # the setting produced no result file. It is the same root cause as the two models
    # that will not warm at start-up: sd and sd_no_lead belong to the older 32-card
    # generation. Patching the reshape would feed the model a differently shaped world
    # than it was trained on, which is worse than leaving it alone.
    #
    # So there is no working "no double dummy" card mode to select. What CAN be said with
    # settings is: no PIMC anywhere, and the opening lead taken straight from the net -
    # lead_accept_nn = 0 makes every lead "NN - best" and skips the simulation's verdict.
    # Against pimc-off, which differs only in the lead, this isolates what the lead
    # simulation is worth.
    net-alone) set_conf net-alone pimc_use_declaring=False pimc_use_defending=False \
                        pimc_use_discarding=False lead_accept_nn=0 ;;
    lead100)   set_conf lead100 sample_hands_opening_lead=100 ;;
  esac
}

for label in "${LABELS[@]}"; do
  conf="$(conf_for "$label")"
  echo "=== $label  ($conf) ==="
  # EVERY OLD SERVICE MUST BE GONE FIRST. A stale one still holding 8085 makes the new
  # one die with "Address already in use" while the benchmark cheerfully talks to the
  # OLD process - so boards get played against the previous settings and the numbers are
  # quietly wrong. Two runs were thrown away to this. Fail loudly instead.
  pkill -f "gameapi.py" 2>/dev/null
  pkill -f "run-.*\.sh" 2>/dev/null
  sleep 3
  if lsof -ti:8085 >/dev/null 2>&1; then
    lsof -ti:8085 | xargs kill -9 2>/dev/null
    sleep 2
  fi
  if lsof -ti:8085 >/dev/null 2>&1; then
    echo "!! port 8085 is still held by $(lsof -ti:8085 | tr '\n' ' ') - skipping $label" >&2
    continue
  fi
  # A WRAPPER, NOT A SUBSHELL. macOS strips DYLD_* when a process is spawned, so exporting
  # it in a subshell does not reach the service: PIMC then cannot load its own DDS and the
  # FIRST card request kills the process outright -
  #   System.DllNotFoundException: Unable to load shared library 'dds'
  #   Fatal Python error: Aborted
  # which reads from the client side as "Remote end closed connection without response"
  # on every board. Writing a script and exec-ing it carries the variable through.
  cat > "$WORK/run-$label.sh" <<WRAP
#!/bin/bash
cd "$R/src"
export BEN_HOME="$R"
export TF_CPP_MIN_LOG_LEVEL=3
export PYTHONPATH="$DDS3"
export DYLD_LIBRARY_PATH="$R/bin/BGA/macos/arm64"
exec "$PY" gameapi.py --host 127.0.0.1 --config "$conf"
WRAP
  chmod +x "$WORK/run-$label.sh"
  nohup "$WORK/run-$label.sh" > "$WORK/out/api-$label.log" 2>&1 &
  # wait for the port, up to 90 s
  # Wait for a real DECISION, not just an open port: the service answers / long before
  # the models are loaded, and PIMC's failure only shows when a card is asked for.
  ready=0
  for i in $(seq 1 180); do
    if curl -sS --max-time 5 "http://127.0.0.1:8085/lead?hand=K93.AKT3.643.KJ5&seat=E&dealer=N&vul=&ctx=1D-P-2D-P-P-P&details=false" 2>/dev/null | grep -q '"card"'; then
      ready=1; break
    fi
    sleep 1
  done
  if ! grep -q "$(basename "$conf")" "$WORK/out/api-$label.log" 2>/dev/null; then
    echo "!! $label: the answering service did not load $conf - skipping it" >&2
    continue
  fi
  if [ "$ready" != "1" ]; then
    echo "  !! $label: service never answered a lead - see $WORK/out/api-$label.log" >&2
    grep -m1 -E "Unable to load shared library|Fatal Python error" "$WORK/out/api-$label.log" >&2
    continue
  fi
  PYTHONPATH="$DDS3" "$PY" "$R/scripts/bench_card_play.py" \
     --deals "$DEALS" --label "$label" --out "$WORK/out/results-$label.json" \
     2>&1 | tail -3

  # ONE RETRY IF THE SETTING PRODUCED NOTHING. BGADLL.dylib - PIMC's native library -
  # aborts the whole process occasionally and unpredictably: three SIGABRTs inside it on
  # 2026-10-05, then 1145 cards across two runs without one. When it does go, every
  # remaining board of that setting fails with "Connection refused" and the setting is
  # lost. A restart and one more attempt costs a few minutes and saves the run.
  if ! grep -q '"boards": \[{' "$WORK/out/results-$label.json" 2>/dev/null; then
    echo "  !! $label produced no boards - restarting the service and retrying once" >&2
    lsof -ti:8085 | xargs kill -9 2>/dev/null; sleep 5
    nohup "$WORK/run-$label.sh" > "$WORK/out/api-$label-retry.log" 2>&1 &
    for i in $(seq 1 180); do
      curl -sS --max-time 5 "http://127.0.0.1:8085/lead?hand=K93.AKT3.643.KJ5&seat=E&dealer=N&vul=&ctx=1D-P-2D-P-P-P&details=false" 2>/dev/null | grep -q '"card"' && break
      sleep 1
    done
    PYTHONPATH="$DDS3" "$PY" "$R/scripts/bench_card_play.py" \
       --deals "$DEALS" --label "$label" --out "$WORK/out/results-$label.json" \
       2>&1 | tail -3
  fi
done
pkill -f "gameapi.py" 2>/dev/null
echo "ALL DONE: $WORK/out"
