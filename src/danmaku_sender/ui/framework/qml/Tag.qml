pragma ComponentBehavior: Bound

import QtQuick

// 小标签：GitHub 标签（Primer IssueLabel）形制——圆角 full、内边距 4、描边 1；
// 字重常规（GitHub 标签字重 semibold 是英文小字号的取舍，中文与数字语境下加粗观感过重）。
//
// 契约：
// - theme 为令牌桥；text 为标签文字。
// - tone 为健康档取值 good / warn / bad / neutral，配色取 theme.healthColors[tone][dark ? "dark" : "light"]，
//   空档与未知档回落 neutral。三元组 {fg, bg, border} 由 HealthColors 折算（深色 GitHub 公式、浅色柔化变体）。
// - 尺寸由调用方指定：fontPointSize 为字号（默认取 theme 值），minWidth 为最小宽下限（默认 0，不设下限），高可由 height 覆盖（默认 16）；
//   implicitWidth = max(文字宽, minWidth) + 10，圆角取高度之半。
Rectangle {
    id: root

    required property var theme
    required property string text
    property string tone: ""
    property int fontPointSize: root.theme.fontPointSize
    property real minWidth: 0

    readonly property var tint: {
        const table = root.theme.healthColors
        const entry = table[root.tone] ?? table["neutral"]
        return entry[root.theme.dark ? "dark" : "light"]
    }
    readonly property color fg: root.tint.fg
    readonly property color bg: root.tint.bg
    readonly property color borderColor: root.tint.border

    implicitWidth: Math.max(label.implicitWidth, root.minWidth) + 10
    implicitHeight: 16
    radius: root.height / 2
    color: root.bg
    border.width: 1
    border.color: root.borderColor

    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        textFormat: Text.PlainText
        font.family: root.theme.fontFamily
        font.pointSize: root.fontPointSize
        color: root.fg
    }
}
