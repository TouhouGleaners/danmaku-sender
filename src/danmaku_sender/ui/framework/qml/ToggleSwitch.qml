pragma ComponentBehavior: Bound

import QtQuick

// Fluent 风格二元开关（WinUI 3 ToggleSwitch 形制）。
// 度量取自 WinUI 3 ToggleSwitch_themeresources.xaml：轨道 40×20，滑块常态 12 / 悬停 14 / 按下 17×14；
// 滑块膨胀居中（源码 HorizontalAlignment="Center"），禁用态整体减淡（WinUI 用 Disabled 专用笔刷）。
// 状态文字在左、轨道在右，焦点环连文字与轨道一起框住（2px 高对比描边、外扩 8px、圆角 10）。
//
// 契约：
// - theme 为令牌桥；checked 为开关状态，toggled 为状态变化信号。
// - onText / offText 为状态文字；色阶走令牌随主题换装；焦点环仅键盘聚焦时显示。
Item {
    id: root

    required property var theme
    property var host
    property bool checked: false
    property string onText: "开"
    property string offText: "关"
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

    // 根盒为焦点环让位：环外扩 8px（6px 缝 + 2px 描边）
    width: content.width + 16
    height: content.height + 16
    focus: true
    activeFocusOnTab: true
    // WinUI 禁用态用 Disabled 专用笔刷（约四成透明度）；以整体透明度近似
    opacity: root.enabled ? 1 : 0.45

    // 位移进度：0 为关、1 为开。滑块位置由它派生。
    property real progress: root.checked ? 1 : 0
    Behavior on progress {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    // 焦点环只在键盘聚焦时显示；鼠标聚焦与失焦即灭（宿主按 focusReason 驱动）
    property bool focusRingVisible: false

    function toggle() {
        if (!root.enabled)
            return
        root.checked = !root.checked
        root.toggled(root.checked)
        if (root.host)
            root.host.notify_toggled(root.checked)
    }

    Item {
        id: content
        anchors.centerIn: parent
        width: stateLabel.implicitWidth + 10 + track.width
        height: track.height

        Text {
            id: stateLabel
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: root.checked ? root.onText : root.offText
            color: root.theme.text
            font.family: root.theme.fontFamily
            // WinUI 正文档为 14px（ControlContentThemeFontSize），状态文字随控件档
            font.pixelSize: 14
        }

        Rectangle {
            id: track
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: 40
            height: 20
            radius: height / 2
            color: root.trackFill
            border.width: 1
            border.color: root.trackStroke
            Behavior on color {
                ColorAnimation { duration: 150 }
            }

            readonly property real inset: (height - 12) / 2
            // 滑块中心的行程：两端各留 inset
            readonly property real knobCenter: inset + 6 + (width - 2 * inset - 12) * root.progress

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
                x: track.knobCenter - width / 2

                Behavior on width {
                    NumberAnimation { duration: 90; easing.type: Easing.OutQuad }
                }
                Behavior on height {
                    NumberAnimation { duration: 90; easing.type: Easing.OutQuad }
                }
            }
        }
    }

    Rectangle {
        id: focusRing
        visible: root.focusRingVisible
        anchors.fill: content
        anchors.margins: -8
        radius: 10
        color: "transparent"
        border.width: 2
        border.color: root.theme.text
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.enabled
        onPressed: root.focusRingVisible = false
        onClicked: root.toggle()
    }

    Keys.onPressed: (event) => {
        if (event.key === Qt.Key_Space || event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            root.toggle()
            event.accepted = true
        }
    }

    onActiveFocusChanged: {
        if (!activeFocus)
            focusRingVisible = false
    }
}
