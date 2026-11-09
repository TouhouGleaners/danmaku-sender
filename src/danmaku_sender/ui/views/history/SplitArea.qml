pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../framework/qml" as Fluent

// 弹幕历史主页面双栏分流区 (Split View Area)
//
// 架构定位：
// 1. 混合桥接单场景：整个分栏区承载在同一个原生 QQuickView (QmlWindowHost) 内部。
//    拖动分栏条时只改变场景内部两个区域的弹性宽度，宿主外部 Qt 窗口完全不需要改变几何尺寸，消除了 QSplitter 跨窗口重绘造成的掉帧问题。
// 2. 组件分层：复用通用的 Fluent.TreeView 与 Fluent.TableView，本文件仅负责历史页专属的业务数据绑定（筛选工具条、统计看板卡片、右键操作菜单）。

Item {
    id: root

    required property var theme
    required property var bridge
    required property var treeRows
    required property var records
    required property var treeColumns
    required property var tableColumns

    // 【QtQuick.Controls 风格适配】：
    // 原生 Fusion 风格控件无法直接解析自定义主题 Token，在此处显式将 Token 映射到 QML 内置调色板角色中，确保下拉菜单、按钮的底色与高亮文本随系统主题动态联动。
    palette.window: root.theme.SolidBackgroundFillColorTertiary
    palette.base: root.theme.SolidBackgroundFillColorTertiary
    palette.alternateBase: root.theme.SubtleFillColorTertiary
    palette.text: root.theme.TextFillColorPrimary
    palette.windowText: root.theme.TextFillColorPrimary
    palette.button: root.theme.SubtleFillColorTertiary
    palette.buttonText: root.theme.TextFillColorPrimary
    palette.highlight: root.theme.AccentFillColorDefault
    palette.highlightedText: root.theme.SolidBackgroundFillColorTertiary
    palette.placeholderText: root.theme.TextFillColorSecondary
    palette.mid: root.theme.SubtleFillColorTertiary
    palette.light: root.theme.SubtleFillColorSecondary

    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal

        // 分栏条拖拽手柄
        handle: Rectangle {
            implicitWidth: 4
            color: "transparent"

            Rectangle {
                anchors.centerIn: parent
                width: 2
                height: parent.height
                radius: 1
                color: handleArea.pressed ? root.theme.ControlStrongStrokeColorDefault : root.theme.DividerStrokeColorDefault
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

        // 左栏：全量核销入口与任务时间树
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

        // 右栏：任务概览看板、搜索筛选条与弹幕记录数据表
        ColumnLayout {
            SplitView.fillWidth: true
            spacing: 8

            // 任务详情与存活统计概览卡片（仅在选中具体任务时显示）
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

                    // 视频标题与分P标识
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        // 主标题文本
                        Text {
                            Layout.fillWidth: true
                            text: root.bridge.summaryTitle
                            wrapMode: Text.WordWrap
                            font.family: root.theme.fontFamily
                            font.pointSize: root.theme.fontPointSize
                            font.weight: Font.DemiBold
                            color: root.theme.TextFillColorPrimary
                            textFormat: Text.PlainText
                        }

                        // 分P标题文本
                        Text {
                            Layout.fillWidth: true
                            visible: root.bridge.summaryPart !== ""
                            text: root.bridge.summaryPart
                            wrapMode: Text.WordWrap
                            font.family: root.theme.fontFamily
                            font.pointSize: root.theme.fontPointSize
                            color: root.theme.TextFillColorPrimary
                            textFormat: Text.PlainText
                        }
                    }

                    // 存活率与各项统计数据
                    RowLayout {
                        spacing: 32

                        ColumnLayout {
                            spacing: 2

                            Text {
                                text: root.bridge.summaryRate
                                font.family: root.theme.fontFamily
                                font.pointSize: root.theme.fontPointSize * 2
                                font.bold: true
                                color: root.theme.AccentFillColorDefault
                            }

                            Text {
                                text: "存活率"
                                font.family: root.theme.fontFamily
                                font.pointSize: root.theme.fontPointSize
                                color: root.theme.TextFillColorSecondary
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
                                        color: root.theme.TextFillColorSecondary
                                        textFormat: Text.PlainText
                                    }

                                    Text {
                                        text: statRow.modelData.value
                                        font.family: root.theme.fontFamily
                                        font.pointSize: root.theme.fontPointSize
                                        color: root.theme.TextFillColorPrimary
                                        textFormat: Text.PlainText
                                    }
                                }
                            }
                        }

                        Item { Layout.fillWidth: true }
                    }
                }
            }

            // 未选中任务时的空态提示
            Text {
                Layout.fillWidth: true
                visible: root.bridge.summaryTitle.length === 0
                text: "未选择任务\n从左侧的时间树里选一个任务查看它的弹幕"
                wrapMode: Text.WordWrap
                font.family: root.theme.fontFamily
                font.pointSize: root.theme.fontPointSize
                color: root.theme.TextFillColorSecondary
            }

            // 搜索与状态过滤工具栏
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: "搜索:"
                    font.family: root.theme.fontFamily
                    font.pointSize: root.theme.fontPointSize
                    color: root.theme.TextFillColorPrimary
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
                    color: root.theme.TextFillColorPrimary
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

            // 弹幕记录数据表
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

    // 右键菜单：针对选中行的操作
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
