---
status: accepted
date: 2026-10-19
---
# Qt Quick support is an optional compile-time component on top of the Widgets seam

The seam started Widgets-only. Qt Quick support (item-tree lookup, input to the
`QQuickWindow`, "painted" = `frameSwapped`/`afterRendering`, per-window frame stats) is
compiled in only when `PERFDRIVER_QUICK` is on (default: on when Qt Quick is found), so a
pure Widgets application never links QtQuick and the Widgets code path is untouched.
The seam still links QtWidgets even for a Quick application; dropping that
(`PERFDRIVER_WIDGETS=OFF`) is future work, accepted because QtWidgets is universally
available and the extra dependency is harmless for the measurements.
