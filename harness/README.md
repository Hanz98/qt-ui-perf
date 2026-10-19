# harness/ — the in-process pieces

## perfdriver/ (the automation seam) — implemented

A static library (`perfdriver`) linked into the real application. Two calls in `main()`:

```cpp
PerfDriver::markProcessStart();        // first line of main(): starts the startup clock
QApplication app(argc, argv);
PerfDriver::installIfRequested(app);   // no-op unless --perf-driver or QT_PERF_DRIVER is set
```

`sample-app/testing-changes.diff` shows the complete set of changes this needs in an app.

### Transport

Newline-delimited JSON on the application's **stdin/stdout**. Replies are prefixed with
`@perf ` so the driver can ignore the application's own output. No extra Qt module (no
QtNetwork, no QtTest), no named pipes or sockets, identical on Linux and Windows. The reader
thread uses the raw file descriptor rather than `std::cin`: a thread blocked in stdio holds
the stream lock and glibc's `exit()` deadlocks on it, so the app would never quit while the
driver keeps the pipe open. When stdin reaches EOF (the driver died) the application quits.

Commands are queued and run one at a time; a waiting command (for a paint, for idle) holds
the queue until its reply is out. Every reply carries the command `id` and `t`, the
milliseconds since `markProcessStart()`.

### Commands

Objects are addressed by `objectName`, optionally as a path `parent/child`; the first segment
is searched among all top-level widgets and their descendants.

| command | effect | reply fields |
|---|---|---|
| `{"op":"find","object":…}` | locate an object | `class`, `visible`, `enabled`, `geometry` |
| `{"op":"get","object":…,"property":"text"}` | read any Qt property | `value` |
| `{"op":"click","object":…}` | synthetic press+release at the widget's centre, then wait for the next repaint of its window | `dispatch_ms`, `painted`, `paint_ms`, `enabled` |
| `{"op":"key","object":…,"keys":["Right","Ctrl+A"],"text":"abc"}` | focus the widget, send key press/release pairs, wait for repaint | `dispatch_ms`, `keys`, `painted`, `paint_ms` |
| `{"op":"wheel","object":…,"delta":-120,"axis":"y"}` | one synthetic wheel event, wait for repaint | `dispatch_ms`, `accepted`, `painted`, `paint_ms` |
| `{"op":"wait_first_frame"}` | resolve at the first widget paint event | `first_paint_ms` |
| `{"op":"wait_idle","ms":300}` | resolve after `ms` without paint/update events | — |
| `{"op":"stats","reset":false}` | jank meter and paint counters | `jank{count,p50,p95,max,over_50ms}`, `paint_count`, `first_paint_ms` |
| `{"op":"mark"}` / `{"op":"ping"}` | timestamp only | — |
| `{"op":"quit"}` | reply, then `QCoreApplication::quit()` | — |

`paint_ms` is measured from just before the input events are sent to the moment the first
`QEvent::Paint` for a widget of the same top-level window is delivered, i.e. input handling
plus layout, up to the start of repainting. If nothing repaints within `timeout_ms`
(default 1000) the reply has `painted:false` and `paint_ms:null`, which the driver drops from
the statistics; the scenario's `get … expect` checks are what catch an interaction that did
nothing.

Always-on while active: the **jank meter**, a 16 ms precise timer whose lateness per tick is
recorded (`stats` reports its percentiles; `over_50ms` counts ticks that were late by more
than 50 ms, i.e. visible stutters).

Why synthetic events in-process: they bypass the OS input stack, so they work in Windows
Session 0, in locked sessions and on the `offscreen` plugin. They do not exercise the
platform input plugin, which is accepted; that is not where an application's performance
lives.

Limits of the first version: Widgets only (Qt Quick needs the item tree and
`QQuickWindow::frameSwapped`, planned), one window at a time for the paint wait, no
screenshots yet.

## qbench/ (optional micro-benchmarks) — not started

A QtTest executable with `QBENCHMARK` blocks for hot code paths (models, delegates, file
parsers). Run with `-perfcounter instructions -iterations 20 -o bench.csv,csv` on Linux
for near-deterministic counts; `-tickcounter` or `-walltime` on Windows with more
iterations. Added once the scenario lane is stable and we know what to zoom into.
