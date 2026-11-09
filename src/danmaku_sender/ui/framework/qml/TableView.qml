pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// 通用 Fluent 风格数据表格 (WinUI 3 TableView)
//
// 架构设计：
// 1. 列规格系统 (Column Specifications)：
//    通过 columns 数组声明每列属性：[{ role, title, width, align, toneRole, tag }]。
//    - 弹性列 (Fill Column)：未指定固定 width 且非 Tag 的列，自动吸收视口剩余宽度。
//    - 胶囊标签列 (Tag Column)：带有 tag: true 的列，自动套用圆角状态胶囊 (Tag.qml) 渲染。
// 2. 斑马纹与悬停：偶数行背景透明，奇数行微弱着色；鼠标悬停时整体平滑高亮。
// 3. 空状态提示：当绑定的数据模型为空 (count === 0) 时，自动浮现 EmptyState 引导组件。
// 4. 定制滚动条：集成轻量级细胶囊悬浮滚动条，常态淡化，操作时显形。
//
// 事件信号：
// - rowActivated(int row): 行被左键双击时触发（通常用于呼出详情档案）。
// - rowContextMenu(int row, point pos): 行被右键点击时触发，返回右键菜单所需坐标。
// - emptyActionClicked(): 点击空状态引导按钮时触发。

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

    // 弹性列判定：非 Tag 胶囊且未声明具体宽度的列，视为弹性吸收列
    function isFill(column) {
        return !column.tag && (column.width === null || column.width === undefined)
    }

    // 表头横栏
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

    // 数据行列表
    ListView {
        id: list
        anchors.top: headerBar.bottom
        width: parent.width
        height: parent.height - headerBar.height
        clip: true
        model: root.model
        spacing: 0

        // 垂直滚动条
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

        // 单行委托
        delegate: Rectangle {
            id: row
            required property int index
            required property var model

            width: list.width
            height: 30

            // 背景交互状态：悬停高亮 > 隔行斑马纹底色 > 透明
            color: rowMouse.containsMouse
                ? root.theme.SubtleFillColorSecondary
                : row.index % 2
                    ? root.theme.SolidBackgroundFillColorTertiary
                    : "transparent"

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

                        // 状态标签列：尺寸随文字内容自适应，右对齐时按单元格宽度推至右边缘
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

                        // 普通文本列：单行显示，超出宽度时右侧省略
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

    // 空状态引导
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
