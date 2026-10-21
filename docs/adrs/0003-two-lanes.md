---
status: accepted
date: 2026-10-16
---
# Two measurement lanes: headless gates merges, display runs nightly on dedicated agents

CPU-side work (startup, layout, event handling, main-thread jank, memory) is deterministic
enough to gate a merge and runs anywhere with `QT_QPA_PLATFORM=offscreen` and a software
renderer — that is the **headless lane**. Real frame pacing needs a real GPU and compositor,
which only exists on a prepared machine (bare Xorg / eglfs on Linux, an auto-logged-on,
never-locked console session on Windows) — that is the **display lane**, run nightly for
trend charts and failing only on gross regressions. Measuring on shared build agents was
rejected outright: numbers from a machine running three jobs at once are noise that no
threshold absorbs.
