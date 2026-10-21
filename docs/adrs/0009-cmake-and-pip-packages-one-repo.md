---
status: accepted
date: 2026-10-19
---
# One repository ships both a CMake package and a pip package

The C++ seam (`harness/perfdriver`) is the CMake package `QtUiPerf` — consumable by
`add_subdirectory`, `FetchContent` or `find_package` after install — and the Python tools
are the pip distribution `qtuiperf` (`perfdrive`, `compare` commands), built from the same
tree and the same version number. Splitting them into two repositories was rejected: the
protocol between seam and driver is the contract, and a version of one only makes sense
with the matching version of the other. The protocol itself carries no version field yet;
when it changes incompatibly, the major version of both packages moves together.
