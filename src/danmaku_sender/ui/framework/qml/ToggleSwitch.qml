pragma ComponentBehavior: Bound

import QtQuick

// Fluent 风格二元开关 (WinUI 3 ToggleSwitch)
//
// 设计与度量规范（严格参考 WinUI 3 ToggleSwitch_themeresources.xaml）：
// 1. 轨道与滑块：
//    - 轨道尺寸为 40x20px 胶囊；
//    - 滑块常态尺寸为 12x12px，悬停时微膨胀为 14x14px，按下时拉伸为 17x14px。
// 2. 居中膨胀机制：滑块尺寸变化时始终以其物理几何中心为基准向两侧展开，防止重心左右漂移。
// 3. 焦点环设计：
//    - 对齐 Windows 11 键盘导航原则，仅在键盘操作（Tab / 方向键）聚焦时显示外扩焦点环；
//    - 鼠标点击聚焦时不显示。
//    - 控件外层预留 8px 边距专供焦点环展开。
// 4. 透明度合成防黑边：通过在底层显式绘制与宿主卡片一致的实色背景，彻底避免 QQuickWidget 在处理透明通道合成与圆角抗锯齿时在四角产生黑色杂边。
//
// 属性与接口：
// - theme: 注入的 QmlPaletteBridge 实例。
// - checked: 当前开关开启状态 (bool)。
// - onText / offText: 开/关状态文字标签，默认分别对应“开”和“关”。
// - surface: 宿主卡片传递的当前表面色，用于底层混色。
// - toggled(bool): 状态被用户交互改变时向外发出的通知信号。

Item {
    id: root

    required property var theme
    property var host
    property bool checked: false
    property string onText: "开"
    property string offText: "关"
    property color surface: root.theme.SolidBackgroundFillColorTertiary
    signal toggled(bool checked)

    // 色彩 Tokens 映射
    property color fillOn: root.theme.AccentFillColorDefault
    property color fillOff: root.theme.SubtleFillColorTertiary
    property color strokeOn: root.theme.AccentFillColorDefault
    property color strokeOff: root.theme.ControlStrokeColorDefault
    property color knobFillOn: "#FFFFFF"
    property color knobFillOff: root.theme.TextFillColorSecondary

    readonly property bool hovered: area.containsMouse
    readonly property bool pressed: area.pressed

    // 轨道背景色动态计算
    readonly property color trackFill: {
        if (!root.enabled)
            return root.checked ? root.fillOn : root.fillOff
        if (root.pressed)
            return root.checked ? Qt.lighter(root.fillOn, 1.3) : Qt.darker(root.fillOff, 1.12)
        if (root.hovered)
            return root.checked ? Qt.lighter(root.fillOn, 1.15) : Qt.darker(root.fillOff, 1.06)
        return root.checked ? root.fillOn : root.fillOff
    }
    readonly property color trackStroke: root.checked ? root.strokeOn : root.strokeOff
    readonly property color knobFill: root.checked ? root.knobFillOn : root.knobFillOff

    // 整体尺寸预留外扩边距，防止焦点环（外扩 8px）被组件外层裁剪
    width: content.width + 16
    height: content.height + 16
    focus: true
    activeFocusOnTab: true

    // 禁用态整体置灰淡化（对齐 WinUI Disabled 专用透明笔刷）
    opacity: root.enabled ? 1 : 0.45

    // 滑块位移进度：0 为关闭端，1 为开启端，驱动平滑位移动画
    property real progress: root.checked ? 1 : 0
    Behavior on progress {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    // 键盘焦点环可见性：仅在键盘导航入焦时激活，鼠标点击不触发
    property bool focusRingVisible: false

    function toggle() {
        if (!root.enabled)
            return
        root.checked = !root.checked
        root.toggled(root.checked)
        if (root.host)
            root.host.notify_toggled(root.checked)
    }

    // 避免抗锯齿黑边：
    // QQuickWidget 在透明视口合成时，圆角外边缘容易出现黑边与杂色；
    // 此处在底层铺一层与宿主卡片表面相同的实色背景，使圆角抗锯齿混合正常。
    Rectangle {
        anchors.fill: parent
        color: root.surface
    }

    Item {
        id: content
        anchors.centerIn: parent
        width: stateLabel.implicitWidth + 10 + track.width
        height: track.height

        // 状态文字：位于轨道左侧，字号对齐 WinUI 标准正文档位 (14px)
        Text {
            id: stateLabel
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: root.checked ? root.onText : root.offText
            color: root.theme.TextFillColorPrimary
            font.family: root.theme.fontFamily
            font.pixelSize: 14
        }

        // 开关胶囊
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

            // 几何推导：
            // 1. 胶囊两端留白边距 (inset) = (轨道高 20px - 滑块高 12px) / 2 = 4px
            // 2. 滑块中心点行程范围：左侧起点 (inset + 半径 6px) 到右侧终点，按 progress (0~1) 线性插值
            readonly property real inset: (height - 12) / 2
            readonly property real knobCenter: inset + 6 + (width - 2 * inset - 12) * root.progress

            // 运动滑块
            Rectangle {
                id: knob
                radius: height / 2
                anchors.verticalCenter: parent.verticalCenter
                color: root.knobFill

                // 按压与悬停状态下的物理尺寸反馈
                readonly property real baseW: root.pressed ? 17 : (root.hovered ? 14 : 12)
                readonly property real baseH: root.pressed ? 14 : (root.hovered ? 14 : 12)

                width: baseW
                height: baseH
                // 居中膨胀机制：滑块悬停/按下时尺寸拉伸，以中心点对称向两侧膨胀，不改变视觉重心
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

    // 键盘焦点高亮环（外扩 8px，2px 主文本色描边）
    Rectangle {
        id: focusRing
        visible: root.focusRingVisible
        anchors.fill: content
        anchors.margins: -8
        radius: 10
        color: "transparent"
        border.width: 2
        border.color: root.theme.TextFillColorPrimary
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.enabled
        onPressed: root.focusRingVisible = false
        onClicked: root.toggle()
    }

    // 键盘控制（空格与回车切换状态）
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
