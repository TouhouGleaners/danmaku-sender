pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

// 通用 Fluent 风格树形层级视图 (WinUI 3 TreeView)
//
// 设计与交互规范：
// 1. 结构与度量：
//    - 单行标准高 32px（若首列带有次行副标题则自动扩展至 44px），行内四周留白 2px，圆角 4px。
//    - 缩进深度：每层按 8px 紧凑递增（对齐现代开发工具如 VS Code 的紧致层级感）。
//    - 节点折叠与展开：由左侧 24px 宽度的独立点击热区触发，使用双字形无旋转切换。
//      叶子节点无箭头，而是在同一占位处显示文档图标，确保文字起始线垂直对齐。
// 2. 选中指示器：
//    - 行左侧直接绘制 3x16px 圆角高亮滑块，不依赖 ListView.highlight 的几何移动，杜绝位移延迟。
//    - 悬停与按压态严格遵循 WinUI 3 SubtleFill 色阶层次。
// 3. 键盘操作支持：
//    - 方向键 ↑ / ↓：切换选中行。
//    - 方向键 →：若处于折叠状态则展开当前节点；若已展开则焦点顺次进入首个子节点。
//    - 方向键 ←：若处于展开状态则折叠当前节点；若已折叠则焦点返回父节点。
//    - 回车键 (Enter / Return)：激活选中项（触发 rowPicked 信号）。
//
// 避坑备忘：
// - 委托组件销毁期间，内部属性绑定若引用 parent 会触发 Qt TypeError，因此行内坐标统一基于局部 id 算式定位。

Item {
    id: root

    required property var theme
    required property var model
    property var columns: []

    signal rowPicked(int row)

    // 区分键盘导航与鼠标点击（键盘模式下显示焦点环，对齐 WinUI FocusVisuals 行为）
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
            // 展开当前项；若已展开则进入第一个子项
            const cur = tree.currentIndex
            if (!root.model.expand(cur)) {
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
            // 折叠当前项；若已折叠则回退到父项
            const cur = tree.currentIndex
            if (!root.model.collapse(cur)) {
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

        // 垂直滚动条
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
                color: vScroll.hovered || vScroll.pressed ? root.theme.TextFillColorSecondary : root.theme.ControlStrokeColorDefault
            }

            background: Item {}
        }

        // 展开与折叠动效（平滑淡入滑出）
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

            // 次行副标题：仅首列支持，若存在则行高扩展至 44px
            readonly property string subRoleName: root.columns.length > 0 ? (root.columns[0].subRole ?? "") : ""
            readonly property string subText: row.subRoleName ? (row.model[row.subRoleName] ?? "") : ""
            readonly property bool twoLine: row.subText !== ""

            // 布局算法：
            // 1. 右侧标签簇定位于行最右端（右边预留 6px 避免遮挡悬浮滚动条）。
            // 2. 固定宽度的非标签列，从标签簇的左边缘开始【自右向左】逆向递减计算 X 坐标。
            // 3. 第 0 列（弹性文本列）自左侧展开图标右缘开始，宽度自适应填满中间所有剩余空间。
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

                color: {
                    // 按压状态：点击未选态用 Tertiary，悬停已选态用 Secondary
                    if (rowMouse.pressed || chevronMouse.pressed) {
                        return row.isCurrent ? root.theme.SubtleFillColorSecondary : root.theme.SubtleFillColorTertiary;
                    }
                    // 悬停且已选态：用 Tertiary
                    if (row.isCurrent && rowMouse.containsMouse) {
                        return root.theme.SubtleFillColorTertiary;
                    }
                    // 常态已选 或 悬停未选：用 Secondary
                    if (row.isCurrent || rowMouse.containsMouse) {
                        return root.theme.SubtleFillColorSecondary;
                    }
                    // 默认透明
                    return "transparent";
                }

                // 选中指示器：行左侧绘制 3x16px 圆角高亮滑块，避免使用 ListView.highlight 的几何移动，杜绝位移延迟
                Rectangle {
                    x: 0
                    y: (bg.height - height) / 2
                    width: 3
                    height: 16
                    radius: 2
                    color: root.theme.AccentFillColorDefault
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
                    border.color: root.theme.AccentFillColorDefault
                    border.width: 2
                    visible: root.keyboardMode && root.activeFocus && row.isCurrent
                }

                // 展开/收起箭头图标（仅在含有子节点时可见）
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
                    color: rowMouse.pressed || chevronMouse.pressed ? root.theme.TextFillColorSecondary : root.theme.TextFillColorPrimary
                }

                // 叶子节点文档占位图标（与箭头共享相同位置，保证文字始终垂直对齐）
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
                    color: root.theme.TextFillColorSecondary
                }

                // 右侧标签组（贴右排列，并留出避让滚动条的 6px 右边距）
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

                // 常规文本单元格排布
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

                        // 主标题文本
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
                                ? ((rowMouse.pressed || chevronMouse.pressed) ? root.theme.TextFillColorSecondary : root.theme.TextFillColorPrimary)
                                : root.theme.TextFillColorSecondary
                        }

                        // 次行副标题文本（仅首列且存在副标题时展开双行）
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
                            color: root.theme.TextFillColorSecondary
                        }
                    }
                }

                // 整行点击交互区（选中该行并上报）
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

                // 展开/收起点击：仅切换展开状态，不改变当前选中项
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
