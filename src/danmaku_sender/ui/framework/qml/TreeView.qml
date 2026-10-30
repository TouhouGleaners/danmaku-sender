pragma ComponentBehavior: Bound

import QtQuick

// 通用 Fluent 风格树视图。度量与状态照 WinUI 3 TreeView：
// 行槽 32（内容 28 + 上下边距 2）、内容圆角 4、缩进 16/层、chevron 槽 40（字形 12，
// 双字形切换不旋转）、选中条 3×16 圆角 2；状态取色照 SubtleFill 阶梯——
// 悬停/选中 Secondary，悬停于选中、按压未选中 Tertiary。
// 展开 = 子行滑入淡入，收起 = 淡出；键盘：↑↓ 选行、→ 展开或下潜、← 收起或回父、Enter 选中、Home/End。
//
// 契约：
// - model 为 TreeRowsModel：结构角色 depth/expandable/expanded，
//   内容列按 columns 的 {role, width, align} 渲染；width 为 null 的弹性列须是第一列。
// - 行内定位一律不引用 parent（delegate 销毁期绑定解引用会刷 TypeError）。
Item {
    id: root

    required property var theme
    required property var model
    property var columns: []

    signal rowPicked(int row)

    property bool keyboardMode: false

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
        const hasFollowing = root.columns.length > 1
        const right = hasFollowing ? trailingX(1) : tree.width - 8
        return right - (hasFollowing ? 8 : 0) - columnX(idx, indent)
    }
    function pickCurrent() {
        if (tree.currentIndex >= 0)
            root.rowPicked(tree.currentIndex)
    }

    ListView {
        id: tree
        anchors.fill: parent
        clip: true
        model: root.model
        currentIndex: -1
        boundsBehavior: Flickable.StopAtBounds
        keyNavigationEnabled: false
        activeFocusOnTab: true

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
                // WinUI 语义：收起时展开，已展开则下潜到首个子行
                const cur = tree.currentIndex
                if (!root.model.expand(cur)) {
                    const child = root.model.first_child_row(cur)
                    if (child !== null) {
                        tree.currentIndex = child
                        root.pickCurrent()
                    }
                }
                event.accepted = true
                break
            }
            case Qt.Key_Left: {
                // WinUI 语义：展开时收起，已收起则回父行
                const cur = tree.currentIndex
                if (!root.model.collapse(cur)) {
                    const parentRow = root.model.parent_row(cur)
                    if (parentRow !== null) {
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

        delegate: Item {
            id: row

            required property int index
            required property int depth
            required property bool expandable
            required property bool expanded
            required property var model

            property real slide: 0

            readonly property int indent: depth * 16
            readonly property bool isCurrent: tree.currentIndex === row.index

            width: tree.width
            height: 32
            transform: Translate { y: row.slide }

            Rectangle {
                id: bg
                x: 4
                y: 2
                width: row.width - 8
                height: 28
                radius: 4
                // WinUI 状态矩阵：按压未选中 / 悬停于选中 → Tertiary；其余悬停与选中 → Secondary
                color: rowMouse.pressed || chevronMouse.pressed
                        ? (row.isCurrent ? root.theme.fillHover : root.theme.fillPressed)
                    : row.isCurrent && rowMouse.containsMouse ? root.theme.fillPressed
                    : row.isCurrent || rowMouse.containsMouse ? root.theme.fillHover
                    : "transparent"

                // 选中条画在本行内（WinUI 式）：随行而定，不依赖 highlight 定位
                Rectangle {
                    x: 0
                    y: 6
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
                    visible: root.keyboardMode && tree.activeFocus && row.isCurrent
                }

                Text {
                    id: chevronGlyph
                    x: row.indent + 14
                    y: (bg.height - height) / 2
                    width: 12
                    height: 12
                    visible: row.expandable
                    text: row.expanded ? root.glyphExpanded : root.glyphCollapsed
                    font.family: root.theme.iconFontFamily
                    font.pixelSize: 12
                    color: rowMouse.pressed || chevronMouse.pressed ? root.theme.textSecondary : root.theme.text
                }

                Repeater {
                    model: root.columns
                    delegate: Text {
                        required property int index
                        required property var modelData

                        x: root.columnX(index, row.indent)
                        y: (bg.height - height) / 2
                        width: root.columnWidth(index, row.indent)
                        text: row.model[modelData.role] ?? ""
                        horizontalAlignment: modelData.align === "right" ? Text.AlignRight : Text.AlignLeft
                        elide: index === 0 ? Text.ElideRight : Text.ElideNone
                        font.family: root.theme.fontFamily
                        font.pointSize: root.theme.fontPointSize
                        color: index === 0
                            ? ((rowMouse.pressed || chevronMouse.pressed) ? root.theme.textSecondary : root.theme.text)
                            : root.theme.textSecondary
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
                        tree.forceActiveFocus()
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
                    y: 0
                    width: 40
                    height: bg.height
                    visible: row.expandable
                    onClicked: {
                        root.keyboardMode = false
                        tree.forceActiveFocus()
                        root.model.toggle(row.index)
                    }
                }
            }
        }
    }
}
