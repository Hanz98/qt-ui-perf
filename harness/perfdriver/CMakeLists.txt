# The automation seam. Link it into the application and call PerfDriver::markProcessStart()
# first thing in main() and PerfDriver::installIfRequested(app) after the application object
# exists. It stays dormant unless the app is started with --perf-driver (or QT_PERF_DRIVER=1).
# Expects QT_VERSION_MAJOR to be set by the including project.
add_library(perfdriver STATIC
    perfdriver.cpp
    perfdriver.h
)
target_include_directories(perfdriver PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(perfdriver PUBLIC Qt${QT_VERSION_MAJOR}::Widgets)
target_compile_features(perfdriver PUBLIC cxx_std_17)
