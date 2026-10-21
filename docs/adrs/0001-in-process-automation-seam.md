---
status: accepted
date: 2026-10-16
---
# Drive the application from inside the process, never through the OS desktop

The target CI agents (Jenkins on Linux and Windows) run as services or sit at a locked
screen. Anything that touches the OS desktop — `SendInput`, `xdotool`, UI Automation /
AT-SPI drivers, screenshot-based tools — fails there or produces meaningless timings
(Windows Session 0 has no desktop; a locked session routes input to the lock screen and
stops presenting frames). We therefore link a small automation seam into the application
itself: it receives commands, delivers input as Qt events and measures from inside. The price
is that the application's source must be available and shipped with the seam compiled in
(see 0007); the alternative, an external accessibility driver, needs an unlocked interactive
desktop, which is exactly what we cannot rely on.

## Consequences

- Out of scope for good: OS-level input injection, pixel/visual regression testing, a GUI
  recorder. They need the desktop we do not have and would blur what this tool is for.
- Applications without source access cannot use this framework. Documented, not worked around.
