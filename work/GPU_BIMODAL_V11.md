# V11: the GPU is bimodal, and half the campaign's measurements are in the slow mode

## Summary

The RX 6600 XT on this host enters, at random and unrelated to the code under
test, a state where MEMCLK oscillates between 1000 MHz and 541 MHz. In that
state a decode workload runs **about 40% slower**. It happened in 5 of 12
interleaved runs measured for this note, and it invalidates any measurement that
does not say which state it ran in.

| State | MEMCLK | Decode B=4, FP4_FAST | Spread |
| --- | --- | ---: | ---: |
| Fast | 1000 MHz steady | 393.0 -- 401.8 tok/s | 2.2% |
| Slow | oscillating 1000/541 MHz | 223.7 -- 239.1 tok/s | 6.9% |

The two states are 1.56x apart, which is larger than every kernel result the
campaign ever produced, and it is not attributable to any code change.

## How it was found

A format screen repeated the same command on the same binary and got 397.32,
239.71, 394.66, 239.96, 239.91, 393.33 tok/s. Correlating each run with a 0.05 s
MEMCLK sample gives the mechanism directly: every slow run contains repeated
samples at 541 MHz, every fast run is steady at 1000 MHz.

```
run2: S_TG=239.71  mclk_active={1000Mhz: 45, 541Mhz: 2, 675Mhz: 1}
run3: S_TG=394.66  mclk_active={1000Mhz: 29}
```

`power_dpm_force_performance_level` is `auto` and the active power profile is
`0 BOOTUP_DEFAULT`, whose MEMCLK row is
`MinActiveFreqType=1 MinActiveFreq=0 BoosterFreq=4 BoosterFreq=800`. That
profile permits the memory clock to drop and oscillate. The `3D_FULL_SCREEN`
profile sets `MinActiveFreqType=4 MinActiveFreq=850` for MEMCLK, which would
hold it up.

**No power setting was changed.** This campaign's standing constraint is not to
touch power profiles, drivers or firmware, and that constraint is respected
here. The finding is reported rather than acted on because the setting is a
system-wide power decision, not a benchmark knob. Pinning the profile is a
one-line change (`pp_power_profile_mode` 1, or
`power_dpm_force_performance_level` `high`) that would remove this variance
entirely, and it also affects the *server*, not just the benchmarks: a
production run that lands in the slow state serves at 60% of its capability.

## What this explains about the earlier campaign

- `RESULTS.md` records a `ubatch=512` cliff in which C=1 fell to 68.03 and C=4
  to 110.14 tok/s and "the memory clock alternated between 541 and 1000 MHz",
  while direct `llama-bench` did not reproduce it. That is this state. It was
  attributed to `ubatch=512` and worked around with `ubatch=128`; the real
  cause is that the GPU can enter it at any time, as the measurements above
  show at `ubatch=128`.
- V3 measured 229.27 tok/s where the published series said 233.99 and recorded
  the difference as an unexplained artifact-state mismatch. A low-state run is a
  plausible explanation for a swing of that size.
- The campaign's repeated instruction not to trust single runs, its 10-pair
  protocols and its wide bootstrap intervals are all consistent with a
  measurement floor that was actually bimodal rather than noisy.

Any A/B in this repository whose arms were not interleaved and clock-checked
should be treated as provisional until re-run under the protocol below.

## Measurement protocol from here

1. Every throughput measurement runs interleaved with its control.
2. Runs are classified into the fast and slow modes by clustering; the reported
   figure is the fast-mode mean, with the mode split stated.
3. `work/scripts/run_with_clock_guard.sh` samples MEMCLK alongside any command
   and prints the active-clock histogram, so a run can be labelled after the
   fact without a second tool.

Re-measuring the fold under this protocol gives **+13.0%** at four slots
(fast-mode control 351.9 tok/s from 2 clean runs, fast-mode folded 397.6 tok/s
from 5 clean runs), consistent with the +15.9% first observed and well above the
2.2% within-mode spread.

## Decision

**KEEP as a measurement gate, do not change the power profile without
authorization.** Every subsequent result in this campaign states its mode split.
