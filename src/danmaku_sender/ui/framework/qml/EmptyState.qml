pragma ComponentBehavior: Bound

import QtQuick

// 空状态引导：数据为空时居中显示的提示块，标题在上、说明在下、动作按钮在最下。
//
// 契约：
// - theme 为令牌桥；title 为标题，description 留空则不显示。
// - 动作按钮经默认属性挂载收进行内，无按钮则不显示按钮行。
// - 显隐由使用方的 visible 控制，本件随承载区居中。
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

        Text {
            width: parent.width
            text: root.title
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            font.family: root.theme.fontFamily
            font.pointSize: root.theme.fontPointSize + 2
            color: root.theme.text
        }

        Text {
            width: parent.width
            visible: root.description !== ""
            text: root.description
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            font.family: root.theme.fontFamily
            font.pointSize: root.theme.fontPointSize
            color: root.theme.textSecondary
        }

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
