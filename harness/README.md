# harness/ — the in-process pieces

## perfdriver/ (the automation seam) — implemented

A static library (`perfdriver`) linked into the real application. Two calls in `main()`:

```cpp
PerfDriver::markProcessStart();        // first line of main(): starts the startup clock
QApplication app(argc, argv);          // or QGuiApplication for a Qt Quick application
PerfDriver::installIfRequested(app);   // no-op unless --perf-driver or QT_PERF_DRIVER is set
```

`sample-app/testing-changes.diff` (Widgets) and `sample-app-quick/testing-changes.diff`
(Qt Quick) show the complete set of changes this needs in an app.

### Building it in

```cmake
add_subdirectory(path/to/harness/perfdriver perfdriver)   # needs QT_VERSION_MAJOR set
target_link_libraries(MyApp PRIVATE perfdriver)
```

The seam always links `Qt::Widgets`. Qt Quick support is optional and controlled by the
CMake option `PERFDRIVER_QUICK`: default **ON when the `Qt::Quick` package is found, OFF
otherwise**, so a Widgets-only build on a machine without Qt Quick needs nothing extra, and
`-DPERFDRIVER_QUICK=OFF` keeps QtQuick out of a Widgets application even when it is
installed. The source is guarded with `PERFDRIVER_HAVE_QUICK`. Both Qt 5.15 and Qt 6 work.

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

### Addressing objects

An object path is one or more `/`-separated segments. The first segment is searched among
all top-level widgets and their descendants, then among all `QQuickWindow`s and their item
trees (`contentItem()` downwards); every further segment among the descendants of the
previous match. A segment is one of:

| segment | matches |
|---|---|
| `countButton` | `objectName` (always tried first) |
| `Button` | class name: `Button`, `QButton`, `QQuickButton`, a base class of the object, or a QML type derived from one of those (`Button_QMLTYPE_4`). So `PushButton` finds a `QPushButton`, `Button` a Qt Quick Controls `Button` |
| `Button=Count` | class as above **and** the `text` property (else `accessibleName`, else `title`) equals `Count` |

`mainWindow/Label=Ready.` therefore finds the status label of either sample app. Prefer
`objectName`s in scenarios (stable across restyling); class selectors are for applications
you cannot change. Run `tools/perfdrive.py --app … --tree` to see what is there.

### Commands

| command | effect | reply fields |
|---|---|---|
| `{"op":"find","object":…}` | locate an object | `class`, `name`, `visible`, `enabled`, `geometry` (Qt Quick: scene coordinates, plus `window`) |
| `{"op":"get","object":…,"property":"text"}` | read any Qt property | `value` |
| `{"op":"tree","depth":8,"window":…,"max":5000}` | dump the object tree: every top-level widget and `QQuickWindow` with its descendants, as a flat depth-annotated list (`window` restricts it to one top-level by `objectName`/class selector; non-visual children appear only when they have an `objectName`) | `nodes[]{depth,class,name,visible,geometry,text}`, `count`, `truncated` |
| `{"op":"click","object":…}` | synthetic press+release at the object's centre, then wait for the next repaint/frame of its window | `dispatch_ms`, `painted`, `paint_ms`, `enabled` (+ `accepted` for Quick) |
| `{"op":"key","object":…,"keys":["Right","Ctrl+A"],"text":"abc"}` | focus the object, send key press/release pairs, wait for repaint | `dispatch_ms`, `keys`, `painted`, `paint_ms` (+ `focused` for Quick) |
| `{"op":"wheel","object":…,"delta":-120,"axis":"y"}` | one synthetic wheel event, wait for repaint | `dispatch_ms`, `accepted`, `painted`, `paint_ms` |
| `{"op":"wait_first_frame"}` | resolve at the first widget paint event or the first frame of any `QQuickWindow`, whichever comes first | `first_paint_ms` |
| `{"op":"wait_idle","ms":300}` | resolve after `ms` without paint/update events or Quick frames | — |
| `{"op":"stats","reset":false}` | jank meter, paint counters, Quick frame stats | `jank{count,p50,p95,max,over_50ms}`, `paint_count`, `first_paint_ms`, `frames[]` |
| `{"op":"mark"}` / `{"op":"ping"}` | timestamp only | — |
| `{"op":"quit"}` | reply, then `QCoreApplication::quit()` | — |

`paint_ms` is measured from just before the input events are sent to the moment the
window shows the result: for Widgets the first `QEvent::Paint` for a widget of the same
top-level window (input handling plus layout, up to the start of repainting); for Qt Quick
the first `afterRendering`/`frameSwapped` of the item's `QQuickWindow` (input handling,
property bindings, scene graph sync and render, timestamped on the render thread). If
nothing repaints within `timeout_ms` (default 1000) the reply has `painted:false` and
`paint_ms:null`, which the driver drops from the statistics; the scenario's `get … expect`
checks are what catch an interaction that did nothing.

Always-on while active: the **jank meter**, a 16 ms precise timer whose lateness per tick is
recorded (`stats` reports its percentiles; `over_50ms` counts ticks that were late by more
than 50 ms, i.e. visible stutters). It starts when the seam is installed, so the first
`stats` of a Qt Quick application includes the QML engine load; use `{"op":"stats",
"reset":true}` after startup to measure the interactions on their own.

Why synthetic events in-process: they bypass the OS input stack, so they work in Windows
Session 0, in locked sessions and on the `offscreen` plugin. They do not exercise the
platform input plugin, which is accepted; that is not where an application's performance
lives.

### Qt Quick

Enabled by `PERFDRIVER_QUICK` (above). What changes for a `QQuickItem`:

- **Input.** `click` and `wheel` send `QMouseEvent`/`QWheelEvent` to the item's
  `QQuickWindow` at the item's scene-mapped centre, so they go through the window's normal
  delivery (hit testing, pointer handlers, Controls). `key` calls `forceActiveFocus()` on the
  item and sends the `QKeyEvent`s to the window, which routes them to its active focus item;
  if the item could not take active focus (the window is not active on the platform plugin)
  the events go straight to the item and the reply says `focused:false`.
- **Paint detection** uses `QQuickWindow::frameSwapped` and `afterRendering` (whichever
  arrives first; `afterRendering` is the fallback for render loops that never report a
  swap) instead of `QEvent::Paint`. `wait_first_frame` resolves on the first frame of any
  `QQuickWindow` when no widget paints first. Windows are discovered as they are shown, so
  windows created from QML after `installIfRequested()` are covered.
- **`stats` → `frames`**: one entry per `QQuickWindow` seen, `{window, class, source,
  count, first_frame_ms, interval_p50, interval_p95, interval_max, fps}`. Intervals are
  between consecutive `frameSwapped` timestamps since the last `reset`; `fps` is
  `(count-1)/span`. `tools/perfdrive.py` records them as `frames.<window>.count`,
  `.fps`, `.interval_p50/p95/max`. In the headless lane frames are produced on demand (one
  per interaction), so these are only frame-pacing numbers in the display lane with a real
  render loop and vsync.
- **Headless lane:** the `offscreen` platform plugin has no OpenGL on CI machines, so a Qt
  Quick scenario sets `"env": {"QT_QUICK_BACKEND": "software"}` (see
  `scenarios/sample_app_quick.json`). The software backend paints on the GUI thread and is
  fine for CPU-side numbers; the display lane leaves the backend to the real GPU.

Limits:

- A Qt Quick application still links `QtWidgets` through the seam (the Widgets paths are
  unconditional); a `PERFDRIVER_WIDGETS=OFF` switch is future work.
- A continuously animating scene (running `Animation`s, a blinking cursor in a focused
  `TextField`) produces frames all the time, so `wait_idle` never resolves and fails with
  `timed out`; pause the animations in the perf build or do not use `wait_idle` there.
- The paint wait is per window; a click that opens a *new* window is reported as painted
  when the clicked item's window renders, not when the new one does. One window at a time.
- `QQuickWidget` (Quick inside a widget) is driven as a widget: input works, paint detection
  comes from the widget's `QEvent::Paint`, the `frames` entry is its internal window.
- No `touch`, `drag`, `hover` or screenshots yet. Addressing by `Accessible.name` of QML
  items is not available (`accessibleName` is a widget property; QML uses an attached
  property the seam cannot read generically).

## qbench/ (optional micro-benchmarks) — not started

A QtTest executable with `QBENCHMARK` blocks for hot code paths (models, delegates, file
parsers). Run with `-perfcounter instructions -iterations 20 -o bench.csv,csv` on Linux
for near-deterministic counts; `-tickcounter` or `-walltime` on Windows with more
iterations. Added once the scenario lane is stable and we know what to zoom into.
