pragma ComponentBehavior: Bound

import QtQuick

// 卡片表面：WinUI 3 卡片形制——圆角 4、表面色填充、双色描边（整体淡描、底边提亮）。
//
// 契约：
// - theme 为令牌桥；padding 为内容区四周内边距。
// - 内容经默认属性挂载，铺进内边距区；表面与描边由本件负责。
Rectangle {
    id: root

    required property var theme
    property real padding: 8
    default property alias content: inner.data

    radius: 4
    color: root.theme.card
    border.color: root.theme.divider
    border.width: 1
    clip: true

    // 底边提亮；两端避让圆角切点，避免直角线穿出圆角
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        height: 1
        color: root.theme.border
    }

    Item {
        id: inner
        anchors.fill: parent
        anchors.margins: root.padding
    }
}
