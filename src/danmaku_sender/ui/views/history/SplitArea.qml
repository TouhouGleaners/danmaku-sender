pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../framework/qml" as Fluent

// 历史页分栏区：
// 整块一个 Quick 场景，分栏拖动只改场景内两个栏的宽度，承载面（原生 Quick 窗口）不改尺寸。
// 通用件是 Fluent.TreeView 与 Fluent.TableView，本文件仅承担组装与历史页专属组件（按钮、筛选行、标识条、菜单）。
Item {
    id: root

    required property var theme
    required property var bridge
    required property var treeRows
    required property var records
    required property var treeColumns
    required property var tableColumns

    // QtQuick.Controls 的调色板：原生风格控件不解析 theme 令牌，按令牌映射到 palette
    palette.window: root.theme.background
    palette.base: root.theme.background
    palette.alternateBase: root.theme.fillPressed
    palette.text: root.theme.text
    palette.windowText: root.theme.text
    palette.button: root.theme.fillPressed
    palette.buttonText: root.theme.text
    palette.highlight: root.theme.accent
    palette.highlightedText: root.theme.background
    palette.placeholderText: root.theme.textSecondary
    palette.mid: root.theme.fillPressed
    palette.light: root.theme.fillHover

    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal

        handle: Rectangle {
            implicitWidth: 4
            color: "transparent"

            Rectangle {
                anchors.centerIn: parent
                width: 2
                height: parent.height
                radius: 1
                color: handleArea.pressed ? root.theme.strokeStrong : root.theme.divider
                opacity: handleArea.pressed || handleArea.containsMouse ? 1.0 : 0.0
                Behavior on opacity { NumberAnimation { duration: 100 } }
            }

            MouseArea {
                id: handleArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.SizeHorCursor
            }
        }

        // ---------- 左栏：账本级操作 + 任务时间树 ----------
        ColumnLayout {
            SplitView.preferredWidth: 300
            SplitView.minimumWidth: 220
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                Button {
                    text: "验证全部"
                    onClicked: root.bridge.verify_all()
                }
                Item { Layout.fillWidth: true }
            }

            Fluent.Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                theme: root.theme

                Fluent.TreeView {
                    anchors.fill: parent
                    theme: root.theme
                    model: root.treeRows
                    columns: root.treeColumns
                    onRowPicked: (row) => root.bridge.pick_tree_row(row)
                }
            }
        }

        // ---------- 右栏：任务标识 + 筛选 + 弹幕表 ----------
        ColumnLayout {
            SplitView.fillWidth: true
            spacing: 8

            Fluent.Card {
                Layout.fillWidth: true
                implicitHeight: cardBody.implicitHeight + 32
                padding: 16
                theme: root.theme
                visible: root.bridge.summaryTitle.length > 0

                ColumnLayout {
                    id: cardBody
                    anchors.fill: parent
                    spacing: 16

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        // 标识双行：上行 Semibold、下行常规
                        Text {
                            Layout.fillWidth: true
                            text: root.bridge.summaryTitle
                            wrapMode: Text.WordWrap
                            font.family: root.theme.fontFamily
                            font.pointSize: root.theme.fontPointSize
                            font.weight: Font.DemiBold
                            color: root.theme.text
                            textFormat: Text.PlainText
                        }

                        Text {
                            Layout.fillWidth: true
                            visible: root.bridge.summaryPart !== ""
                            text: root.bridge.summaryPart
                            wrapMode: Text.WordWrap
                            font.family: root.theme.fontFamily
                            font.pointSize: root.theme.fontPointSize
                            color: root.theme.text
                            textFormat: Text.PlainText
                        }
                    }

                    RowLayout {
                        spacing: 32

                        ColumnLayout {
                            spacing: 2

                            Text {
                                text: root.bridge.summaryRate
                                font.family: root.theme.fontFamily
                                font.pointSize: root.theme.fontPointSize * 2
                                font.bold: true
                                color: root.theme.accent
                            }

                            Text {
                                text: "存活率"
                                font.family: root.theme.fontFamily
                                font.pointSize: root.theme.fontPointSize
                                color: root.theme.textSecondary
                            }
                        }

                        GridLayout {
                            columns: 2
                            columnSpacing: 24
                            rowSpacing: 8

                            Repeater {
                                model: root.bridge.summaryStats
                                delegate: RowLayout {
                                    id: statRow
                                    required property var modelData
                                    spacing: 8

                                    Text {
                                        text: statRow.modelData.label
                                        font.family: root.theme.fontFamily
                                        font.pointSize: root.theme.fontPointSize
                                        color: root.theme.textSecondary
                                        textFormat: Text.PlainText
                                    }

                                    Text {
                                        text: statRow.modelData.value
                                        font.family: root.theme.fontFamily
                                        font.pointSize: root.theme.fontPointSize
                                        color: root.theme.text
                                        textFormat: Text.PlainText
                                    }
                                }
                            }
                        }

                        Item { Layout.fillWidth: true }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: root.bridge.summaryTitle.length === 0
                text: "未选择任务\n从左侧的时间树里选一个任务查看它的弹幕"
                wrapMode: Text.WordWrap
                font.family: root.theme.fontFamily
                font.pointSize: root.theme.fontPointSize
                color: root.theme.textSecondary
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: "搜索:"
                    font.family: root.theme.fontFamily
                    font.pointSize: root.theme.fontPointSize
                    color: root.theme.text
                }
                TextField {
                    Layout.fillWidth: true
                    placeholderText: "搜索内容 / BV号 ..."
                    onAccepted: root.bridge.search(text)
                }
                Text {
                    text: "状态:"
                    font.family: root.theme.fontFamily
                    font.pointSize: root.theme.fontPointSize
                    color: root.theme.text
                }
                ComboBox {
                    model: ["全部状态", "待验证", "已存活", "已丢失"]
                    onActivated: (index) => root.bridge.select_status(index)
                }
                Button {
                    text: "刷新数据"
                    onClicked: root.bridge.refresh()
                }
            }

            Fluent.Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                theme: root.theme

                Fluent.TableView {
                    anchors.fill: parent
                    theme: root.theme
                    model: root.records
                    columns: root.tableColumns
                    emptyTitle: root.bridge.emptyTitle
                    emptyDescription: root.bridge.emptyDescription
                    emptyActionText: root.bridge.emptyActionText
                    onEmptyActionClicked: root.bridge.refresh()
                    onRowActivated: (row) => {
                        root.bridge.pick_record(row)
                        root.bridge.open_record()
                    }
                    onRowContextMenu: (row, pos) => {
                        root.bridge.pick_record(row)
                        rowMenu.popup(pos)
                    }
                }
            }
        }
    }

    Menu {
        id: rowMenu

        MenuItem {
            text: "浏览器打开"
            onTriggered: root.bridge.open_in_browser()
        }
        MenuItem {
            text: "查看完整详情"
            onTriggered: root.bridge.open_record()
        }
        MenuItem {
            text: "验证该分P所有弹幕"
            onTriggered: root.bridge.verify_part()
        }
        MenuItem {
            text: "复制 BVID"
            onTriggered: root.bridge.copy_bvid()
        }
        MenuItem {
            text: "复制 内容"
            onTriggered: root.bridge.copy_content()
        }
    }
}
