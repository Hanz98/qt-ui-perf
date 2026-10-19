# Architecture decision records

Why the framework is shaped the way it is. One file per decision, numbered in the order they
were taken; a record is never edited to say something else — a later record supersedes it.
Add one when a choice is hard to reverse, would surprise a reader of the code, and had real
alternatives.

| # | Decision |
|---|---|
| [0001](0001-in-process-automation-seam.md) | Drive the application from inside the process, never through the OS desktop |
| [0002](0002-stdio-json-transport.md) | Transport is newline-delimited JSON over the application's own stdin/stdout |
| [0003](0003-two-lanes.md) | Two measurement lanes: headless gates merges, display runs nightly on dedicated agents |
| [0004](0004-synthetic-qt-events.md) | Input is synthetic Qt events, bypassing the platform input plugin |
| [0005](0005-relative-baselines-with-noise-band.md) | Regressions are judged against a baseline with a learned noise band, never absolute numbers |
| [0006](0006-scenarios-as-data-stdlib-driver.md) | Scenarios are JSON data; the driver is standard-library Python |
| [0007](0007-seam-compiled-in-dormant.md) | The seam is compiled into the application and dormant unless asked for |
| [0008](0008-qt-quick-optional-component.md) | Qt Quick support is an optional compile-time component on top of the Widgets seam |
| [0009](0009-cmake-and-pip-packages-one-repo.md) | One repository ships both a CMake package and a pip package |
| [0010](0010-github-ci-proves-tooling-not-performance.md) | GitHub Actions proves the tooling works; it never produces performance numbers |
