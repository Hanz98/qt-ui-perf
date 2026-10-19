#pragma once

class QCoreApplication;

/// In-process automation seam for UI performance tests (see ../README.md).
///
/// Protocol: newline-delimited JSON commands on stdin, replies on stdout prefixed with
/// "@perf " so they can be told apart from the application's own output. Input is delivered
/// as synthetic Qt events, so it works on any platform plugin (offscreen included), in a
/// locked session and in Windows Session 0. Driven by tools/perfdrive.py.
namespace PerfDriver {

/// Starts the process clock. Call it on the first line of main(), before QApplication.
void markProcessStart();

/// Installs the driver if "--perf-driver" is among the arguments or QT_PERF_DRIVER is set.
/// Returns true when installed. Costs nothing otherwise.
bool installIfRequested(QCoreApplication &app);

} // namespace PerfDriver
