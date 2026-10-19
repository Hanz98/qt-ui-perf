#include "perfdriver.h"

#include <QApplication>
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QEvent>
#include <QGuiApplication>
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
#include <QWindow>

#ifdef PERFDRIVER_HAVE_QUICK
#include <QQuickItem>
#include <QQuickWindow>
#endif

#include <algorithm>
#include <cerrno>
#include <deque>
#include <functional>
#include <iostream>
#include <map>
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

QString className(const QObject *object)
{
    return QString::fromLatin1(object->metaObject()->className());
}

/// The "text" of an object for tree dumps and Class=text addressing: its text property,
/// else accessibleName, else title (windows). Empty when it has none.
QString textOf(const QObject *object)
{
    for (const char *name : {"text", "accessibleName", "title"}) {
        const QVariant v = object->property(name);
        if (v.isValid() && v.canConvert<QString>()) {
            const QString s = v.toString();
            if (!s.isEmpty())
                return s;
        }
    }
    return QString();
}

/// Class-selector match: "Button" matches an object whose class (or any base class) is
/// Button, QButton, QQuickButton, or a QML type derived from one of those (Button_QMLTYPE_7).
bool classMatches(const QObject *object, const QString &cls)
{
    const QString quick = QStringLiteral("QQuick") + cls;
    const QString widget = QStringLiteral("Q") + cls;
    for (const QMetaObject *mo = object->metaObject(); mo; mo = mo->superClass()) {
        QString name = QString::fromLatin1(mo->className());
        const int qml = name.indexOf(QLatin1String("_QML"));
        if (qml > 0)
            name.truncate(qml);
        if (name == cls || name == quick || name == widget)
            return true;
    }
    return false;
}

/// A path segment matches by objectName, or as a selector "Class" / "Class=text".
bool segmentMatches(const QObject *object, const QString &segment)
{
    if (object->objectName() == segment)
        return true;
    const int eq = segment.indexOf(QLatin1Char('='));
    const QString cls = eq < 0 ? segment : segment.left(eq);
    if (cls.isEmpty() || !classMatches(object, cls))
        return false;
    return eq < 0 || textOf(object) == segment.mid(eq + 1);
}

/// Children of an object as the seam sees them: the visual item tree for Qt Quick items
/// and windows, the QObject children otherwise.
QList<QObject *> childrenOf(QObject *object)
{
    QList<QObject *> out;
#ifdef PERFDRIVER_HAVE_QUICK
    if (auto *window = qobject_cast<QQuickWindow *>(object)) {
        if (window->contentItem())
            out << window->contentItem();
        return out;
    }
    if (auto *item = qobject_cast<QQuickItem *>(object)) {
        const QList<QQuickItem *> items = item->childItems();
        for (QQuickItem *child : items)
            out << child;
        return out;
    }
#endif
    const QObjectList &children = object->children();
    for (QObject *child : children)
        out << child;
    return out;
}

/// Depth-first walk; visit(object, depth) returns false to stop.
bool walk(QObject *root, int depth, int maxDepth, const std::function<bool(QObject *, int)> &visit)
{
    if (!visit(root, depth))
        return false;
    if (depth >= maxDepth)
        return true;
    const QList<QObject *> children = childrenOf(root);
    for (QObject *child : children)
        if (!walk(child, depth + 1, maxDepth, visit))
            return false;
    return true;
}

/// First descendant of root (root itself excluded) for which pred holds.
template <typename Pred> QObject *findDescendant(QObject *root, Pred pred)
{
    QObject *found = nullptr;
    walk(root, 0, 64, [&](QObject *object, int depth) {
        if (depth > 0 && pred(object)) {
            found = object;
            return false;
        }
        return true;
    });
    return found;
}

QObject *findByName(QObject *root, const QString &name)
{
    return findDescendant(root, [&](QObject *o) { return o->objectName() == name; });
}

QObject *findBySelector(QObject *root, const QString &segment)
{
    return findDescendant(root, [&](QObject *o) { return segmentMatches(o, segment); });
}

#ifdef PERFDRIVER_HAVE_QUICK
QList<QQuickWindow *> quickWindows()
{
    QList<QQuickWindow *> out;
    const QWindowList windows = QGuiApplication::topLevelWindows();
    for (QWindow *w : windows)
        if (auto *qw = qobject_cast<QQuickWindow *>(w))
            out << qw;
    return out;
}

QJsonArray itemGeometry(const QQuickItem *item)
{
    const QRectF r = item->mapRectToScene(QRectF(0, 0, item->width(), item->height()));
    return QJsonArray{qRound(r.x()), qRound(r.y()), qRound(r.width()), qRound(r.height())};
}

/// Per-QQuickWindow frame record: timestamps of frameSwapped (and afterRendering as the
/// fallback for render loops that never swap) since the last stats reset.
struct FrameRecord
{
    QString name;
    QString cls;
    double firstFrameMs = -1.0;
    std::vector<double> swapped;
    std::vector<double> rendered;
};
#endif

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
    void doTree(const QJsonObject &cmd);
    void doClick(const QJsonObject &cmd);
    void doKey(const QJsonObject &cmd);
    void doWheel(const QJsonObject &cmd);
    void doStats(const QJsonObject &cmd);

    void awaitPaint(QObject *window, int timeoutMs);
    void resolvePaint(bool painted, double at = -1.0);
    void noteFirstPaint(double t);
    void onJankTick();

    std::deque<QJsonObject> m_queue; // commands received while one was still in flight
    QJsonValue m_id;                 // id of the command in flight
    Wait m_wait = Wait::None;
    QPointer<QObject> m_waitWindow;  // top-level whose repaint we wait for (null = any)
    double m_waitSince = 0.0;
    QJsonObject m_partial;           // reply fields collected before the wait finished
    QTimer m_timeout;
    QTimer m_idle;

    double m_firstPaintMs = -1.0;
    qint64 m_paintCount = 0;

    QTimer m_jankTimer;
    QElapsedTimer m_jankClock;
    std::vector<double> m_jankLateness;

#ifdef PERFDRIVER_HAVE_QUICK
    QQuickItem *findQuickItem(const QJsonObject &cmd, QString *error, QQuickWindow **window) const;
    void attachQuickWindow(QQuickWindow *window);
    void onQuickFrame(QObject *window, double t, bool swapped);
    QJsonArray frameStats() const;

    std::map<QObject *, FrameRecord> m_frames;   // keyed by the window; entries removed on destroyed()
#endif
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

#ifdef PERFDRIVER_HAVE_QUICK
    // Windows that exist already; later ones are caught by the event filter.
    const QList<QQuickWindow *> windows = quickWindows();
    for (QQuickWindow *w : windows)
        attachQuickWindow(w);
#endif

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
        noteFirstPaint(t);
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
#ifdef PERFDRIVER_HAVE_QUICK
    else if ((type == QEvent::Show || type == QEvent::Expose || type == QEvent::PlatformSurface)
             && watched->isWindowType()) {
        if (auto *window = qobject_cast<QQuickWindow *>(watched))
            attachQuickWindow(window);
    }
#endif
    return false;
}

void Driver::noteFirstPaint(double t)
{
    if (m_firstPaintMs >= 0.0)
        return;
    m_firstPaintMs = t;
    if (m_wait == Wait::FirstPaint) {
        m_wait = Wait::None;
        m_timeout.stop();
        reply({{QStringLiteral("ok"), true}, {QStringLiteral("first_paint_ms"), t}});
    }
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
    } else if (op == QLatin1String("tree")) {
        doTree(cmd);
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

/// Resolves "name", "parent/child", "Class" or "Class=text" (see segmentMatches). The first
/// segment is searched among all top-level widgets and their descendants, then among the
/// Qt Quick windows and their item trees; each further segment among the descendants of the
/// previous match. A plain objectName always wins over a class selector.
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
#ifdef PERFDRIVER_HAVE_QUICK
    const QList<QQuickWindow *> windows = quickWindows();
    for (int i = 0; !current && i < windows.size(); ++i) {
        if (windows[i]->objectName() == parts[0])
            current = windows[i];
        else if (QObject *item = findByName(windows[i], parts[0]))       // the visual item tree
            current = item;
        else
            current = windows[i]->findChild<QObject *>(parts[0]);   // non-item QML objects (Timer, models)
    }
#endif
    for (int i = 0; !current && i < tops.size(); ++i)
        current = findBySelector(tops[i], parts[0]);
#ifdef PERFDRIVER_HAVE_QUICK
    for (int i = 0; !current && i < windows.size(); ++i)
        current = findBySelector(windows[i], parts[0]);
#endif
    for (int i = 1; current && i < parts.size(); ++i) {
        QObject *next = current->findChild<QObject *>(parts[i]);
        if (!next)
            next = findByName(current, parts[i]);
        if (!next)
            next = findBySelector(current, parts[i]);
        current = next;
    }
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

#ifdef PERFDRIVER_HAVE_QUICK
/// Like findWidget for Qt Quick items. Leaves *error empty when the object is not an item
/// at all (so the caller can report the Widgets error instead).
QQuickItem *Driver::findQuickItem(const QJsonObject &cmd, QString *error, QQuickWindow **window) const
{
    QObject *object = find(cmd.value(QStringLiteral("object")).toString(), error);
    if (!object)
        return nullptr;
    auto *item = qobject_cast<QQuickItem *>(object);
    if (!item) {
        *error = QStringLiteral("%1 is neither a widget nor a Qt Quick item (%2)")
                     .arg(object->objectName(), className(object));
        return nullptr;
    }
    *window = item->window();
    if (!*window) {
        *error = QStringLiteral("%1 is not in a window").arg(object->objectName());
        return nullptr;
    }
    return item;
}

void Driver::attachQuickWindow(QQuickWindow *window)
{
    if (m_frames.count(window))
        return;
    FrameRecord &rec = m_frames[window];
    rec.name = window->objectName();
    rec.cls = className(window);
    // Both signals come from the render thread (threaded loop) or the main thread (basic /
    // software loop); the timestamp is taken right there and the bookkeeping is queued to
    // the main thread. frameSwapped is the frame-pacing signal; afterRendering is the
    // fallback for loops that never report a swap.
    QObject *key = window;
    connect(window, &QQuickWindow::frameSwapped, this, [this, key] {
        const double t = nowMs();
        QMetaObject::invokeMethod(this, [this, key, t] { onQuickFrame(key, t, true); }, Qt::QueuedConnection);
    }, Qt::DirectConnection);
    connect(window, &QQuickWindow::afterRendering, this, [this, key] {
        const double t = nowMs();
        QMetaObject::invokeMethod(this, [this, key, t] { onQuickFrame(key, t, false); }, Qt::QueuedConnection);
    }, Qt::DirectConnection);
    connect(window, &QObject::destroyed, this, [this, key] { m_frames.erase(key); });
}

void Driver::onQuickFrame(QObject *window, double t, bool swapped)
{
    auto it = m_frames.find(window);
    if (it == m_frames.end())
        return;
    FrameRecord &rec = it->second;
    (swapped ? rec.swapped : rec.rendered).push_back(t);
    if (rec.firstFrameMs < 0.0)
        rec.firstFrameMs = t;
    if (!swapped)   // one frame = one afterRendering; frameSwapped follows it
        ++m_paintCount;
    noteFirstPaint(t);
    if (m_wait == Wait::Paint) {
        if (m_waitWindow.isNull() || m_waitWindow == window)
            resolvePaint(true, t);
    } else if (m_wait == Wait::Idle) {
        m_idle.start();
    }
}

QJsonArray Driver::frameStats() const
{
    QJsonArray out;
    for (const auto &entry : m_frames) {
        const FrameRecord &rec = entry.second;
        const bool fallback = rec.swapped.empty() && !rec.rendered.empty();
        const std::vector<double> &stamps = fallback ? rec.rendered : rec.swapped;
        std::vector<double> intervals;
        for (size_t i = 1; i < stamps.size(); ++i)
            intervals.push_back(stamps[i] - stamps[i - 1]);
        QJsonObject w{{QStringLiteral("window"), rec.name.isEmpty() ? rec.cls : rec.name},
                      {QStringLiteral("class"), rec.cls},
                      {QStringLiteral("source"), fallback ? QStringLiteral("afterRendering") : QStringLiteral("frameSwapped")},
                      {QStringLiteral("count"), qint64(stamps.size())},
                      {QStringLiteral("first_frame_ms"), rec.firstFrameMs},
                      {QStringLiteral("interval_p50"), percentile(intervals, 0.5)},
                      {QStringLiteral("interval_p95"), percentile(intervals, 0.95)},
                      {QStringLiteral("interval_max"), intervals.empty() ? 0.0 : *std::max_element(intervals.begin(), intervals.end())}};
        const double span = stamps.size() > 1 ? stamps.back() - stamps.front() : 0.0;
        w.insert(QStringLiteral("fps"), span > 0.0 ? QJsonValue(double(stamps.size() - 1) * 1000.0 / span) : QJsonValue());
        out.append(w);
    }
    return out;
}
#endif

void Driver::doFind(const QJsonObject &cmd)
{
    QString error;
    QObject *object = find(cmd.value(QStringLiteral("object")).toString(), &error);
    if (!object)
        return fail(error);
    QJsonObject out{{QStringLiteral("ok"), true},
                    {QStringLiteral("class"), className(object)},
                    {QStringLiteral("name"), object->objectName()}};
    if (auto *widget = qobject_cast<QWidget *>(object)) {
        const QRect r = widget->geometry();
        out.insert(QStringLiteral("visible"), widget->isVisible());
        out.insert(QStringLiteral("enabled"), widget->isEnabled());
        out.insert(QStringLiteral("geometry"), QJsonArray{r.x(), r.y(), r.width(), r.height()});
    }
#ifdef PERFDRIVER_HAVE_QUICK
    else if (auto *item = qobject_cast<QQuickItem *>(object)) {
        out.insert(QStringLiteral("visible"), item->isVisible());
        out.insert(QStringLiteral("enabled"), item->isEnabled());
        out.insert(QStringLiteral("geometry"), itemGeometry(item));
        if (QQuickWindow *w = item->window())
            out.insert(QStringLiteral("window"), w->objectName().isEmpty() ? className(w) : w->objectName());
    } else if (auto *window = qobject_cast<QWindow *>(object)) {
        const QRect r = window->geometry();
        out.insert(QStringLiteral("visible"), window->isVisible());
        out.insert(QStringLiteral("geometry"), QJsonArray{r.x(), r.y(), r.width(), r.height()});
    }
#endif
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

/// Dumps the object tree so scenario authors can discover addresses: every top-level widget
/// (or Qt Quick window) and its descendants as a flat, depth-annotated list. Non-visual
/// QObject children are listed only when they carry an objectName.
void Driver::doTree(const QJsonObject &cmd)
{
    const int maxDepth = cmd.value(QStringLiteral("depth")).toInt(8);
    const int maxNodes = cmd.value(QStringLiteral("max")).toInt(5000);
    const QString only = cmd.value(QStringLiteral("window")).toString();

    QList<QObject *> roots;
    const QWidgetList tops = QApplication::topLevelWidgets();
    for (QWidget *top : tops)
        roots << top;
#ifdef PERFDRIVER_HAVE_QUICK
    const QList<QQuickWindow *> windows = quickWindows();
    for (QQuickWindow *w : windows)
        roots << w;
#endif
    if (!only.isEmpty()) {
        QList<QObject *> matching;
        for (QObject *root : roots)
            if (segmentMatches(root, only))
                matching << root;
        if (matching.isEmpty())
            return fail(QStringLiteral("window not found: %1").arg(only));
        roots = matching;
    }

    QJsonArray nodes;
    bool truncated = false;
    for (QObject *root : roots) {
        walk(root, 0, maxDepth, [&](QObject *object, int depth) {
            if (nodes.size() >= maxNodes) {
                truncated = true;
                return false;
            }
            QJsonObject node{{QStringLiteral("depth"), depth},
                             {QStringLiteral("class"), className(object)},
                             {QStringLiteral("name"), object->objectName()}};
            if (auto *widget = qobject_cast<QWidget *>(object)) {
                const QRect r = widget->geometry();
                node.insert(QStringLiteral("visible"), widget->isVisible());
                node.insert(QStringLiteral("geometry"), QJsonArray{r.x(), r.y(), r.width(), r.height()});
            }
#ifdef PERFDRIVER_HAVE_QUICK
            else if (auto *item = qobject_cast<QQuickItem *>(object)) {
                node.insert(QStringLiteral("visible"), item->isVisible());
                node.insert(QStringLiteral("geometry"), itemGeometry(item));
            }
#endif
            else if (auto *window = qobject_cast<QWindow *>(object)) {
                const QRect r = window->geometry();
                node.insert(QStringLiteral("visible"), window->isVisible());
                node.insert(QStringLiteral("geometry"), QJsonArray{r.x(), r.y(), r.width(), r.height()});
            } else if (object->objectName().isEmpty()) {
                return true;   // anonymous helper object: skip it, but keep walking its children
            }
            const QString text = textOf(object);
            if (!text.isEmpty())
                node.insert(QStringLiteral("text"), text.left(60));
            nodes.append(node);
            return true;
        });
    }
    reply({{QStringLiteral("ok"), true},
           {QStringLiteral("count"), nodes.size()},
           {QStringLiteral("truncated"), truncated},
           {QStringLiteral("nodes"), nodes}});
}

void Driver::awaitPaint(QObject *window, int timeoutMs)
{
    m_wait = Wait::Paint;
    m_waitWindow = window;
    m_timeout.start(timeoutMs);
}

void Driver::resolvePaint(bool painted, double at)
{
    m_timeout.stop();
    m_wait = Wait::None;
    QJsonObject out{{QStringLiteral("ok"), true}, {QStringLiteral("painted"), painted}};
    const double end = at >= 0.0 ? at : nowMs();
    out.insert(QStringLiteral("paint_ms"), painted ? QJsonValue(end - m_waitSince) : QJsonValue());
    reply(out);
}

void Driver::doClick(const QJsonObject &cmd)
{
    QString error;
    QWidget *widget = findWidget(cmd, &error);
#ifdef PERFDRIVER_HAVE_QUICK
    if (!widget) {
        QString quickError;
        QQuickWindow *window = nullptr;
        if (QQuickItem *item = findQuickItem(cmd, &quickError, &window)) {
            const QPointF scene = item->mapToScene(QPointF(item->width() / 2, item->height() / 2));
            const QPointF global = window->mapToGlobal(scene.toPoint());
            const Qt::MouseButton button = Qt::LeftButton;

            m_waitSince = nowMs();
            QMouseEvent press(QEvent::MouseButtonPress, scene, scene, global, button, button, Qt::NoModifier);
            press.setTimestamp(quint64(m_waitSince));
            QCoreApplication::sendEvent(window, &press);
            QMouseEvent release(QEvent::MouseButtonRelease, scene, scene, global, button, Qt::NoButton, Qt::NoModifier);
            release.setTimestamp(quint64(nowMs()));
            QCoreApplication::sendEvent(window, &release);

            m_partial = {{QStringLiteral("dispatch_ms"), nowMs() - m_waitSince},
                         {QStringLiteral("enabled"), item->isEnabled()},
                         {QStringLiteral("accepted"), press.isAccepted()}};
            awaitPaint(window, cmd.value(QStringLiteral("timeout_ms")).toInt(1000));
            return;
        }
        if (!quickError.isEmpty())
            error = quickError;
    }
#endif
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
#ifdef PERFDRIVER_HAVE_QUICK
    QQuickItem *item = nullptr;
    QQuickWindow *quickWindow = nullptr;
    if (!widget) {
        QString quickError;
        item = findQuickItem(cmd, &quickError, &quickWindow);
        if (!item && !quickError.isEmpty())
            error = quickError;
    }
    if (!widget && !item)
        return fail(error);
#else
    if (!widget)
        return fail(error);
#endif

    QStringList specs;
    for (const QJsonValue &v : cmd.value(QStringLiteral("keys")).toArray())
        specs << v.toString();
    const QString text = cmd.value(QStringLiteral("text")).toString();
    for (const QChar &c : text)
        specs << QString(c);
    if (specs.isEmpty())
        return fail(QStringLiteral("key: give 'keys' (e.g. [\"Right\", \"Ctrl+A\"]) or 'text'"));

    // Where the key events go: the widget itself, or for Qt Quick the window (which routes
    // them to its active focus item). If the item could not take active focus (the window
    // is not active on this platform plugin) they go straight to the item instead.
    QObject *target = widget;
    QObject *window = widget ? widget->window() : nullptr;
    bool focused = true;
    if (widget) {
        widget->setFocus(Qt::OtherFocusReason);
    }
#ifdef PERFDRIVER_HAVE_QUICK
    else {
        if (!quickWindow->isActive())
            quickWindow->requestActivate();
        item->forceActiveFocus();
        focused = item->hasActiveFocus();
        target = focused ? static_cast<QObject *>(quickWindow) : static_cast<QObject *>(item);
        window = quickWindow;
    }
#endif
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
        QCoreApplication::sendEvent(target, &press);
        QKeyEvent release(QEvent::KeyRelease, key, mods, keyText);
        QCoreApplication::sendEvent(target, &release);
    }
    m_partial = {{QStringLiteral("dispatch_ms"), nowMs() - m_waitSince},
                 {QStringLiteral("keys"), specs.size()}};
    if (!widget)
        m_partial.insert(QStringLiteral("focused"), focused);
    awaitPaint(window, cmd.value(QStringLiteral("timeout_ms")).toInt(1000));
}

void Driver::doWheel(const QJsonObject &cmd)
{
    QString error;
    QWidget *widget = findWidget(cmd, &error);
    const int delta = cmd.value(QStringLiteral("delta")).toInt(-120);
    const bool horizontal = cmd.value(QStringLiteral("axis")).toString() == QLatin1String("x");
    const QPoint angle = horizontal ? QPoint(delta, 0) : QPoint(0, delta);
#ifdef PERFDRIVER_HAVE_QUICK
    if (!widget) {
        QString quickError;
        QQuickWindow *window = nullptr;
        if (QQuickItem *item = findQuickItem(cmd, &quickError, &window)) {
            const QPointF scene = item->mapToScene(QPointF(item->width() / 2, item->height() / 2));
            m_waitSince = nowMs();
            QWheelEvent wheel(scene, QPointF(window->mapToGlobal(scene.toPoint())), QPoint(), angle,
                              Qt::NoButton, Qt::NoModifier, Qt::NoScrollPhase, false);
            wheel.setTimestamp(quint64(m_waitSince));
            QCoreApplication::sendEvent(window, &wheel);
            m_partial = {{QStringLiteral("dispatch_ms"), nowMs() - m_waitSince},
                         {QStringLiteral("accepted"), wheel.isAccepted()}};
            awaitPaint(window, cmd.value(QStringLiteral("timeout_ms")).toInt(1000));
            return;
        }
        if (!quickError.isEmpty())
            error = quickError;
    }
#endif
    if (!widget)
        return fail(error);
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
    QJsonObject out{{QStringLiteral("ok"), true},
                    {QStringLiteral("jank"), jank},
                    {QStringLiteral("paint_count"), m_paintCount},
                    {QStringLiteral("first_paint_ms"), m_firstPaintMs}};
#ifdef PERFDRIVER_HAVE_QUICK
    out.insert(QStringLiteral("frames"), frameStats());
#else
    out.insert(QStringLiteral("frames"), QJsonArray());
#endif
    if (cmd.value(QStringLiteral("reset")).toBool()) {
        m_jankLateness.clear();
#ifdef PERFDRIVER_HAVE_QUICK
        for (auto &entry : m_frames) {
            entry.second.swapped.clear();
            entry.second.rendered.clear();
        }
#endif
    }
    reply(out);
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
