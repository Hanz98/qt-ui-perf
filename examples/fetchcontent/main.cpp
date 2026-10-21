// The complete app-side integration: two guarded calls in main() and objectNames on the
// widgets a scenario drives. Run it with --perf-driver (or QT_PERF_DRIVER=1) and
// tools/perfdrive.py takes over stdin/stdout.
#include <QApplication>
#include <QLabel>
#include <QPushButton>
#include <QVBoxLayout>
#include <QWidget>

#ifdef QTUIPERF_ENABLED
#include <perfdriver.h>
#endif

int main(int argc, char *argv[])
{
#ifdef QTUIPERF_ENABLED
    PerfDriver::markProcessStart();          // startup is measured from here
#endif
    QApplication app(argc, argv);
#ifdef QTUIPERF_ENABLED
    PerfDriver::installIfRequested(app);     // no-op without --perf-driver
#endif

    QWidget window;
    window.setObjectName(QStringLiteral("mainWindow"));
    auto *layout = new QVBoxLayout(&window);
    auto *label = new QLabel(QStringLiteral("Clicks: 0"), &window);
    label->setObjectName(QStringLiteral("clicksLabel"));    // scenario: get clicksLabel.text
    auto *button = new QPushButton(QStringLiteral("Count"), &window);
    button->setObjectName(QStringLiteral("countButton"));   // scenario: click countButton
    layout->addWidget(label);
    layout->addWidget(button);

    int clicks = 0;
    QObject::connect(button, &QPushButton::clicked, label, [&] {
        label->setText(QStringLiteral("Clicks: %1").arg(++clicks));
    });

    window.show();
    return app.exec();
}
