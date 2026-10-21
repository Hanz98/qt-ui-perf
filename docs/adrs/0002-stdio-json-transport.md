---
status: accepted
date: 2026-10-16
---
# Transport is newline-delimited JSON over the application's own stdin/stdout

The driver and the seam talk over the pipes the driver already owns when it launches the
application: commands in on stdin, replies out on stdout prefixed with `@perf ` so the
application's own output can be ignored. No sockets, no named pipes, no QtNetwork, no QtTest:
nothing to open, nothing that differs between Linux and Windows, no extra Qt module an
application might not ship. The reader thread uses the raw file descriptor / `ReadFile`,
not `std::cin`: a thread blocked in stdio holds the stream lock and glibc's `exit()`
deadlocks on it, so the application would never quit while the driver keeps the pipe open.
Stdin reaching EOF means the driver died, and the application quits.

## Considered options

- TCP/local socket: works, but needs QtNetwork in the application and a free port per
  parallel run; rejected for the dependency.
- QtTest in-process harness linking the app's libraries: tighter coupling to the app's build
  and a second executable to maintain per app.
