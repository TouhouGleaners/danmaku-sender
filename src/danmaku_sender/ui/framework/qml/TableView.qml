pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// 通用 Fluent 风格表格：表头与行按列规格渲染，行交互发信号。
// columns: [{role, title, width, align, toneRole, tag}]——width 为 null 的列为弹性列，吸收行宽余量；
// tag 列渲染为小标签（健康档着色，toneRole 为档位角色名）。
// model 须按角色暴露行数据（roleNames），委托按列的 role 从行读取。
Item {
    id: root

    required property var theme
    required property var model
    property var columns: []
    property string emptyTitle: ""
    property string emptyDescription: ""
    property string emptyActionText: ""

    signal rowActivated(int row)
    signal rowContextMenu(int row, point pos)
    signal emptyActionClicked()

    function isFill(column) {
        return !column.tag && (column.width === null || column.width === undefined)
    }

    Rectangle {
        id: headerBar
        width: parent.width
        height: 30
        clip: true
        color: root.theme.SubtleFillColorTertiary

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 4
            anchors.rightMargin: 4
            spacing: 8

            Repeater {
                model: root.columns
                delegate: Text {
                    required property var modelData

                    Layout.minimumWidth: root.isFill(modelData) ? 0 : (modelData.width ?? implicitWidth)
                    Layout.preferredWidth: root.isFill(modelData) ? 0 : (modelData.width ?? implicitWidth)
                    Layout.fillWidth: root.isFill(modelData)
                    text: modelData.title
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    horizontalAlignment: modelData.align === "right" ? Text.AlignRight : Text.AlignLeft
                    font.family: root.theme.fontFamily
                    font.pointSize: root.theme.fontPointSize
                    font.bold: true
                    color: root.theme.TextFillColorPrimary
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
        ScrollBar.vertical: ScrollBar {
            id: vScroll
            width: 12
            policy: ScrollBar.AsNeeded
            visible: size < 1.0
            topPadding: 4
            bottomPadding: 4
            leftPadding: 3
            rightPadding: 3

            contentItem: Rectangle {
                radius: 3
                color: vScroll.hovered || vScroll.pressed ? root.theme.TextFillColorSecondary : root.theme.ControlStrokeColorDefault
            }

            background: Item {}
        }

        delegate: Rectangle {
            id: row
            required property int index
            required property var model

            width: list.width
            height: 30
            color: rowMouse.containsMouse ? root.theme.SubtleFillColorSecondary
                : row.index % 2 ? root.theme.SolidBackgroundFillColorTertiary : "transparent"

            RowLayout {
                x: 4
                y: 0
                width: row.width - 8
                height: row.height
                spacing: 8

                Repeater {
                    model: root.columns
                    delegate: Item {
                        id: cell
                        required property var modelData

                        readonly property bool isTag: modelData.tag === true
                        readonly property string cellText: row.model[modelData.role] ?? ""

                        Layout.minimumWidth: root.isFill(modelData) ? 0 : (modelData.width ?? implicitWidth)
                        Layout.preferredWidth: root.isFill(modelData) ? 0 : (modelData.width ?? implicitWidth)
                        Layout.fillWidth: root.isFill(modelData)
                        implicitWidth: cell.isTag ? tagPill.implicitWidth : plainLabel.implicitWidth
                        implicitHeight: cell.isTag ? tagPill.implicitHeight : plainLabel.implicitHeight

                        Tag {
                            id: tagPill
                            visible: cell.isTag
                            x: cell.modelData.align === "right" ? cell.width - width : 0
                            y: (cell.height - height) / 2
                            theme: root.theme
                            text: cell.cellText
                            tone: cell.modelData.toneRole ? (row.model[cell.modelData.toneRole] ?? "") : ""
                            fontPointSize: root.theme.fontPointSize - 1
                            minWidth: 26
                            padding: 8
                            height: 18
                        }

                        Text {
                            id: plainLabel
                            visible: !cell.isTag
                            anchors.fill: parent
                            text: cell.cellText
                            textFormat: Text.PlainText
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: cell.modelData.align === "right" ? Text.AlignRight : Text.AlignLeft
                            elide: Text.ElideRight
                            font.family: root.theme.fontFamily
                            font.pointSize: root.theme.fontPointSize
                            color: root.theme.TextFillColorPrimary
                        }
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

    EmptyState {
        anchors.fill: list
        visible: list.count === 0
        theme: root.theme
        title: root.emptyTitle
        description: root.emptyDescription

        Button {
            visible: root.emptyActionText !== ""
            text: root.emptyActionText
            onClicked: root.emptyActionClicked()
        }
    }
}
