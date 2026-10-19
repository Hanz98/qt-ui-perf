#include "perfdriver.h"

#include <QApplication>
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QEvent>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QKeyEvent>
#include <QKeySequence>
#include <QMouseEvent>
#include <QPointer>
#include <QTimer>
#include <QWheelEvent>
#include <QWidget>

#include <algorithm>
#include <cerrno>
#include <deque>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

#ifdef Q_OS_WIN
#include <windows.h>
#else
#include <unistd.h>
#endif

namespace {

QElapsedTimer g_processClock;

// Reads stdin without stdio. A thread blocked inside std::getline/fgets holds the stream's
// lock, and glibc's exit() then deadlocks while flushing all streams, so the application
// would never terminate while the driver keeps the pipe open.
bool readStdin(char *buffer, size_t size, size_t *got)
{
#ifdef Q_OS_WIN
    DWORD n = 0;
    if (!ReadFile(GetStdHandle(STD_INPUT_HANDLE), buffer, DWORD(size), &n, nullptr) || n == 0)
        return false;
    *got = n;
    return true;
#else
    for (;;) {
        const ssize_t n = ::read(0, buffer, size);
        if (n > 0) {
            *got = size_t(n);
            return true;
        }
        if (n < 0 && errno == EINTR)
            continue;
        return false;
    }
#endif
}

double nowMs()
{
    return g_processClock.isValid() ? g_processClock.nsecsElapsed() / 1e6 : 0.0;
}

double percentile(std::vector<double> values, double p)
{
    if (values.empty())
        return 0.0;
    std::sort(values.begin(), values.end());
    const auto index = static_cast<size_t>(p * double(values.size() - 1) + 0.5);
    return values[std::min(index, values.size() - 1)];
}

class Driver : public QObject
{
public:
    explicit Driver(QCoreApplication &app);
    bool eventFilter(QObject *watched, QEvent *event) override;

private:
    enum class Wait { None, FirstPaint, Paint, Idle };

    void handleLine(const QString &line);
    void pump();
    void dispatch(const QJsonObject &cmd);
    void reply(QJsonObject obj);
    void fail(const QString &message);

    QObject *find(const QString &path, QString *error) const;
    QWidget *findWidget(const QJsonObject &cmd, QString *error) const;

    void doFind(const QJsonObject &cmd);
    void doGet(const QJsonObject &cmd);
    void doClick(const QJsonObject &cmd);
    void doKey(const QJsonObject &cmd);
    void doWheel(const QJsonObject &cmd);
    void doStats(const QJsonObject &cmd);

    void awaitPaint(QWidget *window, int timeoutMs);
    void resolvePaint(bool painted);
    void onJankTick();

    std::deque<QJsonObject> m_queue; // commands received while one was still in flight
    QJsonValue m_id;                 // id of the command in flight
    Wait m_wait = Wait::None;
    QPointer<QWidget> m_waitWindow;  // top-level whose repaint we wait for (null = any)
    double m_waitSince = 0.0;
    QJsonObject m_partial;           // reply fields collected before the wait finished
    QTimer m_timeout;
    QTimer m_idle;

    double m_firstPaintMs = -1.0;
    qint64 m_paintCount = 0;

    QTimer m_jankTimer;
    QElapsedTimer m_jankClock;
    std::vector<double> m_jankLateness;
};

Driver::Driver(QCoreApplication &app)
    : QObject(&app)
{
    app.installEventFilter(this);

    m_timeout.setSingleShot(true);
    connect(&m_timeout, &QTimer::timeout, this, [this] {
        if (m_wait == Wait::Paint) {
            resolvePaint(false);
        } else if (m_wait != Wait::None) {
            m_wait = Wait::None;
            fail(QStringLiteral("timed out"));
        }
    });

    m_idle.setSingleShot(true);
    connect(&m_idle, &QTimer::timeout, this, [this] {
        if (m_wait == Wait::Idle) {
            m_wait = Wait::None;
            m_timeout.stop();
            reply({{QStringLiteral("ok"), true}});
        }
    });

    // Jank meter: a 16 ms timer whose lateness shows how long the main thread was busy.
    m_jankTimer.setTimerType(Qt::PreciseTimer);
    m_jankTimer.setInterval(16);
    connect(&m_jankTimer, &QTimer::timeout, this, &Driver::onJankTick);
    m_jankClock.start();
    m_jankTimer.start();

    // Reader thread: blocks on stdin, hands each line to the main thread.
    QPointer<Driver> self(this);
    std::thread([self] {
        std::string pending;
        char buffer[4096];
        size_t got = 0;
        while (readStdin(buffer, sizeof buffer, &got)) {
            pending.append(buffer, got);
            size_t newline;
            while ((newline = pending.find('\n')) != std::string::npos) {
                std::string line = pending.substr(0, newline);
                pending.erase(0, newline + 1);
                if (!line.empty() && line.back() == '\r')
                    line.pop_back();
                if (!self)
                    return;
                const QString text = QString::fromStdString(line);
                QMetaObject::invokeMethod(self, [self, text] {
                    if (self)
                        self->handleLine(text);
                }, Qt::QueuedConnection);
            }
        }
        // Driver went away: do not leave the application running unattended.
        QMetaObject::invokeMethod(qApp, [] { QCoreApplication::quit(); }, Qt::QueuedConnection);
    }).detach();

    std::cout << "@perf {\"event\":\"ready\",\"t\":" << nowMs() << "}" << std::endl;
}

bool Driver::eventFilter(QObject *watched, QEvent *event)
{
    const QEvent::Type type = event->type();
    if (type == QEvent::Paint && watched->isWidgetType()) {
        const double t = nowMs();
        ++m_paintCount;
        if (m_firstPaintMs < 0.0) {
            m_firstPaintMs = t;
            if (m_wait == Wait::FirstPaint) {
                m_wait = Wait::None;
                m_timeout.stop();
                reply({{QStringLiteral("ok"), true}, {QStringLiteral("first_paint_ms"), t}});
            }
        }
        if (m_wait == Wait::Paint) {
            auto *widget = static_cast<QWidget *>(watched);
            if (m_waitWindow.isNull() || widget->window() == m_waitWindow)
                resolvePaint(true);
        } else if (m_wait == Wait::Idle) {
            m_idle.start();
        }
    } else if (type == QEvent::UpdateRequest && m_wait == Wait::Idle) {
        m_idle.start();
    }
    return false;
}

void Driver::handleLine(const QString &line)
{
    QJsonParseError error{};
    const QJsonDocument doc = QJsonDocument::fromJson(line.toUtf8(), &error);
    if (!doc.isObject()) {
        m_id = QJsonValue();
        fail(QStringLiteral("bad command: %1").arg(error.errorString()));
        return;
    }
    m_queue.push_back(doc.object());
    pump();
}

/// Runs queued commands one at a time; a command that waits (for a paint, for idle) holds
/// the queue until its reply has gone out.
void Driver::pump()
{
    while (m_wait == Wait::None && !m_queue.empty()) {
        const QJsonObject cmd = m_queue.front();
        m_queue.pop_front();
        m_id = cmd.value(QStringLiteral("id"));
        m_partial = QJsonObject();
        dispatch(cmd);
    }
}

void Driver::dispatch(const QJsonObject &cmd)
{
    const QString op = cmd.value(QStringLiteral("op")).toString();
    if (op == QLatin1String("ping") || op == QLatin1String("mark")) {
        reply({{QStringLiteral("ok"), true}});
    } else if (op == QLatin1String("find")) {
        doFind(cmd);
    } else if (op == QLatin1String("get")) {
        doGet(cmd);
    } else if (op == QLatin1String("click")) {
        doClick(cmd);
    } else if (op == QLatin1String("key")) {
        doKey(cmd);
    } else if (op == QLatin1String("wheel")) {
        doWheel(cmd);
    } else if (op == QLatin1String("stats")) {
        doStats(cmd);
    } else if (op == QLatin1String("wait_first_frame")) {
        if (m_firstPaintMs >= 0.0) {
            reply({{QStringLiteral("ok"), true}, {QStringLiteral("first_paint_ms"), m_firstPaintMs}});
        } else {
            m_wait = Wait::FirstPaint;
            m_timeout.start(cmd.value(QStringLiteral("timeout_ms")).toInt(30000));
        }
    } else if (op == QLatin1String("wait_idle")) {
        m_wait = Wait::Idle;
        m_idle.start(cmd.value(QStringLiteral("ms")).toInt(300));
        m_timeout.start(cmd.value(QStringLiteral("timeout_ms")).toInt(10000));
    } else if (op == QLatin1String("quit")) {
        reply({{QStringLiteral("ok"), true}});
        QTimer::singleShot(0, qApp, &QCoreApplication::quit);
    } else {
        fail(QStringLiteral("unknown op '%1'").arg(op));
    }
}

void Driver::reply(QJsonObject obj)
{
    for (auto it = m_partial.begin(); it != m_partial.end(); ++it)
        if (!obj.contains(it.key()))
            obj.insert(it.key(), it.value());
    m_partial = QJsonObject();
    obj.insert(QStringLiteral("id"), m_id);
    obj.insert(QStringLiteral("t"), nowMs());
    std::cout << "@perf " << QJsonDocument(obj).toJson(QJsonDocument::Compact).constData() << std::endl;
    if (!m_queue.empty())
        QMetaObject::invokeMethod(this, [this] { pump(); }, Qt::QueuedConnection);
}

void Driver::fail(const QString &message)
{
    reply({{QStringLiteral("ok"), false}, {QStringLiteral("error"), message}});
}

QObject *Driver::find(const QString &path, QString *error) const
{
    const QStringList parts = path.split(QLatin1Char('/'), Qt::SkipEmptyParts);
    if (parts.isEmpty()) {
        *error = QStringLiteral("empty object path");
        return nullptr;
    }
    QObject *current = nullptr;
    const QWidgetList tops = QApplication::topLevelWidgets();
    for (QWidget *top : tops) {
        if (top->objectName() == parts[0]) {
            current = top;
            break;
        }
    }
    for (int i = 0; !current && i < tops.size(); ++i)
        current = tops[i]->findChild<QObject *>(parts[0]);
    for (int i = 1; current && i < parts.size(); ++i)
        current = current->findChild<QObject *>(parts[i]);
    if (!current)
        *error = QStringLiteral("object not found: %1").arg(path);
    return current;
}

QWidget *Driver::findWidget(const QJsonObject &cmd, QString *error) const
{
    QObject *object = find(cmd.value(QStringLiteral("object")).toString(), error);
    if (!object)
        return nullptr;
    auto *widget = qobject_cast<QWidget *>(object);
    if (!widget)
        *error = QStringLiteral("%1 is not a widget").arg(object->objectName());
    return widget;
}

void Driver::doFind(const QJsonObject &cmd)
{
    QString error;
    QObject *object = find(cmd.value(QStringLiteral("object")).toString(), &error);
    if (!object)
        return fail(error);
    QJsonObject out{{QStringLiteral("ok"), true},
                    {QStringLiteral("class"), QString::fromLatin1(object->metaObject()->className())}};
    if (auto *widget = qobject_cast<QWidget *>(object)) {
        const QRect r = widget->geometry();
        out.insert(QStringLiteral("visible"), widget->isVisible());
        out.insert(QStringLiteral("enabled"), widget->isEnabled());
        out.insert(QStringLiteral("geometry"), QJsonArray{r.x(), r.y(), r.width(), r.height()});
    }
    reply(out);
}

void Driver::doGet(const QJsonObject &cmd)
{
    QString error;
    QObject *object = find(cmd.value(QStringLiteral("object")).toString(), &error);
    if (!object)
        return fail(error);
    const QString property = cmd.value(QStringLiteral("property")).toString(QStringLiteral("text"));
    const QVariant value = object->property(property.toUtf8().constData());
    if (!value.isValid())
        return fail(QStringLiteral("no property '%1' on %2").arg(property, object->objectName()));
    reply({{QStringLiteral("ok"), true}, {QStringLiteral("value"), QJsonValue::fromVariant(value)}});
}

void Driver::awaitPaint(QWidget *window, int timeoutMs)
{
    m_wait = Wait::Paint;
    m_waitWindow = window;
    m_timeout.start(timeoutMs);
}

void Driver::resolvePaint(bool painted)
{
    m_timeout.stop();
    m_wait = Wait::None;
    QJsonObject out{{QStringLiteral("ok"), true}, {QStringLiteral("painted"), painted}};
    out.insert(QStringLiteral("paint_ms"), painted ? QJsonValue(nowMs() - m_waitSince) : QJsonValue());
    reply(out);
}

void Driver::doClick(const QJsonObject &cmd)
{
    QString error;
    QWidget *widget = findWidget(cmd, &error);
    if (!widget)
        return fail(error);
    const QPoint local = widget->rect().center();
    const QPointF scene = widget->mapTo(widget->window(), local);
    const QPointF global = widget->mapToGlobal(local);
    const Qt::MouseButton button = Qt::LeftButton;

    m_waitSince = nowMs();
    QMouseEvent press(QEvent::MouseButtonPress, QPointF(local), scene, global, button, button, Qt::NoModifier);
    QCoreApplication::sendEvent(widget, &press);
    QMouseEvent release(QEvent::MouseButtonRelease, QPointF(local), scene, global, button, Qt::NoButton, Qt::NoModifier);
    QCoreApplication::sendEvent(widget, &release);

    m_partial = {{QStringLiteral("dispatch_ms"), nowMs() - m_waitSince},
                 {QStringLiteral("enabled"), widget->isEnabled()}};
    awaitPaint(widget->window(), cmd.value(QStringLiteral("timeout_ms")).toInt(1000));
}

void Driver::doKey(const QJsonObject &cmd)
{
    QString error;
    QWidget *widget = findWidget(cmd, &error);
    if (!widget)
        return fail(error);

    QStringList specs;
    for (const QJsonValue &v : cmd.value(QStringLiteral("keys")).toArray())
        specs << v.toString();
    const QString text = cmd.value(QStringLiteral("text")).toString();
    for (const QChar &c : text)
        specs << QString(c);
    if (specs.isEmpty())
        return fail(QStringLiteral("key: give 'keys' (e.g. [\"Right\", \"Ctrl+A\"]) or 'text'"));

    widget->setFocus(Qt::OtherFocusReason);
    m_waitSince = nowMs();
    for (const QString &spec : specs) {
        const QKeySequence seq(spec);
        int key = 0;
        Qt::KeyboardModifiers mods = Qt::NoModifier;
        if (seq.count() > 0) {
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
            key = seq[0].key();
            mods = seq[0].keyboardModifiers();
#else
            key = seq[0] & ~Qt::KeyboardModifierMask;
            mods = Qt::KeyboardModifiers(seq[0] & Qt::KeyboardModifierMask);
#endif
        }
        if (key == 0 || key == Qt::Key_unknown) {
            if (spec.size() != 1)
                return fail(QStringLiteral("key: cannot parse '%1'").arg(spec));
            key = Qt::Key_unknown;
        }
        const QString keyText = spec.size() == 1 ? spec : QString();
        QKeyEvent press(QEvent::KeyPress, key, mods, keyText);
        QCoreApplication::sendEvent(widget, &press);
        QKeyEvent release(QEvent::KeyRelease, key, mods, keyText);
        QCoreApplication::sendEvent(widget, &release);
    }
    m_partial = {{QStringLiteral("dispatch_ms"), nowMs() - m_waitSince},
                 {QStringLiteral("keys"), specs.size()}};
    awaitPaint(widget->window(), cmd.value(QStringLiteral("timeout_ms")).toInt(1000));
}

void Driver::doWheel(const QJsonObject &cmd)
{
    QString error;
    QWidget *widget = findWidget(cmd, &error);
    if (!widget)
        return fail(error);
    const int delta = cmd.value(QStringLiteral("delta")).toInt(-120);
    const bool horizontal = cmd.value(QStringLiteral("axis")).toString() == QLatin1String("x");
    const QPoint angle = horizontal ? QPoint(delta, 0) : QPoint(0, delta);
    const QPoint local = widget->rect().center();

    m_waitSince = nowMs();
    QWheelEvent wheel(QPointF(local), QPointF(widget->mapToGlobal(local)), QPoint(), angle,
                      Qt::NoButton, Qt::NoModifier, Qt::NoScrollPhase, false);
    QCoreApplication::sendEvent(widget, &wheel);
    m_partial = {{QStringLiteral("dispatch_ms"), nowMs() - m_waitSince},
                 {QStringLiteral("accepted"), wheel.isAccepted()}};
    awaitPaint(widget->window(), cmd.value(QStringLiteral("timeout_ms")).toInt(1000));
}

void Driver::doStats(const QJsonObject &cmd)
{
    std::vector<double> late = m_jankLateness;
    QJsonObject jank{{QStringLiteral("count"), qint64(late.size())},
                     {QStringLiteral("p50"), percentile(late, 0.5)},
                     {QStringLiteral("p95"), percentile(late, 0.95)},
                     {QStringLiteral("max"), late.empty() ? 0.0 : *std::max_element(late.begin(), late.end())},
                     {QStringLiteral("over_50ms"), qint64(std::count_if(late.begin(), late.end(), [](double v) { return v > 50.0; }))}};
    if (cmd.value(QStringLiteral("reset")).toBool())
        m_jankLateness.clear();
    reply({{QStringLiteral("ok"), true},
           {QStringLiteral("jank"), jank},
           {QStringLiteral("paint_count"), m_paintCount},
           {QStringLiteral("first_paint_ms"), m_firstPaintMs}});
}

void Driver::onJankTick()
{
    const double elapsed = m_jankClock.nsecsElapsed() / 1e6;
    m_jankClock.restart();
    m_jankLateness.push_back(std::max(0.0, elapsed - m_jankTimer.interval()));
}

} // namespace

namespace PerfDriver {

void markProcessStart()
{
    g_processClock.start();
}

bool installIfRequested(QCoreApplication &app)
{
    const bool wanted = app.arguments().contains(QStringLiteral("--perf-driver"))
                        || !qEnvironmentVariableIsEmpty("QT_PERF_DRIVER");
    if (!wanted)
        return false;
    if (!g_processClock.isValid())
        g_processClock.start();
    new Driver(app);
    return true;
}

} // namespace PerfDriver
