#include "mainwindow.h"

#include <QApplication>

#ifdef SAMPLEAPP_PERF_DRIVER
#include <perfdriver.h>
#endif

int main(int argc, char *argv[])
{
#ifdef SAMPLEAPP_PERF_DRIVER
    PerfDriver::markProcessStart();   // startup is measured from here
#endif
    QApplication app(argc, argv);
#ifdef SAMPLEAPP_PERF_DRIVER
    PerfDriver::installIfRequested(app);   // no-op without --perf-driver
#endif
    MainWindow window;
    window.show();
    return app.exec();
}
