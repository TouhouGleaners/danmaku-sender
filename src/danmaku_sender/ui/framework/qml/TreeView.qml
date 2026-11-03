pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

// 通用 Fluent 风格树视图。度量与状态依 WinUI 3 TreeView，缩进依 VSCode 资源管理器收紧：
// 行槽 32（内容 28 + 上下边距 2；带次行的行 44）、内容圆角 4、缩进 8/层、chevron 槽 24（字形 12，双字形切换不旋转，叶行同槽放叶图标）、选中条 3×16 圆角 2；
// 状态取色依 SubtleFill 阶梯——悬停/选中 Secondary，悬停于选中、按压未选中 Tertiary。
// 展开 = 子行滑入淡入，收起 = 淡出；键盘：↑↓ 选行、→ 展开或进入子行、← 收起或返回父行、Enter 选中、Home/End。
//
// 契约：
// - model 为 TreeRowsModel：
//   结构角色 depth/expandable/expanded，内容列按 columns 的 {role, width, align} 渲染；
//   width 为 null 的弹性列须是第一列。
// - 标签列（tag）不按列宽排布：聚拢行右缘（右缘预留拇指槽 6）、自适应内容宽、按列序间距 4；须在列序末尾连续。
// - 首列的 subRole 给出次行角色：取值非空的行双行显示（主行 + 次行，行高 44），空值行单行（行高 32）。
// - 行内定位一律不引用 parent（delegate 销毁期绑定解引用会触发 TypeError）。
Item {
    id: root

    required property var theme
    required property var model
    property var columns: []

    signal rowPicked(int row)

    property bool keyboardMode: false
    activeFocusOnTab: true

    function pickCurrent() {
        if (tree.currentIndex >= 0)
            root.rowPicked(tree.currentIndex)
    }

    Keys.onPressed: (event) => {
        root.keyboardMode = true
        switch (event.key) {
        case Qt.Key_Up:
            tree.decrementCurrentIndex()
            root.pickCurrent()
            event.accepted = true
            break
        case Qt.Key_Down:
            tree.incrementCurrentIndex()
            root.pickCurrent()
            event.accepted = true
            break
        case Qt.Key_Right: {
            // WinUI 语义：收起时展开，已展开则进入首个子行
            const cur = tree.currentIndex
            if (!root.model.expand(cur)) {
                // 返回 None 时 QML 侧是 undefined，仅 number 是有效行号
                const child = root.model.first_child_row(cur)
                if (typeof child === "number") {
                    tree.currentIndex = child
                    root.pickCurrent()
                }
            }
            event.accepted = true
            break
        }
        case Qt.Key_Left: {
            // WinUI 语义：展开时收起，已收起则返回父行
            const cur = tree.currentIndex
            if (!root.model.collapse(cur)) {
                // 返回 None 时 QML 侧是 undefined，仅 number 是有效行号
                const parentRow = root.model.parent_row(cur)
                if (typeof parentRow === "number") {
                    tree.currentIndex = parentRow
                    root.pickCurrent()
                }
            }
            event.accepted = true
            break
        }
        case Qt.Key_Return:
        case Qt.Key_Enter:
            root.pickCurrent()
            event.accepted = true
            break
        case Qt.Key_Home:
            tree.currentIndex = 0
            root.pickCurrent()
            event.accepted = true
            break
        case Qt.Key_End:
            tree.currentIndex = tree.count - 1
            root.pickCurrent()
            event.accepted = true
            break
        }
    }

    ListView {
        id: tree
        anchors.fill: parent
        clip: true
        model: root.model
        currentIndex: -1
        boundsBehavior: Flickable.StopAtBounds
        keyNavigationEnabled: false
        ScrollBar.vertical: ScrollBar {
            id: vScroll
            width: 12
            policy: ScrollBar.AsNeeded
            visible: size < 1.0
            topPadding: 4
            bottomPadding: 4
            leftPadding: 6
            rightPadding: 0

            contentItem: Rectangle {
                radius: 3
                color: vScroll.hovered || vScroll.pressed ? root.theme.textSecondary : root.theme.border
            }

            background: Item {}
        }

        add: Transition {
            ParallelAnimation {
                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 150 }
                NumberAnimation { property: "slide"; from: -8; to: 0; duration: 150; easing.type: Easing.OutCubic }
            }
        }
        displaced: Transition {
            NumberAnimation { properties: "x,y"; duration: 150; easing.type: Easing.OutCubic }
        }
        remove: Transition {
            NumberAnimation { property: "opacity"; to: 0; duration: 100 }
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

            property real slide: 0

            readonly property int indent: depth * 8
            readonly property bool isCurrent: tree.currentIndex === row.index

            readonly property string subRoleName: root.columns.length > 0 ? (root.columns[0].subRole ?? "") : ""
            readonly property string subText: row.subRoleName ? (row.model[row.subRoleName] ?? "") : ""
            readonly property bool twoLine: row.subText !== ""

            // 标签簇定位于行右缘的拇指槽内缘；定宽非标签列自标签簇左缘逆向排列，弹性列自 chevron 槽后起排
            function trailingX(idx) {
                let x = tagRow.x - 8
                for (let i = root.columns.length - 1; i > idx; --i)
                    if (!root.columns[i].tag)
                        x -= root.columns[i].width + 8
                return x - root.columns[idx].width
            }
            function columnX(idx, indent) {
                return idx === 0 ? indent + 24 : trailingX(idx)
            }
            function columnWidth(idx, indent) {
                const spec = root.columns[idx]
                if (spec.width !== null && spec.width !== undefined)
                    return spec.width
                // 弹性列右缘止于首个非标签定宽列，无则止于标签簇
                let right = tagRow.x - 8
                let gap = 0
                for (let i = idx + 1; i < root.columns.length; ++i) {
                    if (!root.columns[i].tag) {
                        right = trailingX(i)
                        gap = 8
                        break
                    }
                }
                return right - gap - columnX(idx, indent)
            }

            width: tree.width
            height: row.twoLine ? 44 : 32
            transform: Translate { y: row.slide }

            Rectangle {
                id: bg
                x: 4
                y: 2
                width: row.width - 8
                height: row.height - 4
                radius: 4
                // WinUI 状态矩阵：按压未选中 / 悬停于选中 → Tertiary；其余悬停与选中 → Secondary
                color: rowMouse.pressed || chevronMouse.pressed
                        ? (row.isCurrent ? root.theme.fillHover : root.theme.fillPressed)
                    : row.isCurrent && rowMouse.containsMouse ? root.theme.fillPressed
                    : row.isCurrent || rowMouse.containsMouse ? root.theme.fillHover
                    : "transparent"

                // 选中条绘制在本行内：随行而定，不依赖 highlight 定位
                Rectangle {
                    x: 0
                    y: (bg.height - height) / 2
                    width: 3
                    height: 16
                    radius: 2
                    color: root.theme.accent
                    visible: row.isCurrent
                }

                // 键盘焦点环（仅键盘模式显示，对齐 WinUI 的 focus visual）
                Rectangle {
                    x: 0
                    y: 0
                    width: bg.width
                    height: bg.height
                    radius: 6
                    color: "transparent"
                    border.color: root.theme.accent
                    border.width: 2
                    visible: root.keyboardMode && root.activeFocus && row.isCurrent
                }

                Text {
                    id: chevronGlyph
                    x: row.indent + 4
                    y: (bg.height - height) / 2
                    width: 12
                    height: 12
                    visible: row.expandable
                    text: row.expanded ? root.theme.chevronExpanded : root.theme.chevronCollapsed
                    font.family: root.theme.iconFontFamily
                    font.pixelSize: 12
                    color: rowMouse.pressed || chevronMouse.pressed ? root.theme.textSecondary : root.theme.text
                }

                // 叶行无 chevron，同槽放叶图标；与 chevron 同字形族同尺寸
                Text {
                    id: leafGlyph
                    x: row.indent + 4
                    y: (bg.height - height) / 2
                    width: 12
                    height: 12
                    visible: !row.expandable
                    text: root.theme.leafGlyph
                    font.family: root.theme.iconFontFamily
                    font.pixelSize: 12
                    color: root.theme.textSecondary
                }

                // 标签列聚拢行右缘，按列序依次排列；右缘预留拇指槽，避让滚动条
                Row {
                    id: tagRow
                    anchors.right: bg.right
                    anchors.rightMargin: 6
                    y: (bg.height - height) / 2
                    spacing: 4

                    Repeater {
                        model: root.columns.filter((c) => c.tag === true)
                        delegate: Tag {
                            required property var modelData

                            theme: root.theme
                            text: row.model[modelData.role] ?? ""
                            tone: modelData.toneRole ? (row.model[modelData.toneRole] ?? "") : ""
                            fontPointSize: root.theme.fontPointSize - 1
                            minWidth: 26
                        }
                    }
                }

                Repeater {
                    model: root.columns
                    delegate: Item {
                        id: cell
                        required property int index
                        required property var modelData

                        readonly property bool isTag: modelData.tag === true
                        readonly property string cellText: row.model[modelData.role] ?? ""
                        readonly property bool withSub: cell.index === 0 && row.twoLine

                        visible: !cell.isTag
                        x: cell.isTag ? 0 : row.columnX(index, row.indent)
                        y: (bg.height - height) / 2
                        width: cell.isTag ? 0 : row.columnWidth(index, row.indent)
                        height: cell.withSub ? 36 : 20

                        Text {
                            id: plainLabel
                            x: 0
                            y: 0
                            width: cell.width
                            height: cell.withSub ? 18 : cell.height
                            text: cell.cellText
                            textFormat: Text.PlainText
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: cell.modelData.align === "right" ? Text.AlignRight : Text.AlignLeft
                            elide: cell.index === 0 ? Text.ElideRight : Text.ElideNone
                            font.family: root.theme.fontFamily
                            font.pointSize: root.theme.fontPointSize
                            color: cell.index === 0
                                ? ((rowMouse.pressed || chevronMouse.pressed) ? root.theme.textSecondary : root.theme.text)
                                : root.theme.textSecondary
                        }

                        // 次行：同号次要色，与主行紧凑排布为双行
                        Text {
                            id: subLabel
                            visible: cell.withSub
                            x: 0
                            y: 18
                            width: cell.width
                            height: 18
                            text: row.subText
                            textFormat: Text.PlainText
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            font.family: root.theme.fontFamily
                            font.pointSize: root.theme.fontPointSize
                            color: root.theme.textSecondary
                        }
                    }
                }

                MouseArea {
                    id: rowMouse
                    x: 0
                    y: 0
                    width: bg.width
                    height: bg.height
                    hoverEnabled: true
                    onClicked: {
                        root.keyboardMode = false
                        tree.currentIndex = row.index
                        root.forceActiveFocus()
                        root.rowPicked(row.index)
                    }
                    onDoubleClicked: {
                        if (row.expandable)
                            root.model.toggle(row.index)
                    }
                }

                // chevron 命中区叠于行命中区之上，单击只切换展开，不选中
                MouseArea {
                    id: chevronMouse
                    x: row.indent
                    y: 0
                    width: 24
                    height: bg.height
                    visible: row.expandable
                    onClicked: {
                        root.keyboardMode = false
                        root.forceActiveFocus()
                        root.model.toggle(row.index)
                    }
                }
            }
        }
    }
}
