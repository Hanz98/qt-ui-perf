# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] — unreleased

First consumable version.

### Added

- `harness/perfdriver` is the CMake package **QtUiPerf** (`project(QtUiPerf VERSION 0.1.0)`):
  exported target `QtUiPerf::perfdriver`, install rules, generated `QtUiPerfConfig.cmake` +
  `QtUiPerfConfigVersion.cmake`, usable through `add_subdirectory`, `FetchContent` and
  `find_package`. Qt is detected when the including project did not set `QT_VERSION_MAJOR`;
  `-DPERFDRIVER_QT_MAJOR=5|6` pins it.
- `qtuiperf_instrument(<target>)`: links the seam and defines `QTUIPERF_ENABLED`, the one
  line an application needs besides the two guarded calls in `main()`.
- Root `CMakeLists.txt` building the seam and the sample app, with the CTest test
  `sample_app_scenario` (plays `scenarios/sample_app.json` headless).
- `examples/fetchcontent/`: minimal FetchContent consumer.
- `pyproject.toml`: `tools/` installs as the Python package `qtuiperf` with the console
  script `perfdrive` (`pip install git+https://github.com/Hanz98/qt-ui-perf.git`).
- `scenarios/schema.json`: JSON Schema (draft-07) for scenario files; every scenario in the
  repository is validated against it by `tests/test_scenarios.py`.
- `docs/integration.md`: CMake integration, the `main()` calls, objectName conventions,
  Python install.
- The seam itself (`PerfDriver::markProcessStart` / `installIfRequested`, stdin/stdout JSON
  protocol, click/key/wheel/get/wait/stats commands, jank meter), `tools/perfdrive.py`
  (headless + display lanes, warm-up, median/p95), the instrumented sample app, the fake-app
  driver tests and the GitHub Actions smoke matrix (Linux Qt 5/6, Windows Qt 6).

### Changed

- The sample app's compile definition for the seam is `QTUIPERF_ENABLED` (was
  `SAMPLEAPP_PERF_DRIVER`); the `SAMPLEAPP_PERF_DRIVER` CMake option is unchanged.
  `sample-app/testing-changes.diff` regenerated accordingly.
