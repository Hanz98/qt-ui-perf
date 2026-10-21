#include <QGuiApplication>
#include <QQmlApplicationEngine>

#ifdef SAMPLEAPP_PERF_DRIVER
#include <perfdriver.h>
#endif

int main(int argc, char *argv[])
{
#ifdef SAMPLEAPP_PERF_DRIVER
    PerfDriver::markProcessStart();   // startup is measured from here
#endif
    QGuiApplication app(argc, argv);
#ifdef SAMPLEAPP_PERF_DRIVER
    PerfDriver::installIfRequested(app);   // no-op without --perf-driver
#endif
    QQmlApplicationEngine engine;
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreated, &app,
                     [](QObject *object, const QUrl &) {
                         if (!object)
                             QCoreApplication::exit(1);
                     }, Qt::QueuedConnection);
    engine.load(QUrl(QStringLiteral("qrc:/main.qml")));
    return app.exec();
}
