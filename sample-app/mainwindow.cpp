#include "mainwindow.h"

#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QSlider>
#include <QVBoxLayout>
#include <QWidget>

namespace {
constexpr int kDefaultLevel = 50;

QString moodFor(int level)
{
    if (level == 0)
        return QStringLiteral("Silent");
    if (level < 30)
        return QStringLiteral("Quiet");
    if (level < 70)
        return QStringLiteral("Moderate");
    if (level < 100)
        return QStringLiteral("Loud");
    return QStringLiteral("Maximum");
}
} // namespace

MainWindow::MainWindow(QWidget *parent)
    : QMainWindow(parent)
{
    setWindowTitle(tr("Sample App"));
    // Object names are the addresses the UI performance scenarios use (scenarios/*.json).
    setObjectName(QStringLiteral("mainWindow"));

    auto *central = new QWidget(this);
    auto *layout = new QVBoxLayout(central);
    layout->setSpacing(12);
    layout->setContentsMargins(24, 24, 24, 24);

    auto *title = new QLabel(tr("Level control"), central);
    QFont titleFont = title->font();
    titleFont.setPointSize(titleFont.pointSize() + 6);
    titleFont.setBold(true);
    title->setFont(titleFont);
    layout->addWidget(title);

    m_valueLabel = new QLabel(central);
    m_valueLabel->setObjectName(QStringLiteral("valueLabel"));
    layout->addWidget(m_valueLabel);

    m_slider = new QSlider(Qt::Horizontal, central);
    m_slider->setObjectName(QStringLiteral("levelSlider"));
    m_slider->setRange(0, 100);
    m_slider->setValue(kDefaultLevel);
    m_slider->setTickPosition(QSlider::TicksBelow);
    m_slider->setTickInterval(10);
    layout->addWidget(m_slider);

    m_moodLabel = new QLabel(central);
    m_moodLabel->setObjectName(QStringLiteral("moodLabel"));
    m_moodLabel->setAlignment(Qt::AlignCenter);
    QFont moodFont = m_moodLabel->font();
    moodFont.setPointSize(moodFont.pointSize() + 10);
    m_moodLabel->setFont(moodFont);
    layout->addWidget(m_moodLabel);

    auto *buttons = new QHBoxLayout;
    m_countButton = new QPushButton(tr("Count"), central);
    m_resetButton = new QPushButton(tr("Reset"), central);
    m_countButton->setObjectName(QStringLiteral("countButton"));
    m_resetButton->setObjectName(QStringLiteral("resetButton"));
    buttons->addWidget(m_countButton);
    buttons->addWidget(m_resetButton);
    layout->addLayout(buttons);

    m_clicksLabel = new QLabel(central);
    m_clicksLabel->setObjectName(QStringLiteral("clicksLabel"));
    layout->addWidget(m_clicksLabel);

    layout->addStretch();

    m_statusLabel = new QLabel(tr("Ready."), central);
    m_statusLabel->setObjectName(QStringLiteral("statusLabel"));
    m_statusLabel->setStyleSheet(QStringLiteral("color: gray;"));
    layout->addWidget(m_statusLabel);

    setCentralWidget(central);
    resize(420, 320);

    connect(m_slider, &QSlider::valueChanged, this, &MainWindow::onSliderChanged);
    connect(m_countButton, &QPushButton::clicked, this, &MainWindow::onCountClicked);
    connect(m_resetButton, &QPushButton::clicked, this, &MainWindow::onResetClicked);

    updateLabels();
}

void MainWindow::onSliderChanged(int value)
{
    updateLabels();
    m_statusLabel->setText(tr("Level set to %1.").arg(value));
}

void MainWindow::onCountClicked()
{
    ++m_clicks;
    updateLabels();
    m_statusLabel->setText(tr("Counted click number %1.").arg(m_clicks));
}

void MainWindow::onResetClicked()
{
    m_clicks = 0;
    m_slider->setValue(kDefaultLevel);   // emits valueChanged, which refreshes the labels
    updateLabels();
    m_statusLabel->setText(tr("Everything reset."));
}

void MainWindow::updateLabels()
{
    const int level = m_slider->value();
    m_valueLabel->setText(tr("Level: %1 %").arg(level));
    m_moodLabel->setText(moodFor(level));
    m_clicksLabel->setText(tr("Clicks: %1").arg(m_clicks));
    m_resetButton->setEnabled(m_clicks != 0 || level != kDefaultLevel);
}
