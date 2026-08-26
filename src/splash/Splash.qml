import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    signal exitRequested()
    property bool failed: false
    property string displayName: "Player"
    gradient: Gradient {
        GradientStop { position: 0.0; color: "#142b4d" }
        GradientStop { position: 0.48; color: "#0b1423" }
        GradientStop { position: 1.0; color: "#10142c" }
    }
    Column {
        anchors.centerIn: parent
        spacing: 20
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 12
            Label { text: "Welcome back,"; color: "#f5f8ff"; font.pixelSize: 48; font.weight: Font.DemiBold }
            Label { text: root.displayName; color: "#74a7ff"; font.pixelSize: 48; font.weight: Font.DemiBold }
        }
        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.failed ? "Steam needs attention" : "Starting Steam Big Picture Mode"
            color: "#b4c2d7"; font.pixelSize: 22
        }
        Item {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 132; height: 132
            Canvas {
                id: spinner
                anchors.fill: parent
                property real angle: 0
                onPaint: {
                    const ctx = getContext("2d")
                    ctx.reset()
                    const centre = width / 2
                    ctx.lineWidth = 7
                    ctx.lineCap = "round"
                    ctx.strokeStyle = "#21365a"
                    ctx.beginPath()
                    ctx.arc(centre, centre, 48, 0, Math.PI * 2)
                    ctx.stroke()
                    ctx.strokeStyle = "#75a6ff"
                    ctx.beginPath()
                    ctx.arc(centre, centre, 48, angle, angle + Math.PI * 1.35)
                    ctx.stroke()
                }
                NumberAnimation on angle { from: 0; to: Math.PI * 2; duration: 2200; loops: Animation.Infinite; running: !root.failed }
                onAngleChanged: requestPaint()
            }
        }
    }
    Button {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.verticalCenter
        anchors.topMargin: 152
        visible: root.failed
        text: "Exit to desktop"
        onClicked: root.exitRequested()
    }
    Keys.onEscapePressed: {
        if (root.failed) root.exitRequested()
    }
}
