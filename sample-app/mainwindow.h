#pragma once

#include <QMainWindow>

class QLabel;
class QPushButton;
class QSlider;

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    explicit MainWindow(QWidget *parent = nullptr);

private slots:
    void onSliderChanged(int value);
    void onCountClicked();
    void onResetClicked();

private:
    void updateLabels();

    QSlider *m_slider = nullptr;
    QPushButton *m_countButton = nullptr;
    QPushButton *m_resetButton = nullptr;
    QLabel *m_valueLabel = nullptr;
    QLabel *m_moodLabel = nullptr;
    QLabel *m_clicksLabel = nullptr;
    QLabel *m_statusLabel = nullptr;

    int m_clicks = 0;
};
