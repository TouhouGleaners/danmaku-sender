pragma ComponentBehavior: Bound

import QtQuick

// 小标签：圆角 full、字重常规，内边距由调用方按场景给（padding）。
//
// 契约：
// - theme 为 QmlPaletteBridge；text 为标签文字。
// - tone 为健康档取值 good / warn / bad / neutral，配色取 theme.healthColors[tone][dark ? "dark" : "light"]，
//   空档与未知档回落 neutral。三元组 {fg, bg, border} 由 HealthColors 折算：浅色淡底深字、深色晕底亮字。
// - 描边仅深色模式有（1）；浅色不留描边。
// - 尺寸由调用方指定：
//   fontPointSize 为字号（默认取 theme 值），
//   minWidth 为最小宽下限（默认 0，不设下限），
//   padding 为文字到左右缘的内边距（默认 5），
//   高可由 height 覆盖（默认 16）；
//   implicitWidth = max(文字宽, minWidth) + 2 * padding，圆角取高度之半。
Rectangle {
    id: root

    required property var theme
    required property string text
    property string tone: ""
    property int fontPointSize: root.theme.fontPointSize
    property real minWidth: 0
    property real padding: 5

    readonly property var tint: {
        const table = root.theme.healthColors
        const entry = table[root.tone] ?? table["neutral"]
        return entry[root.theme.dark ? "dark" : "light"]
    }
    readonly property color fg: root.tint.fg
    readonly property color bg: root.tint.bg
    readonly property color borderColor: root.tint.border

    implicitWidth: Math.max(label.implicitWidth, root.minWidth) + root.padding * 2
    implicitHeight: 16
    radius: root.height / 2
    color: root.bg
    border.width: root.theme.dark ? 1 : 0
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
