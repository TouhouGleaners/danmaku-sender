pragma ComponentBehavior: Bound

import QtQuick

// Fluent 风格二元开关（WinUI 3 ToggleSwitch 形制）。
// 度量取自 WinUI 3 ToggleSwitch_themeresources.xaml：轨道 40×20，滑块常态 12 / 悬停 14 / 按下 17×14；
// 滑块膨胀居中（源码 HorizontalAlignment="Center"），禁用态整体减淡（WinUI 用 Disabled 专用笔刷）。
//
// 契约：
// - theme 为令牌桥；checked 为开关状态，toggled 为用户切换信号。
// - 色阶走令牌（accent / surface / stroke / knobOff），随主题换装；焦点环仅键盘聚焦时显示。
Item {
    id: root

    required property var theme
    property var host
    property bool checked: false
    signal toggled(bool checked)

    property color accent: root.theme.accent
    property color surface: root.theme.fillPressed
    property color stroke: root.theme.border
    property color knobOn: "#FFFFFF"
    property color knobOff: root.theme.textSecondary

    readonly property bool hovered: area.containsMouse
    readonly property bool pressed: area.pressed

    readonly property color trackFill: {
        if (!root.enabled)
            return root.checked ? root.accent : root.surface
        if (root.pressed)
            return root.checked ? Qt.lighter(root.accent, 1.3) : Qt.darker(root.surface, 1.12)
        if (root.hovered)
            return root.checked ? Qt.lighter(root.accent, 1.15) : Qt.darker(root.surface, 1.06)
        return root.checked ? root.accent : root.surface
    }
    readonly property color trackStroke: root.checked ? root.accent : root.stroke
    readonly property color knobFill: root.checked ? root.knobOn : root.knobOff

    width: 40
    height: 20
    focus: true
    activeFocusOnTab: true
    // WinUI 禁用态用 Disabled 专用笔刷（约四成透明度）；以整体透明度近似
    opacity: root.enabled ? 1 : 0.45

    // 位移进度：0 为关、1 为开
    property real progress: root.checked ? 1 : 0
    Behavior on progress {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    readonly property real inset: (root.height - 12) / 2
    // 滑块中心的行程：两端各留 inset
    readonly property real knobCenter: root.inset + 6 + (root.width - 2 * root.inset - 12) * root.progress

    function toggle() {
        root.checked = !root.checked
        root.toggled(root.checked)
        if (root.host)
            root.host.notify_toggled(root.checked)
    }

    Rectangle {
        id: track
        anchors.fill: parent
        radius: height / 2
        color: root.trackFill
        border.width: 1
        border.color: root.trackStroke
        Behavior on color {
            ColorAnimation { duration: 150 }
        }

        Rectangle {
            id: knob
            radius: height / 2
            anchors.verticalCenter: parent.verticalCenter
            color: root.knobFill

            readonly property real baseW: root.pressed ? 17 : (root.hovered ? 14 : 12)
            readonly property real baseH: root.pressed ? 14 : (root.hovered ? 14 : 12)

            width: baseW
            height: baseH
            // 居中膨胀：宽度变化时围绕中心，行进由中心点动画驱动
            x: root.knobCenter - width / 2

            Behavior on width {
                NumberAnimation { duration: 90; easing.type: Easing.OutQuad }
            }
            Behavior on height {
                NumberAnimation { duration: 90; easing.type: Easing.OutQuad }
            }
        }
    }

    Rectangle {
        id: focusRing
        visible: root.activeFocus && !area.containsMouse
        anchors.fill: parent
        anchors.margins: 1.5
        radius: height / 2
        color: "transparent"
        border.width: 1
        border.color: root.accent
        opacity: 0.6
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.enabled
        onClicked: root.toggle()
    }

    Keys.onPressed: (event) => {
        if (event.key === Qt.Key_Space || event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            root.toggle()
            event.accepted = true
        }
    }
}
