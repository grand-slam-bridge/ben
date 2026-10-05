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
    net-alone) set_conf net-alone pimc_use_declaring=False pimc_use_defending=False \
                        pimc_use_discarding=False double_dummy=False ;;
    lead100)   set_conf lead100 sample_hands_opening_lead=100 ;;
  esac
}

for label in "${LABELS[@]}"; do
  conf="$(conf_for "$label")"
  echo "=== $label  ($conf) ==="
  pkill -f "gameapi.py" 2>/dev/null; sleep 2
  (
    cd "$R/src"
    export BEN_HOME="$R" TF_CPP_MIN_LOG_LEVEL=3 PYTHONPATH="$DDS3"
    export DYLD_LIBRARY_PATH="$R/bin/BGA/macos/arm64"
    nohup "$PY" gameapi.py --host 127.0.0.1 --config "$conf" > "$WORK/out/api-$label.log" 2>&1 &
  )
  # wait for the port, up to 90 s
  for i in $(seq 1 90); do
    curl -sS -o /dev/null --max-time 2 "http://127.0.0.1:8085/" 2>/dev/null && break
    sleep 1
  done
  PYTHONPATH="$DDS3" "$PY" "$R/scripts/bench_card_play.py" \
     --deals "$DEALS" --label "$label" --out "$WORK/out/results-$label.json" \
     2>&1 | tail -3
done
pkill -f "gameapi.py" 2>/dev/null
echo "ALL DONE: $WORK/out"
