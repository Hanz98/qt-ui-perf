// The Qt Quick twin of sample-app/: same controls, same texts, same objectNames, so
// scenarios/sample_app_quick.json mirrors scenarios/sample_app.json.
// Versioned imports so the same file loads on Qt 5.15 and Qt 6.
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

ApplicationWindow {
    id: root
    // Object names are the addresses the UI performance scenarios use (scenarios/*.json).
    objectName: "mainWindow"
    title: "Sample App (Quick)"
    width: 420
    height: 320
    visible: true

    readonly property int defaultLevel: 50
    property int clicks: 0
    property string status: "Ready."

    Component.onCompleted: status = "Ready."   // the slider's initial value fires onValueChanged

    function moodFor(level) {
        if (level === 0)
            return "Silent"
        if (level < 30)
            return "Quiet"
        if (level < 70)
            return "Moderate"
        if (level < 100)
            return "Loud"
        return "Maximum"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 12

        Label {
            text: "Level control"
            font.pointSize: Qt.application.font.pointSize + 6
            font.bold: true
        }

        Label {
            objectName: "valueLabel"
            text: "Level: " + Math.round(levelSlider.value) + " %"
        }

        Slider {
            id: levelSlider
            objectName: "levelSlider"
            Layout.fillWidth: true
            from: 0
            to: 100
            stepSize: 1
            value: root.defaultLevel
            wheelEnabled: true
            onValueChanged: root.status = "Level set to " + Math.round(value) + "."
        }

        Label {
            objectName: "moodLabel"
            Layout.alignment: Qt.AlignHCenter
            text: root.moodFor(Math.round(levelSlider.value))
            font.pointSize: Qt.application.font.pointSize + 10
        }

        RowLayout {
            Layout.fillWidth: true

            Button {
                objectName: "countButton"
                Layout.fillWidth: true
                text: "Count"
                onClicked: {
                    root.clicks += 1
                    root.status = "Counted click number " + root.clicks + "."
                }
            }

            Button {
                objectName: "resetButton"
                Layout.fillWidth: true
                text: "Reset"
                enabled: root.clicks !== 0 || Math.round(levelSlider.value) !== root.defaultLevel
                onClicked: {
                    root.clicks = 0
                    levelSlider.value = root.defaultLevel   // triggers onValueChanged first
                    root.status = "Everything reset."
                }
            }
        }

        Label {
            objectName: "clicksLabel"
            text: "Clicks: " + root.clicks
        }

        Item {
            Layout.fillHeight: true
        }

        Label {
            objectName: "statusLabel"
            text: root.status
            color: "gray"
        }
    }
}
