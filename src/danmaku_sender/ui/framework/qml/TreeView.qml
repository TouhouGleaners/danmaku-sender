pragma ComponentBehavior: Bound

import QtQuick

// 通用 Fluent 风格树行列表。度量照 WinUI 3 TreeView：行槽 32（内容 28 + 上下边距 2）、
// 内容圆角 4、缩进 16/层、chevron 槽 40（字形 12，双字形切换）、选中条 3×16 圆角 2。
//
// 契约：
// - model 为 TreeRowsModel：结构角色 depth/expandable/expanded，
//   内容列按 columns 的 {role, width, align} 渲染；width 为 null 的弹性列须是第一列。
// - 交互：chevron 单击/行双击切换展开，行单击选中并发出 rowPicked(row)。
Item {
    id: root

    required property var theme
    required property var model
    property var columns: []

    signal rowPicked(int row)

    readonly property string glyphCollapsed: String.fromCharCode(0xe76c)
    readonly property string glyphExpanded: String.fromCharCode(0xe70d)

    // 定宽列从右缘反向排列，弹性列从 chevron 槽后接出
    function trailingX(idx) {
        let x = tree.width - 8
        for (let i = root.columns.length - 1; i > idx; --i)
            x -= root.columns[i].width + 8
        return x - root.columns[idx].width
    }
    function columnX(idx, indent) {
        return idx === 0 ? indent + 40 : trailingX(idx)
    }
    function columnWidth(idx, indent) {
        if (root.columns[idx].width !== null && root.columns[idx].width !== undefined)
            return root.columns[idx].width
        let right = root.columns.length > 1 ? trailingX(1) : tree.width - 8
        return right - 8 - columnX(idx, indent)
    }

    ListView {
        id: tree
        anchors.fill: parent
        clip: true
        model: root.model
        currentIndex: -1
        boundsBehavior: Flickable.StopAtBounds

        highlightFollowsCurrentItem: true
        highlightMoveDuration: 150
        highlightResizeDuration: 150
        highlight: Item {
            Rectangle {
                x: 4
                width: 3
                height: 16
                radius: 2
                anchors.verticalCenter: parent.verticalCenter
                color: theme.accent
            }
        }

        add: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 150 }
        }
        displaced: Transition {
            NumberAnimation { properties: "x,y"; duration: 150; easing.type: Easing.OutCubic }
        }
        remove: Transition {
            NumberAnimation { property: "opacity"; to: 0; duration: 120 }
        }
        removeDisplaced: Transition {
            NumberAnimation { properties: "x,y"; duration: 150; easing.type: Easing.OutCubic }
        }

        delegate: Item {
            id: row

            required property int index
            required property int depth
            required property bool expandable
            required property bool expanded
            required property var model

            readonly property int indent: depth * 16

            width: tree.width
            height: 32

            Rectangle {
                id: bg
                x: 4
                y: 2
                width: parent.width - 8
                height: 28
                radius: 4
                color: rowMouse.pressed || chevronMouse.pressed ? theme.fillPressed
                    : tree.currentIndex === row.index || rowMouse.containsMouse ? theme.fillHover
                    : "transparent"

                Text {
                    id: chevronGlyph
                    x: row.indent + 14
                    width: 12
                    height: 12
                    anchors.verticalCenter: parent.verticalCenter
                    visible: row.expandable
                    text: row.expanded ? root.glyphExpanded : root.glyphCollapsed
                    font.family: "Segoe Fluent Icons"
                    font.pixelSize: 12
                    color: theme.text
                }

                Repeater {
                    model: root.columns
                    delegate: Text {
                        required property int index
                        required property var modelData

                        x: root.columnX(index, row.indent)
                        width: root.columnWidth(index, row.indent)
                        anchors.verticalCenter: parent.verticalCenter
                        text: row.model[modelData.role] ?? ""
                        horizontalAlignment: modelData.align === "right" ? Text.AlignRight : Text.AlignLeft
                        elide: index === 0 ? Text.ElideRight : Text.ElideNone
                        font.family: theme.fontFamily
                        font.pointSize: theme.fontPointSize
                        color: index === 0 ? theme.text : theme.textSecondary
                    }
                }

                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: {
                        tree.currentIndex = row.index
                        root.rowPicked(row.index)
                    }
                    onDoubleClicked: {
                        if (row.expandable)
                            root.model.toggle(row.index)
                    }
                }

                // chevron 命中区浮在行命中区之上，单击只切换展开，不选中
                MouseArea {
                    id: chevronMouse
                    x: row.indent
                    width: 40
                    height: parent.height
                    visible: row.expandable
                    onClicked: root.model.toggle(row.index)
                }
            }
        }
    }
}
