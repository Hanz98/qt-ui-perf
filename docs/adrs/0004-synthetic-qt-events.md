---
status: accepted
date: 2026-10-16
---
# Input is synthetic Qt events, bypassing the platform input plugin

The seam delivers clicks, keys and wheel as `QMouseEvent` / `QKeyEvent` / `QWheelEvent`
posted to the widget or `QQuickWindow`, not through the platform plugin (xcb, windows,
wayland). This is what makes 0001 work on `offscreen`, in Session 0 and in locked sessions.
The accepted loss: the platform input path (event compression, touch synthesis, native
gesture recognition) is not exercised. We judged that acceptable because an application's
performance problems live in its own event handling, layout and painting, not in Qt's input
plugin, and the alternative (OS input) is unavailable where the tests must run.
