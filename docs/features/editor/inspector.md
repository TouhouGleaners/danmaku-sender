# 单条编辑与属性检查器

编辑器采用 **7:3 左右分屏布局**：左侧为弹幕列表，右侧为属性检查器面板。选中列表中的任意一行，即可在右侧面板查看和修改该条弹幕的所有属性。

---

## 属性检查器面板

选中一条弹幕后，右侧面板会显示以下可编辑属性：

| 属性 | 控件类型 | 说明 |
|:-----|:---------|:-----|
| **出现时间** | 数值输入框 | 毫秒级精度，单位为秒（例如 `12.345`）。修改后列表会按时间重新排序。 |
| **弹幕模式** | 下拉选择 | 滚动 (1)、底端 (4)、顶端 (5)。 |
| **弹幕字号** | 下拉选择 | 预设三档：标准 (25)、小 (18)、大 (36)。如果弹幕使用了自定义字号，会自动识别并显示。 |
| **弹幕颜色** | 色块按钮 | 点击弹出调色板，左下角已集成 B 站网页端同款 **14 色画板**。 |
| **弹幕内容** | 多行文本框 | 直接编辑文字内容，自动去除换行符。 |

### 实时预览

属性检查器顶部有一个 **实时预览区域**（深色背景），会根据你当前编辑的属性实时渲染弹幕效果：

- 滚动模式：弹幕居中显示
- 底端模式：弹幕贴近底部
- 顶端模式：弹幕贴近顶部
- 颜色和字号变化会立即反映在预览中

---

## 编辑操作

### 修改单条弹幕属性

1. 在左侧列表中 **单击** 选中一条弹幕。
2. 在右侧属性检查器中修改属性。
3. 点击 **[保存属性修改]** 按钮。

!!! warning "必须点击保存"
    修改属性后，**必须点击 [保存属性修改] 按钮**，改动才会正式写入暂存区并触发撤销记录。未保存的修改在切换选中行时会丢失。

### 双击编辑内容

双击列表中的「弹幕内容」列（第 4 列），会弹出一个独立的编辑对话框，适合编辑较长的弹幕文本。

在编辑对话框中：

- 如果将内容 **清空** 并确认，程序会询问是否直接删除该条弹幕。
- 修改后自动保存，无需再点属性检查器的保存按钮。

---

## 插入新弹幕

在列表中右键某一行，可以选择：

| 操作 | 说明 |
|:-----|:-----|
| **在上方插入新弹幕** | 在选中行的上方插入一条空白弹幕，随后弹出编辑对话框填写内容 |
| **在下方插入新弹幕** | 在选中行的下方插入一条空白弹幕，随后弹出编辑对话框填写内容 |

插入后会自动切换到「预览模式」，方便你看到新弹幕在整体列表中的位置。

---

## 删除弹幕

### 右键删除

右键选中一条或多条弹幕，选择 **「删除选中条目」**。

### 清空内容触发删除

双击编辑弹幕内容时，如果将内容清空并确认，程序会询问「内容为空，是否直接删除该条弹幕？」。

---

## 多选操作

列表支持 **多选**（按住 `Ctrl` 或 `Shift` 点击），多选后可以：

- 批量删除
- 批量平移时间轴（右键 → 平移选中弹幕的时间轴）

---

## B 站标准色板

调色板左下角集成了 B 站网页端的 14 种标准弹幕颜色：

| 色块 | 色号 | 名称 |
|:----:|:----:|:----:|
| <span style="display:inline-block;width:16px;height:16px;background:#FE0302;border-radius:3px;vertical-align:middle"></span> | `#FE0302` | 红 |
| <span style="display:inline-block;width:16px;height:16px;background:#FF7204;border-radius:3px;vertical-align:middle"></span> | `#FF7204` | 橙 |
| <span style="display:inline-block;width:16px;height:16px;background:#FFAA02;border-radius:3px;vertical-align:middle"></span> | `#FFAA02` | 金 |
| <span style="display:inline-block;width:16px;height:16px;background:#FFD302;border-radius:3px;vertical-align:middle"></span> | `#FFD302` | 亮黄 |
| <span style="display:inline-block;width:16px;height:16px;background:#FFFF00;border-radius:3px;vertical-align:middle"></span> | `#FFFF00` | 黄 |
| <span style="display:inline-block;width:16px;height:16px;background:#A0EE00;border-radius:3px;vertical-align:middle"></span> | `#A0EE00` | 亮绿 |
| <span style="display:inline-block;width:16px;height:16px;background:#00CD00;border-radius:3px;vertical-align:middle"></span> | `#00CD00` | 绿 |
| <span style="display:inline-block;width:16px;height:16px;background:#019899;border-radius:3px;vertical-align:middle"></span> | `#019899` | 青 |
| <span style="display:inline-block;width:16px;height:16px;background:#4266BE;border-radius:3px;vertical-align:middle"></span> | `#4266BE` | 蓝 |
| <span style="display:inline-block;width:16px;height:16px;background:#89D5FF;border-radius:3px;vertical-align:middle"></span> | `#89D5FF` | 浅蓝 |
| <span style="display:inline-block;width:16px;height:16px;background:#CC0273;border-radius:3px;vertical-align:middle"></span> | `#CC0273` | 紫 |
| <span style="display:inline-block;width:16px;height:16px;background:#222222;border-radius:3px;vertical-align:middle"></span> | `#222222` | 黑 |
| <span style="display:inline-block;width:16px;height:16px;background:#9B9B9B;border-radius:3px;vertical-align:middle"></span> | `#9B9B9B` | 灰 |
| <span style="display:inline-block;width:16px;height:16px;background:#FFFFFF;border:1px solid #ccc;border-radius:3px;vertical-align:middle"></span> | `#FFFFFF` | 白 |

这些色块是 B 站弹幕系统支持的标准颜色，使用这些颜色可以确保弹幕在视频上的显示效果与预期一致。
