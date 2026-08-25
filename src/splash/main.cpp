#include <QGuiApplication>
#include <QElapsedTimer>
#include <QFile>
#include <QProcess>
#include <QQuickView>
#include <QQuickItem>
#include <QTimer>
#include <LayerShellQt/Window>
#include <pwd.h>
#include <unistd.h>

static bool bigPictureVisible()
{
    const QString runtimeDir = QString::fromUtf8(qgetenv("XDG_RUNTIME_DIR"));
    if (!runtimeDir.isEmpty() && QFile::exists(runtimeDir + QStringLiteral("/ludus-steam-ready"))) {
        return true;
    }
    QProcess wmctrl;
    wmctrl.start(QStringLiteral("/usr/bin/wmctrl"), {QStringLiteral("-lx")});
    if (!wmctrl.waitForFinished(1500)) {
        return false;
    }
    const QByteArray windows = wmctrl.readAllStandardOutput().toLower();
    return windows.contains("steam") && (windows.contains("big picture") || windows.contains("gamepadui"));
}

static QString displayName()
{
    const passwd *account = getpwuid(getuid());
    if (!account) {
        return QStringLiteral("Player");
    }
    const QString name = QString::fromLocal8Bit(account->pw_gecos).section(QLatin1Char(','), 0, 0).trimmed();
    return name.isEmpty() ? QString::fromLocal8Bit(account->pw_name) : name;
}

int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    QQuickView view;
    view.setResizeMode(QQuickView::SizeRootObjectToView);
    view.setSource(QUrl::fromLocalFile(QStringLiteral("/usr/local/lib/ludus/Splash.qml")));
    view.rootObject()->setProperty("displayName", displayName());
    auto *layerSurface = LayerShellQt::Window::get(&view);
    LayerShellQt::Window::Anchors anchors;
    anchors.setFlag(LayerShellQt::Window::AnchorTop);
    anchors.setFlag(LayerShellQt::Window::AnchorBottom);
    anchors.setFlag(LayerShellQt::Window::AnchorLeft);
    anchors.setFlag(LayerShellQt::Window::AnchorRight);
    layerSurface->setAnchors(anchors);
    layerSurface->setLayer(LayerShellQt::Window::LayerOverlay);
    layerSurface->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityExclusive);
    // Qt's showFullScreen() uses Plasma's work area, which excludes panels.
    // A layer-shell surface must instead be explicitly sized to the physical
    // output so it extends behind the taskbar as well.
    const QRect outputGeometry = view.screen()->geometry();
    view.setGeometry(outputGeometry);
    layerSurface->setDesiredSize(outputGeometry.size());
    view.show();
    QProcess::startDetached(QStringLiteral("/usr/local/lib/ludus/ludus-steam"));

    auto *stableSince = new qint64(0);
    auto *elapsed = new QElapsedTimer;
    elapsed->start();
    auto *timer = new QTimer(&app);
    QObject::connect(timer, &QTimer::timeout, &app, [&] {
        if (bigPictureVisible()) {
            if (*stableSince == 0) *stableSince = elapsed->elapsed();
            if (elapsed->elapsed() - *stableSince >= 1500) app.quit();
        } else {
            *stableSince = 0;
        }
        if (elapsed->elapsed() >= 90000 && view.rootObject()) {
            view.rootObject()->setProperty("failed", true);
        }
    });
    timer->start(500);
    return app.exec();
}
