pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

// 通用 Fluent 风格表格：表头与行按列规格渲染，行交互发信号。
// columns: [{role, title, width, align, colorRole}]——width 为 null 的弹性列须是第一列；
// colorRole 非空时该列文字色取行的该角色（十六进制色）。
Item {
    id: root

    required property var theme
    required property var model
    property var columns: []
    property string emptyText: ""

    signal rowActivated(int row)
    signal rowContextMenu(int row)

    function isFill(column) {
        return column.width === null || column.width === undefined
    }

    Rectangle {
        id: header
        width: parent.width
        height: 30
        color: theme.fillPressed

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 4
            anchors.rightMargin: 4
            spacing: 8

            Repeater {
                model: root.columns
                delegate: Text {
                    required property var modelData

                    Layout.preferredWidth: root.isFill(modelData) ? 0 : modelData.width
                    Layout.fillWidth: root.isFill(modelData)
                    text: modelData.title
                    elide: Text.ElideRight
                    font.family: theme.fontFamily
                    font.pointSize: theme.fontPointSize
                    font.bold: true
                    color: theme.text
                }
            }
        }
    }

    ListView {
        id: list
        anchors.top: header.bottom
        width: parent.width
        height: parent.height - header.height
        clip: true
        model: root.model
        spacing: 0

        delegate: Rectangle {
            id: row
            required property int index
            required property var model

            width: list.width
            height: 30
            color: rowMouse.containsMouse ? theme.fillHover
                : row.index % 2 ? theme.background : "transparent"

            RowLayout {
                x: 4
                y: 0
                width: row.width - 8
                height: row.height
                spacing: 8

                Repeater {
                    model: root.columns
                    delegate: Text {
                        required property var modelData

                        Layout.preferredWidth: root.isFill(modelData) ? 0 : modelData.width
                        Layout.fillWidth: root.isFill(modelData)
                        text: row.model[modelData.role] ?? ""
                        elide: Text.ElideRight
                        font.family: theme.fontFamily
                        font.pointSize: theme.fontPointSize
                        color: modelData.colorRole ? (row.model[modelData.colorRole] ?? theme.text) : theme.text
                    }
                }
            }

            MouseArea {
                id: rowMouse
                x: 0
                y: 0
                width: row.width
                height: row.height
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                onDoubleClicked: root.rowActivated(row.index)
                onClicked: (mouse) => {
                    if (mouse.button === Qt.RightButton)
                        root.rowContextMenu(row.index)
                }
            }
        }
    }

    Text {
        anchors.centerIn: parent
        visible: list.count === 0
        text: root.emptyText
        horizontalAlignment: Text.AlignHCenter
        font.family: theme.fontFamily
        font.pointSize: theme.fontPointSize
        color: theme.textSecondary
    }
}
