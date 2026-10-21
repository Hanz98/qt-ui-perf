#include "mainwindow.h"

#include <QApplication>

#ifdef QTUIPERF_ENABLED
#include <perfdriver.h>
#endif

int main(int argc, char *argv[])
{
#ifdef QTUIPERF_ENABLED
    PerfDriver::markProcessStart();   // startup is measured from here
#endif
    QApplication app(argc, argv);
#ifdef QTUIPERF_ENABLED
    PerfDriver::installIfRequested(app);   // no-op without --perf-driver
#endif
    MainWindow window;
    window.show();
    return app.exec();
}
