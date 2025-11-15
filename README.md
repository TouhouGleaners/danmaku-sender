# B站弹幕发射器 (BiliDanmakuSender)

<p align="center">
  <img src="https://img.shields.io/github/v/release/TouhouGleaners/danmaku-sender" alt="Latest Release">
  <img src="https://img.shields.io/github/downloads/TouhouGleaners/danmaku-sender/total" alt="Total Downloads">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/github/license/TouhouGleaners/danmaku-sender" alt="License">
</p>

B站弹幕发射工具，基于**Python 3.12**。  
使用 Python 和 `ttkbootstrap` 构建。它能帮助您将本地的B站XML弹幕文件重新发送到指定的视频分P中，实现弹幕的备份、迁移和恢复。

## ✨ 主要特性

*   **🍪 Cookie 登录**: 安全、便捷地使用您的B站账户。
*   **🎯 精准分P**: 自动获取视频所有分P，确保弹幕发送到正确位置。
*   **🚀 延时发送**: 自定义弹幕发送延迟，模拟真实用户行为，提高成功率。
*   **✅ 弹幕校验**: 在发送前检查弹幕格式，并提供实时编辑和删除功能。
*   **🔭 弹幕监视**: 实时比对线上弹幕与本地文件，跟踪弹幕匹配进度。
*   **📦 开箱即用**: 提供 Windows 打包版，无需安装 Python 环境。


## 🚀 安装与运行

### 📦 打包版 (Windows 用户推荐)

无需安装任何环境依赖，下载后直接运行。

<p align="center">
  <a href="https://github.com/TouhouGleaners/danmaku-sender/releases/latest">
    <img src="https://img.shields.io/badge/下载最新版-BiliDanmakuSender.exe-brightgreen?style=for-the-badge&logo=github" alt="下载最新版">
  </a>
</p>

### 🐍 源码版 (开发者)

*   **Python 版本:** Python 3.12 或更高版本
*   **安装依赖:**
    ```bash
    git clone https://github.com/TouhouGleaners/danmaku-sender.git
    cd danmaku-sender
    pip install -r requirements.txt
    ```
*   **运行:**
    ```bash
    python main_app.py
    ```

## 📖 使用指南
### 🔑 1. 准备工作：获取 Cookie

1.  在浏览器（推荐Chrome/Edge）中登录Bilibili。
2.  按 `F12` 打开“开发者工具”。
3.  切换到 **"应用" (Application)** 标签页。
4.  在左侧菜单，找到 **"存储" (Storage) -> "Cookie" -> `https://www.bilibili.com`**。
5.  在右侧列表中找到 `SESSDATA` 和 `bili_jct`，复制它们的 **值 (Value)**。

### 🚀 2. 发送弹幕 (核心流程)

1.  **填写凭证**: 在 "弹幕发射器" 标签页，将上一步获取的 `SESSDATA` 和 `bili_jct` 粘贴到对应输入框。
2.  **获取分P**: 输入目标视频的 **BV号**，点击 **“获取分P”** 按钮。
3.  **选择分P**: 在下拉框中选择你要发送弹幕的目标分P。
4.  **选择文件**: 点击 **“选择文件”**，加载你本地的弹幕XML文件。
5.  **设置延迟**: 根据需要调整最小和最大延迟（建议20-25秒）。
6.  **开始任务**: 点击 **“开始任务”** 按钮。任务进行中可以点击 **“紧急停止”** 来终止。

### 🔧 3. (可选) 校验和修改弹幕

1.  切换到 "弹幕校验器" 标签页。
2.  确保已在 "发射器" 页面加载了视频分P和弹幕文件。
3.  点击 **“开始验证”**，所有不合规的弹幕都会被列出。
4.  双击弹幕内容可直接 **编辑**，或选中后点击 **删除**。
5.  操作完成后，点击 **“应用所有修改”**。

### 🔭 4. (可选) 监视匹配进度

1.  切换到 "弹幕监视器" 标签页。
2.  点击 **“开始监视”**，程序将定期拉取线上弹幕并与你的本地文件进行比对。

## 🤝 贡献

我们非常欢迎任何形式的贡献！无论是提交 Bug 反馈、功能建议还是代码贡献。

请参考我们的 [**贡献指南 (CONTRIBUTING.md)**](CONTRIBUTING.md) 来了解详细流程。

*   [**提交 PR**](https://github.com/TouhouGleaners/danmaku-sender/pulls)
*   [**报告 Issue**](https://github.com/TouhouGleaners/danmaku-sender/issues)

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源。