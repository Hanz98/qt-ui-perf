# Roadmap: from harness to library

What the project needs before another team can adopt it without reading our source.
Ordered by what unblocks adoption first. Each item is a GitHub issue; this page is the
overview and the reasoning.

| # | Item | Why it is in this position | Status |
|---|---|---|---|
| 1 | **Regression gate** — `tools/compare.py`: baseline store, per-metric thresholds plus a learned noise band, JUnit / Markdown / JSON output, exit codes 0/1/2 | Without it the project measures but never fails a build. This is the whole point. | in progress |
| 2 | **Qt Quick support** in the seam — item-tree addressing, `frameSwapped`-based paint detection, frame-interval stats, a Quick sample app and scenario | Most Qt applications built today are QML; Widgets-only excludes half the users. | in progress |
| 3 | **Packaging** — CMake package (`find_package(QtUiPerf)`, FetchContent, `qtuiperf_instrument(target)`), `pip install qt-ui-perf` with a `perfdrive` console script, scenario JSON Schema, versioning + CHANGELOG | Integration must be one line on each side, not a relative `add_subdirectory` path. | in progress |
| 4 | **Real-app robustness** — modal dialogs (`QDialog::exec` nested loops), message boxes, menus/popups, several windows, drag, hover, Unicode text, object lookup by class + text when `objectName` is missing, `tree` dump, screenshot on failure, clearer errors | The sample app has no dialogs; real apps are mostly dialogs. | after 2 |
| 5 | **Safety** — compile-time guard that is off outside test builds, loud startup banner when active, documented threat model, a CI check that release binaries do not contain the seam | The seam is a remote-control door into the application; "can this ship by accident?" is the first question a security review asks. | after 2 |
| 6 | **Metrics and exports** — CPU time, peak/private memory, allocation counts, Quick sync/render/swap times, optional Linux `perf` counters; JUnit, static HTML trend report, InfluxDB line protocol, `github-action-benchmark` format | Teams consume what their dashboards already understand. | after 1 |
| 7 | **A second, real sample** — instrument an existing open-source Qt application and keep it in CI; it doubles as the tutorial | Shakes out item 4 and proves the integration story in item 3. | after 3, 4 |
| 8 | **Compatibility matrix and seam tests** — macOS, MSVC + GCC + Clang, Qt 5.15 / 6.5 LTS / 6.8, QtTest unit tests for the seam itself | The C++ side is only exercised through the sample app today, and the Windows job has not run yet. | ongoing |
| 9 | **Docs for strangers** — versioned protocol spec, scenario reference, "instrument your app in 10 minutes", an architecture page that puts the locked-session argument up front | The selling point is buried in `docs/agents.md`. | after 3 |

Deliberately out of scope: pixel / visual regression testing, OS-level input injection, a
GUI recorder. Different tools; they would blur what this one is for.

## Order

1 → 2 → 3 → 5 turn the harness into a library. 4 and 7 go together once a real application
is in the tree. 6, 8 and 9 run alongside as capacity allows.
