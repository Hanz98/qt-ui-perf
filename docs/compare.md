# The regression gate: `tools/compare.py` and the baseline store

`tools/perfdrive.py` measures; `tools/compare.py` decides. It reads one result JSON, compares
every metric's median with a baseline and exits with a code the pipeline turns into a build
status. Standard library only, Python 3.8+, same on Linux and Windows.

```sh
python3 tools/compare.py results/linux-headless-sample_app.json \
    --baseline baselines/linux-headless-sample_app.json \
    --scenario scenarios/sample_app.json \
    --junit results/linux-headless-sample_app-junit.xml \
    --markdown results/linux-headless-sample_app.md \
    --json results/linux-headless-sample_app-verdict.json
```

| Exit code | Meaning | Jenkins |
|---|---|---|
| 0 | every metric within its unstable threshold (or `new`) | SUCCESS |
| 1 | at least one metric over `unstable_pct`, or `missing` from the current result | UNSTABLE |
| 2 | at least one metric over `fail_pct` | FAILURE |
| 3 | usage or input error: unreadable or malformed file, no baseline, bad flags | treat as "no baseline yet", do not gate |

## What is compared

For each metric in the current result or the baseline:

- **baseline** = median of the baseline run(s); **current** = the current median;
  **delta** = `(current - baseline) / baseline`.
- Thresholds come from the scenario file's `thresholds` block, keyed by the full metric
  name as it appears in the result (`slider_key_to_paint_ms.p95` is its own entry):

  ```json
  "thresholds": {
    "startup_to_first_paint_ms": {"unstable_pct": 10, "fail_pct": 25},
    "scroll_fps":                {"unstable_pct": 10, "fail_pct": 25, "higher_is_better": true}
  }
  ```

  Metrics without an entry use `--default-unstable-pct 10 --default-fail-pct 25`. Every
  metric is "lower is better" unless its entry says `"higher_is_better": true`; then a *drop*
  is the regression and a rise is never flagged.
- Verdicts: `ok`, `unstable`, `fail`, `new` (in the current result but not the baseline;
  informational, exit 0), `missing` (in the baseline but not the current result; a scenario
  step probably stopped recording, so it counts as unstable). A baseline of 0 has no
  relative change; the metric is `ok` if it stayed at 0 and `unstable` otherwise.
- The overall verdict is the worst one.

## Baselines: a result file or a store

`--baseline` accepts two kinds of file:

1. **A perfdrive result** (`results/*.json`). Simple, no history, no noise band. This is what
   `tests/smoke.sh` does (a result against itself, which must exit 0) and what you do by hand
   to compare two local runs.
2. **A baseline store**, `baselines/<os>-<lane>-<scenario>.json`, maintained by this script:

   ```sh
   python3 tools/compare.py results/linux-headless-sample_app.json \
       --update-baseline baselines/linux-headless-sample_app.json --keep 20 --ref "$GIT_COMMIT"
   ```

   Each call appends the result's per-metric medians (plus time, host, platform, repeats and
   the optional `--ref` label) as one run and trims the file to the last `--keep` runs
   (default 20). The file is created if it does not exist and never overwrites a file that
   is not a store. Its shape is deliberately small enough to read in a diff:

   ```json
   {
     "kind": "qt-ui-perf-baseline-store",
     "scenario": "sample_app", "lane": "headless", "keep": 20,
     "runs": [
       {"time": "2026-10-19T08:00:00+00:00", "host": "perf-01", "platform": "Linux-...",
        "repeats": 7, "ref": "3f2a9c1", "metrics": {"startup_to_first_paint_ms": 41.2, "...": 0}}
     ]
   }
   ```

   The baseline value of a metric is the **median of the stored medians**, so one bad run in
   the history moves nothing.

### The noise band

With a store that holds at least `--min-runs` (default 5) runs of a metric, the script also
learns how much that metric wobbles between green builds: the band
`median ± --mad-factor × MAD` (default 3 × the median absolute deviation of the stored
medians). A metric is flagged only when it is **outside both** the percentage threshold and
the band. So a metric whose history is `100, 130, 90, 120, 110, 140` (median 115, MAD 15,
band 70–160) measured at 150 is +30 % but still `ok`, with the note "over fail but within
noise band"; at 170 it fails. A metric whose history never moved (MAD 0) gets a band of zero
width and the percentage threshold alone decides, as before.

Why MAD and not a bootstrap interval of the median: it is deterministic (no seed to argue
about in a CI log), it ignores the one or two outlier runs every perf history collects, and
it is meaningful at 5 samples where a bootstrap of the median is a handful of distinct
values. 3 × MAD is about 2 σ for normal noise, narrower than the usual 3 σ on purpose: the
band is a second opinion that stops a known-noisy metric from crying wolf, not a replacement
for the threshold. If a metric turns out to be noisier than its threshold allows, the right
fix is to widen its threshold in the scenario file (now with data), not to raise
`--mad-factor` globally.

The table on stdout and the `--json` output show which metrics had a band
(`"band": [low, high]`) and the summary line says `noise band active` when any did.

## The flow in Jenkins

`ci/Jenkinsfile`, per OS × lane cell:

1. **measure**: `perfdrive.py` writes `results/<os>-<lane>-<scenario>.json`.
2. **compare**: `copyArtifacts` fetches `baselines/*.json` from the last successful build of
   the same job, then `compare.py … --baseline baselines/<os>-<lane>-<scenario>.json` runs
   with `--junit`, `--markdown` and `--json`. Exit 1 → `unstable(...)`, exit 2 → `error(...)`,
   exit 3 (no store yet) → logged and skipped. The JUnit file gives one test case per metric
   on the build's test page (`unstable`/`missing`/`fail` are failures with that `type`); the
   Markdown file is what a PR comment or the build description shows.
3. **baseline** (main branch, build green or `UPDATE_BASELINE` ticked): `compare.py …
   --update-baseline` appends the run and the store is archived, so the next build picks it
   up. Any shared location works instead of job artifacts (a network share, an object store);
   the store is a plain file.

A PR build therefore compares against the last 20 green runs of main on the same OS, lane and
scenario, which is exactly the population whose noise the band describes. Bootstrapping a
new scenario or agent: let main run five times (exit 3, then threshold-only verdicts) and the
band switches on by itself.

## Outputs

- stdout: a table (metric, baseline, current, delta %, verdict, note) and a summary line.
- `--junit PATH`: one `<testsuite name="<scenario>.<lane>">` with one `<testcase>` per
  metric; the summary is in `<system-out>`.
- `--markdown PATH`: the same table as GitHub-flavoured Markdown with a bold verdict line.
- `--json PATH`: `{"verdict", "exit_code", "suite", "current", "baseline", "baseline_runs",
  "noise_band_active", "metrics": [{metric, baseline, baseline_runs, current, delta_pct,
  band, unstable_pct, fail_pct, higher_is_better, verdict, note}, …]}` for dashboards.

Output directories are created as needed. `tests/test_compare.py` covers all of the above
without Qt.
