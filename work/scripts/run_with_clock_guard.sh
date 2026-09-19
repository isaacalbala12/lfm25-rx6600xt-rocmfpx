#!/usr/bin/env bash
# Run a command while sampling the GPU memory clock, and report the clock
# histogram alongside the wall time.
#
# The RX 6600 XT drops mclk from 1000 MHz to 541 MHz in a state this campaign
# had previously only seen with ubatch=512. A run in that state is about 40%
# slower, so any throughput comparison has to state which state it ran in or it
# is not a measurement.
#
# Usage: [INTERVAL=0.05] run_with_clock_guard.sh <label> <command...>
set -euo pipefail

INTERVAL=${INTERVAL:-0.05}
LABEL=${1:?usage: run_with_clock_guard.sh <label> <command...>}
shift

CARD=${CARD:-/sys/class/drm/card1/device}
SAMPLES=$(mktemp)

(
  while true; do
    mclk=$(grep '\*' "$CARD/pp_dpm_mclk" 2>/dev/null | awk '{print $2}')
    sclk=$(grep '\*' "$CARD/pp_dpm_sclk" 2>/dev/null | awk '{print $2}')
    printf '%s %s\n' "${mclk:-?}" "${sclk:-?}" >> "$SAMPLES"
    sleep "$INTERVAL"
  done
) &
sampler=$!
trap 'kill "$sampler" 2>/dev/null || true; wait "$sampler" 2>/dev/null || true; rm -f "$SAMPLES"' EXIT

start=$(date +%s.%N)
"$@"
status=$?
end=$(date +%s.%N)

kill "$sampler" 2>/dev/null || true
wait "$sampler" 2>/dev/null || true

python3 - "$LABEL" "$SAMPLES" "$start" "$end" "$status" <<'PY'
import collections
import sys

label, path, start, end, status = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5])
samples = [line.split() for line in open(path) if line.strip()]
mclk = collections.Counter(s[0] for s in samples)
sclk = collections.Counter(s[1] for s in samples)
active = [s for s in samples if s[0] not in ("96Mhz", "?")]
duty = collections.Counter(s[0] for s in active)
print(f"[clock] {label}: wall={end-start:.2f}s status={status} "
      f"mclk_active={dict(duty.most_common(3))} sclk_top={dict(sclk.most_common(2))}")
PY
exit $status
