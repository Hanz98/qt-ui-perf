---
status: accepted
date: 2026-10-19
---
# Regressions are judged against a baseline with a learned noise band, never absolute numbers

A fixed "startup must be under 500 ms" is wrong on every machine but the one it was written
on. `tools/compare.py` instead compares each metric's median to a baseline (the last green
result of the main branch for the same OS × lane × scenario, kept as a store of the last
20 runs) with relative thresholds per metric (`unstable_pct`, `fail_pct` in the scenario).
Once the store holds at least 5 runs, a noise band of median ± 3·MAD of the stored medians
rescues metrics that are over the percentage threshold but inside their own historical
noise, so a jittery metric does not fail builds. Medians and p95 are reported, never means:
one GC pause or page-in would otherwise move the mean of a 5-run sample.

MAD was chosen over a bootstrap interval because it is deterministic, outlier-robust and
meaningful at five samples.
