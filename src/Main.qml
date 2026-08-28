import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.login as PlasmaLogin
import io.github.rfrench3.controllable

Item {
    id: root
    anchors.fill: parent
    property int selectedIndex: 0
    property bool powerFocused: false
    property int powerIndex: 0
    property int pendingPowerIndex: -1
    property bool loggingIn: false
    property int controllerHorizontal: 0
    property int controllerVertical: 0
    property string message: "Who’s playing?"
    readonly property int cardWidth: 250
    readonly property int cardHeight: 286
    readonly property int count: list.count
    function move(delta) {
        if (loggingIn) return
        if (powerFocused) {
            powerIndex = (powerIndex + delta + 2) % 2
            pendingPowerIndex = -1
        } else if (count > 0) {
            selectedIndex = (selectedIndex + delta + count) % count
            pendingPowerIndex = -1
        }
    }
    function controllerDirection(value) {
        return value < -Gamepad.deadzone ? -1 : value > Gamepad.deadzone ? 1 : 0
    }
    function updateControllerAxes() {
        const horizontal = controllerDirection(Gamepad.leftX)
        const vertical = controllerDirection(Gamepad.leftY)
        if (horizontal !== controllerHorizontal) {
            if (horizontal) move(horizontal)
            controllerHorizontal = horizontal
        }
        if (vertical !== controllerVertical) {
            if (vertical < 0) {
                powerFocused = false
                pendingPowerIndex = -1
            }
            else if (vertical > 0) powerFocused = true
            controllerVertical = vertical
        }
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
            // Keep confirmation in the greeter so the same controller input
            // path works for both stages, rather than opening the desktop
            // session's countdown prompt.
            if (pendingPowerIndex !== powerIndex) {
                pendingPowerIndex = powerIndex
                return
            }
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
    // KWin normalises supported controllers into SDL-style logical buttons.
    // This is inside the greeter compositor's input pipeline, unlike an
    // external uinput device, while mouse interaction remains untouched.
    Connections {
        target: Gamepad
        function onButtonEvent(button, pressed) {
            if (!pressed || root.loggingIn) return
            switch (button) {
            case 0:  // A / Cross
            case 6:  // Start
                root.activate()
                break
            case 11: // D-pad up
                root.powerFocused = false
                root.pendingPowerIndex = -1
                break
            case 12: // D-pad down
                root.powerFocused = true
                break
            case 13: // D-pad left
                root.move(-1)
                break
            case 14: // D-pad right
                root.move(1)
                break
            }
        }
    }
    Timer {
        interval: Gamepad.pollingRate
        running: !root.loggingIn
        repeat: true
        onTriggered: root.updateControllerAxes()
    }
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
            Layout.alignment: Qt.AlignHCenter
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
                property bool active: selected && !root.powerFocused
                width: root.cardWidth; height: root.cardHeight
                Item {
                    anchors.fill: parent; anchors.margins: -8
                    visible: card.active
                    Rectangle {
                        anchors.fill: parent; radius: 30; color: "transparent"
                        border.width: 2; border.color: "#9ed9ff"; opacity: .5
                        SequentialAnimation on opacity {
                            running: card.active
                            loops: Animation.Infinite
                            NumberAnimation { to: .12; duration: 850; easing.type: Easing.InOutSine }
                            NumberAnimation { to: .62; duration: 850; easing.type: Easing.InOutSine }
                        }
                    }
                }
                Rectangle { anchors.fill: parent; radius: 22; color: card.active ? "#1d3552" : "#172235"; border.width: card.active ? 3 : 1; border.color: card.active ? "#79caff" : "#30445d" }
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
                        root.pendingPowerIndex = -1
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
                delegate: Item {
                    required property string modelData
                    required property int index
                    width: 144; height: 44
                    Item {
                        anchors.fill: parent; anchors.margins: -8
                        visible: root.powerFocused && root.powerIndex === index
                        Rectangle {
                            anchors.fill: parent; radius: 18; color: "transparent"
                            border.width: 2; border.color: "#9ed9ff"; opacity: .5
                            SequentialAnimation on opacity {
                                running: root.powerFocused && root.powerIndex === index
                                loops: Animation.Infinite
                                NumberAnimation { to: .12; duration: 850; easing.type: Easing.InOutSine }
                                NumberAnimation { to: .62; duration: 850; easing.type: Easing.InOutSine }
                            }
                        }
                    }
                    Rectangle {
                        anchors.fill: parent; radius: 12; color: "#202b3c"
                        border.width: 1; border.color: "#40536d"
                        QQC2.Label {
                            anchors.centerIn: parent
                            text: root.pendingPowerIndex === index ? "Are you sure?" : (index === 0 ? "⏻  " : "↻  ") + modelData
                            color: "white"; font.pixelSize: 16; font.weight: Font.DemiBold
                        }
                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            onEntered: {
                                if (root.loggingIn) return
                                if (root.powerIndex !== index) root.pendingPowerIndex = -1
                                root.powerFocused = true
                                root.powerIndex = index
                            }
                            onExited: {
                                if (root.powerFocused && root.powerIndex === index) root.pendingPowerIndex = -1
                            }
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
    }
    QQC2.Label {
        visible: !root.loggingIn
        anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.rightMargin: 34; anchors.bottomMargin: 25
        text: root.powerFocused ? "Controller: choose power option    A  Confirm" : "Controller: choose player    A  Select"
        color: "#8495ad"; font.pixelSize: 14
    }
    Connections { target: PlasmaLogin.Authenticator
        function onLoginFailed() { root.loggingIn = false; root.message = "Sign-in was not available for this player"; root.forceActiveFocus() }
    }
}
