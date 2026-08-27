import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.login as PlasmaLogin

Item {
    id: root
    anchors.fill: parent
    property int selectedIndex: 0
    property bool powerFocused: false
    property int powerIndex: 0
    property bool loggingIn: false
    property string message: "Who’s playing?"
    readonly property int cardWidth: 250
    readonly property int cardHeight: 286
    readonly property int count: list.count
    focus: true
    function move(delta) {
        if (loggingIn) return
        if (powerFocused) powerIndex = (powerIndex + delta + 2) % 2
        else if (count > 0) selectedIndex = (selectedIndex + delta + count) % count
    }
    function select() {
        if (loggingIn || count === 0) return
        // The greeter must hand its compositor to Plasma at this point.  Keep
        // that short transition intentionally blank; the single Ludus cover
        // appears once the user's compositor is available.
        loggingIn = true
        // SessionType::Wayland is 1 in the Plasma Login greeter protocol.
        PlasmaLogin.GreeterState.handleLoginRequest(list.currentItem.loginName, "", 1, "ludus.desktop")
    }
    function activate() {
        if (powerFocused) {
            if (powerIndex === 0) PlasmaLogin.SessionManagement.requestShutdown(PlasmaLogin.SessionManagement.ConfirmationMode.Skip)
            else PlasmaLogin.SessionManagement.requestReboot(PlasmaLogin.SessionManagement.ConfirmationMode.Skip)
        } else select()
    }
    // The MQTT service can place one validated, root-owned request in the
    // greeter bridge.  It is still checked against this filtered UserModel,
    // so a broker command can never login an account Ludus does not display.
    Timer {
        interval: 500
        running: !root.loggingIn
        repeat: true
        onTriggered: {
            const requested = PlasmaLogin.RemoteLogin.takeRequestedUser()
            if (!requested.length) return
            const index = PlasmaLogin.UserModel.indexOfData(requested, PlasmaLogin.UserModel.NameRole)
            if (index < 0) return
            root.selectedIndex = index
            // Do not depend on ListView.currentItem updating between this
            // timer tick and the login request; the validated model name is
            // the actual account Plasma Login should start.
            root.loggingIn = true
            PlasmaLogin.GreeterState.handleLoginRequest(requested, "", 1, "ludus.desktop")
        }
    }
    Keys.onLeftPressed: move(-1)
    Keys.onRightPressed: move(1)
    Keys.onDownPressed: { if (!loggingIn) powerFocused = true }
    Keys.onUpPressed: { if (!loggingIn) powerFocused = false }
    Keys.onReturnPressed: activate()
    Keys.onEnterPressed: activate()
    Rectangle { anchors.fill: parent; color: root.loggingIn ? "black" : "#0b1220" }
    Rectangle {
        anchors.fill: parent
        visible: !root.loggingIn
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#142b4d" }
            GradientStop { position: 0.48; color: "#0b1423" }
            GradientStop { position: 1.0; color: "#10142c" }
        }
    }
    ColumnLayout {
        anchors.centerIn: parent; spacing: 22; visible: !root.loggingIn
        Column {
            Layout.alignment: Qt.AlignHCenter
            QQC2.Label { anchors.horizontalCenter: parent.horizontalCenter; text: root.message; color: "#f5f8ff"; font.pixelSize: 50; font.weight: Font.DemiBold }
        }
        ListView {
            id: list
            // Make the strip as wide as its cards: one card is centered, while
            // the gap between an even number of cards lands on screen centre.
            Layout.preferredWidth: Math.min(root.width * .82, Math.max(root.cardWidth, root.count * root.cardWidth + Math.max(0, root.count - 1) * 28)); Layout.preferredHeight: root.cardHeight
            orientation: ListView.Horizontal; spacing: 28; model: PlasmaLogin.UserModel; interactive: false; currentIndex: root.selectedIndex
            // For the usual two or three-player Ludus setup, preserve the
            // cards' positions and move only the selection treatment.
            highlightRangeMode: root.count < 4 ? ListView.NoHighlightRange : ListView.StrictlyEnforceRange
            delegate: Item {
                id: card
                required property string name
                required property string realName
                required property string icon
                required property int index
                property string loginName: name
                property bool selected: root.selectedIndex === index
                width: root.cardWidth; height: root.cardHeight
                Item {
                    anchors.fill: parent; anchors.margins: -8
                    visible: card.selected
                    Rectangle {
                        anchors.fill: parent; radius: 30; color: "transparent"
                        border.width: 2; border.color: "#9ed9ff"; opacity: .5
                        SequentialAnimation on opacity {
                            running: card.selected
                            loops: Animation.Infinite
                            NumberAnimation { to: .12; duration: 850; easing.type: Easing.InOutSine }
                            NumberAnimation { to: .62; duration: 850; easing.type: Easing.InOutSine }
                        }
                    }
                }
                Rectangle { anchors.fill: parent; radius: 22; color: card.selected ? "#1d3552" : "#172235"; border.width: card.selected ? 3 : 1; border.color: card.selected ? "#79caff" : "#30445d" }
                Rectangle { id: circle; width: 166; height: 166; radius: width/2; anchors.horizontalCenter: parent.horizontalCenter; y: 25; color: "#36516f"; clip: true
                    Image { anchors.fill: parent; source: card.icon; fillMode: Image.PreserveAspectCrop; asynchronous: true }
                }
                QQC2.Label { anchors.horizontalCenter: parent.horizontalCenter; y: 211; width: parent.width-20; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: card.realName.length ? card.realName : card.name; color: "#75a6ff"; font.pixelSize: 25; font.weight: Font.DemiBold }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    hoverEnabled: true
                    onEntered: {
                        if (root.loggingIn) return
                        root.powerFocused = false
                        root.selectedIndex = card.index
                    }
                    onClicked: {
                        root.selectedIndex = card.index
                        root.select()
                    }
                }
            }
        }
        Row {
            Layout.alignment: Qt.AlignHCenter
            spacing: 14
            topPadding: 4
            Repeater {
                model: ["Shut down", "Restart"]
                delegate: Rectangle {
                    required property string modelData
                    required property int index
                    width: 144; height: 44; radius: 12
                    color: root.powerFocused && root.powerIndex === index ? "#4a3850" : "#202b3c"
                    border.width: root.powerFocused && root.powerIndex === index ? 3 : 1
                    border.color: root.powerFocused && root.powerIndex === index ? "#f5a2c8" : "#40536d"
                    QQC2.Label { anchors.centerIn: parent; text: (index === 0 ? "⏻  " : "↻  ") + modelData; color: "white"; font.pixelSize: 16; font.weight: Font.DemiBold }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.powerFocused = true
                            root.powerIndex = index
                            root.activate()
                        }
                    }
                }
            }
        }
    }
    QQC2.Label {
        visible: !root.loggingIn
        anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.rightMargin: 34; anchors.bottomMargin: 25
        text: root.powerFocused ? "←  →  Choose power option    A  Confirm    ↑  Players" : "←  →  Choose player    A  Select    ↓  Power"
        color: "#8495ad"; font.pixelSize: 14
    }
    Connections { target: PlasmaLogin.Authenticator
        function onLoginFailed() { root.loggingIn = false; root.message = "Sign-in was not available for this player"; root.forceActiveFocus() }
    }
}
