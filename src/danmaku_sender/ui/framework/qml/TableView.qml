pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

// 通用 Fluent 风格表格：表头与行按列规格渲染，行交互发信号。
// columns: [{role, title, width, align, colorRole}]——width 为 null 的列为弹性列，吸收行宽余量；
// colorRole 非空时该列文字色取行的该角色（十六进制色）。
// model 须按角色暴露行数据（roleNames），委托按列的 role 从行读取。
Item {
    id: root

    required property var theme
    required property var model
    property var columns: []
    property string emptyText: ""

    signal rowActivated(int row)
    signal rowContextMenu(int row, point pos)

    function isFill(column) {
        return column.width === null || column.width === undefined
    }

    Rectangle {
        id: headerBar
        width: parent.width
        height: 30
        clip: true
        color: root.theme.fillPressed

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 4
            anchors.rightMargin: 4
            spacing: 8

            Repeater {
                model: root.columns
                delegate: Text {
                    required property var modelData

                    Layout.minimumWidth: root.isFill(modelData) ? 0 : modelData.width
                    Layout.preferredWidth: root.isFill(modelData) ? 0 : modelData.width
                    Layout.fillWidth: root.isFill(modelData)
                    text: modelData.title
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    horizontalAlignment: modelData.align === "right" ? Text.AlignRight : Text.AlignLeft
                    font.family: root.theme.fontFamily
                    font.pointSize: root.theme.fontPointSize
                    font.bold: true
                    color: root.theme.text
                }
            }
        }
    }

    ListView {
        id: list
        anchors.top: headerBar.bottom
        width: parent.width
        height: parent.height - headerBar.height
        clip: true
        model: root.model
        spacing: 0

        delegate: Rectangle {
            id: row
            required property int index
            required property var model

            width: list.width
            height: 30
            color: rowMouse.containsMouse ? root.theme.fillHover
                : row.index % 2 ? root.theme.background : "transparent"

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

                        Layout.minimumWidth: root.isFill(modelData) ? 0 : modelData.width
                        Layout.preferredWidth: root.isFill(modelData) ? 0 : modelData.width
                        Layout.fillWidth: root.isFill(modelData)
                        text: row.model[modelData.role] ?? ""
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        horizontalAlignment: modelData.align === "right" ? Text.AlignRight : Text.AlignLeft
                        font.family: root.theme.fontFamily
                        font.pointSize: root.theme.fontPointSize
                        color: modelData.colorRole ? (row.model[modelData.colorRole] ?? root.theme.text) : root.theme.text
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
                onDoubleClicked: (mouse) => {
                    if (mouse.button === Qt.LeftButton)
                        root.rowActivated(row.index)
                }
                onClicked: (mouse) => {
                    if (mouse.button === Qt.RightButton)
                        root.rowContextMenu(row.index, row.mapToItem(null, mouse.x, mouse.y))
                }
            }
        }
    }

    Text {
        anchors.centerIn: list
        visible: list.count === 0
        text: root.emptyText
        textFormat: Text.PlainText
        horizontalAlignment: Text.AlignHCenter
        font.family: root.theme.fontFamily
        font.pointSize: root.theme.fontPointSize
        color: root.theme.textSecondary
    }
}
