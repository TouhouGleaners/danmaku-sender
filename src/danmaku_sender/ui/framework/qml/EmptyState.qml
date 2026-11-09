pragma ComponentBehavior: Bound

import QtQuick

// 空状态引导视图 (Empty State Hint)
//
// 设计与行为：
// 1. 结构排布：垂直居中排列，自上而下依次为主标题、辅助说明文字以及可选的操作按钮组。
// 2. 响应式显隐：说明文字与操作按钮均为可选。未设置时自动收折高度，保持整体视觉绝对居中。
//
// 属性与使用：
// - theme: 注入的 QmlPaletteBridge 实例。
// - title: 主提示标题。
// - description: 可选的辅助说明文字，留空则不显示该文本行。
// - actions (default): 默认属性，直接在标签内部放置的按钮会自动排入底部的横向操作栏中。

Item {
    id: root

    required property var theme
    property string title: ""
    property string description: ""
    default property alias actions: buttons.data

    Column {
        anchors.centerIn: parent
        width: parent.width
        spacing: 6

        // 主标题
        Text {
            width: parent.width
            text: root.title
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            font.family: root.theme.fontFamily
            font.pointSize: root.theme.fontPointSize + 2
            color: root.theme.TextFillColorPrimary
        }

        // 辅助说明（仅在非空时显示并占用高度）
        Text {
            width: parent.width
            visible: root.description !== ""
            text: root.description
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            font.family: root.theme.fontFamily
            font.pointSize: root.theme.fontPointSize
            color: root.theme.TextFillColorSecondary
        }

        // 操作按钮容器：仅当外部传入了有效的子组件时才占用布局高度并显示，避免空留边距
        Item {
            width: parent.width
            height: buttons.height
            visible: buttons.visibleChildren.length > 0

            Row {
                id: buttons
                anchors.centerIn: parent
                spacing: 8
            }
        }
    }
}
