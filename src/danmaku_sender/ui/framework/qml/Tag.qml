pragma ComponentBehavior: Bound

import QtQuick

// 轻量状态标签胶囊 (Pill Tag)
//
// 设计与色彩规范：
// 1. 几何形态：完全圆角胶囊（圆角半径等于高度的一半），字重常规，尺寸随文字内容自适应。
// 2. 配色系统（对齐 GitHub Primer 标签与健康度色板规范）：
//    - tone 支持四种状态：good (优/成功) / warn (警/待定) / bad (坏/错误) / neutral (中性)。
//    - 浅色模式：采用低饱和淡色背景搭配同色系深色文本（对比度高，无描边）。
//    - 深色模式：采用 18% 低透明度背景搭配提亮后的高饱和文字与边框，防止大面积亮色在暗色背景下刺眼。
//
// 属性与使用：
// - theme: 注入的 QmlPaletteBridge 实例。
// - text: 标签展示的文字内容。
// - tone: 语义状态色阶（"good" | "warn" | "bad" | "neutral"），缺省或未匹配时回退为中性灰。
// - fontPointSize: 字号大小，默认使用主题基准字号。
// - minWidth / padding: 最小宽度约束与左右内边距，方便表格列对齐。
// - 尺寸公式：implicitWidth = max(文字宽, minWidth) + 2 * padding；高度可由 height 覆盖（默认 16），圆角取高度之半。

Rectangle {
    id: root

    required property var theme
    required property string text
    property string tone: ""
    property int fontPointSize: root.theme.fontPointSize
    property real minWidth: 0
    property real padding: 5

    // 根据深浅色模式与语义状态提取预先计算好的色阶三元组 (fg, bg, border)
    readonly property var tint: {
        const table = root.theme.healthColors
        const entry = table[root.tone] ?? table["neutral"]
        return entry[root.theme.dark ? "dark" : "light"]
    }
    readonly property color fg: root.tint.fg
    readonly property color bg: root.tint.bg
    readonly property color borderColor: root.tint.border

    // 宽度自适应内容，但在 minWidth 处截取下限，保证短文字标签视觉稳定
    implicitWidth: Math.max(label.implicitWidth, root.minWidth) + root.padding * 2
    implicitHeight: 16
    radius: root.height / 2
    color: root.bg

    // 浅色模式依靠底色反差无需描边；深色模式采用透明晕底，必须保留 1px 细边框勾勒轮廓
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
