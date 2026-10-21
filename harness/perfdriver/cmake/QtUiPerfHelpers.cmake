# Helper for applications that compile in the perfdriver seam. Available after any of
#   add_subdirectory(<qt-ui-perf>/harness/perfdriver)
#   FetchContent_MakeAvailable(QtUiPerf)
#   find_package(QtUiPerf CONFIG)
#
#   qtuiperf_instrument(<target>)
#
# Links QtUiPerf::perfdriver into <target> (PRIVATE) and defines QTUIPERF_ENABLED for it, so
# the two calls in main() can be guarded:
#
#     #ifdef QTUIPERF_ENABLED
#     #include <perfdriver.h>
#     #endif
#     ...
#     #ifdef QTUIPERF_ENABLED
#         PerfDriver::markProcessStart();
#     #endif
#         QApplication app(argc, argv);
#     #ifdef QTUIPERF_ENABLED
#         PerfDriver::installIfRequested(app);
#     #endif
#
# Put the call behind your own option to build the seam out of release binaries:
#
#     option(MYAPP_PERF_DRIVER "Compile in the UI perf seam" ON)
#     if(MYAPP_PERF_DRIVER)
#         qtuiperf_instrument(MyApp)
#     endif()
function(qtuiperf_instrument target)
    if(NOT TARGET ${target})
        message(FATAL_ERROR "qtuiperf_instrument: '${target}' is not a target")
    endif()
    if(NOT TARGET QtUiPerf::perfdriver)
        message(FATAL_ERROR "qtuiperf_instrument: QtUiPerf::perfdriver is not available; "
                            "add_subdirectory / FetchContent / find_package(QtUiPerf) first")
    endif()
    target_link_libraries(${target} PRIVATE QtUiPerf::perfdriver)
    target_compile_definitions(${target} PRIVATE QTUIPERF_ENABLED)
endfunction()
