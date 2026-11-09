pragma ComponentBehavior: Bound

import QtQuick

// Fluent 风格卡片容器 (WinUI 3 Card)
//
// 设计规范：
// 1. 基础几何：圆角固定为 4px，背景填充默认卡片表面色 (CardBackgroundFillColorDefault)。
// 2. 双层光照描边：四周绘制 1px 的基础淡描边，并在底部叠加 1px 的提亮横线（两端各缩进 4px 以避让圆角切点，防止直角线突出圆角破坏轮廓），以此还原 WinUI 3 的立体光照感。
//
// 属性与使用：
// - theme: 注入的 QmlPaletteBridge 实例，提供全局主题 Token。
// - padding: 卡片内部内容区域的四周内边距，默认为 8px。
// - content (default): 直接在组件标签内部声明的子控件会自动作为内容挂载到内边距区域中。

Rectangle {
    id: root

    required property var theme
    property real padding: 8
    default property alias content: inner.data

    radius: 4
    color: root.theme.CardBackgroundFillColorDefault
    border.color: root.theme.DividerStrokeColorDefault
    border.width: 1
    clip: true

    // 底部高光提亮横线：模拟顶光照射下的底边微弱反光（左右内缩 4px 避免穿出圆角）
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        height: 1
        color: root.theme.ControlStrokeColorDefault
    }

    // 内容承载区域
    Item {
        id: inner
        anchors.fill: parent
        anchors.margins: root.padding
    }
}
