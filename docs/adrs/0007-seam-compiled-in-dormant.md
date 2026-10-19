---
status: accepted
date: 2026-10-16
---
# The seam is compiled into the application and dormant unless asked for

The instrumented build is the real build: `qtuiperf_instrument(MyApp)` links the seam, and
two calls in `main()` (`markProcessStart()`, `installIfRequested(app)`) cost nothing unless
the process is started with `--perf-driver` or `QT_PERF_DRIVER=1`. Measuring a separate
"test build" would measure something else than what ships (different inlining, different
startup path), and a separate test executable linking the app's libraries doubles the build
to maintain. Objects are addressed by `objectName` (path `parent/child`, with a
`Class=text` fallback), which the application has to set on the widgets it wants driven —
`sample-app/testing-changes.diff` is the complete recipe. The seam is a remote-control door
into the application: keeping it out of release builds is tracked as roadmap item 5.
