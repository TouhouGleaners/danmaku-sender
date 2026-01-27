# B站弹幕发射器 (BiliDanmakuSender)

<p align="center">
  <img src="https://img.shields.io/github/v/tag/TouhouGleaners/danmaku-sender?label=Pre-Release&color=orange" alt="Pre-release">
  <img src="https://img.shields.io/github/v/release/TouhouGleaners/danmaku-sender?label=Release&color=bright-green" alt="Release">
  <img src="https://img.shields.io/github/downloads/TouhouGleaners/danmaku-sender/total?label=Downloads" alt="Total Downloads">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/UI-PySide6-41cd52.svg" alt="PySide6">
  <img src="https://img.shields.io/badge/Build-Nuitka-cea113.svg" alt="Nuitka">
  <img src="https://img.shields.io/github/license/TouhouGleaners/danmaku-sender?label=License" alt="License">
</p>

**B站弹幕发射器** 是一款基于 **Python 3.12** 与 **PySide6 (Qt)** 的弹幕补档工具，并采用 Nuitka 编译以获得最佳的运行性能。

它专为**弹幕搬运、备份恢复及大规模补档**场景设计，内置了本地数据库管理系统，支持断点续传、状态追踪和智能风控规避，是重建往日弹幕环境的有力工具。

---

## ✨ 核心特性

*   **💾 本地历史记录 (SQLite)**：内置轻量级数据库，自动记录每一条发送成功的弹幕。支持记录**弹幕状态**（待验证/已存活/已丢失），从此告别盲发。
*   **⏭️ 智能断点续传**：发送前自动比对数据库指纹。如果发现相同内容、颜色、时间的弹幕已发送且处于“待验证”或“已存活”状态，将自动跳过，实现完美的**断点续传**与**防重复发送**。
*   **🛡️ 强力风控规避**：
    *   **WBI 签名**：原生支持 B 站最新的 WBI 签名算法，请求更稳定。
    *   **拟人化延迟**：支持随机间隔 + **爆发模式**（如：每发送 5 条休息 30 秒），模拟人工操作。
*   **🛠️ 交互式校验器**：
    *   支持**批量修复**（一键去除换行符、截断过长文本）。
    *   支持**撤销**（Undo）操作，修改更安心。
    *   支持双击直接编辑弹幕内容。
*   **📊 全局状态监视**：监视器与数据库联动，实时审计弹幕存活率（Total / Verified / Lost），自动核销“待验证”状态的弹幕。
*   **⚡ Nuitka 高性能构建**：采用 Nuitka 编译为机器码，启动速度更快，运行更稳定，无需单独安装 Python 环境。
*   **💻 系统级优化**：
    *   **防休眠**：任务运行期间自动阻止 Windows 系统休眠。
    *   **网络适配**：支持强制直连或使用系统代理。

---

## 🚀 安装与运行

### 📦 打包版 (推荐普通用户)

下载后直接运行 `BiliDanmakuSender.exe`，无需安装 Python 环境。

<p align="center">
  <a href="https://github.com/TouhouGleaners/danmaku-sender/releases/latest">
    <img src="https://img.shields.io/badge/⬇️_下载最新版-Windows_x64-00a1d6?style=for-the-badge&logo=windows" alt="下载最新版">
  </a>
</p>

### 🐍 源码版 (开发者)

如果您希望修改代码或自行构建，请按以下步骤操作。本项目使用 `pyproject.toml` 管理依赖。

```bash
# 1. 克隆仓库
git clone https://github.com/TouhouGleaners/danmaku-sender.git
cd danmaku-sender

# 2. 安装依赖 (推荐使用虚拟环境)
# 使用 pip 安装当前目录下的依赖配置
pip install .

# 或者安装为编辑模式 (Editable mode)
pip install -e .

# 3. 运行
python -m danmaku_sender.main
```

---

## 📖 使用指南

### 1. 全局设置 (准备工作)
首次使用请先前往 **“全局设置”** 标签页：
*   **身份凭证**：填写您的 `SESSDATA` 和 `bili_jct`（Cookie），程序会自动加密存储到系统密钥环中。
*   **网络与系统**：根据需要勾选“阻止电脑休眠”或配置代理策略。

### 2. 发送弹幕 (核心流程)
1.  **加载目标**：输入 **BV 号** 或视频链接，点击“获取分 P”，选择目标分 P。
2.  **加载文件**：选择本地 XML 弹幕文件。
3.  **配置策略**：
    *   设置随机延迟（如 3.0s - 5.0s）。
    *   建议开启 **“爆发模式”**（例如：每 5 条休息 20 秒）以降低封控概率。
    *   ✅ **勾选“启用断点续传”**：程序将自动跳过数据库中已记录的弹幕。
4.  点击 **“开始发送”**。

### 3. 数据审计 (校验与监视)
*   **弹幕校验器**：
    *   在发送前，使用校验器扫描文件。
    *   使用右键菜单或“批量修复”按钮处理**过长、含换行符**的弹幕。
    *   点击“应用所有修改”将清洗后的数据同步回发送队列。
*   **弹幕监视器**：
    *   选择正在发送的分 P，点击“开始监视”。
    *   监视器会定期获取线上列表，将本地数据库中 **Pending (待验证)** 的弹幕更新为 **Verified (已存活)**。

### 4. 历史记录
*   前往 **“弹幕历史记录”** 标签页。
*   支持按关键词、BV 号、弹幕状态（存活/丢失）进行筛选查询。
*   双击条目可查看详细档案（CID、发送时间、颜色字号等）。

---

## ❓ 常见问题

**Q: 为什么显示“SESSDATA 无效”？**
A: B 站 Cookie 有有效期（通常半个月到一个月）。如果失效，请重新提取并在“全局设置”中更新。

**Q: “断点续传”是如何工作的？**
A: 程序会将发送成功的弹幕指纹（内容+时间+颜色等）存入 SQLite 数据库。下次发送相同文件时，程序会查询数据库，如果发现该弹幕已存在于数据库中，就会直接跳过，避免重复发送。

**Q: 遇到“致命错误”任务停止了怎么办？**
A: 如果是网络超时，程序通常会自动重试或跳过。如果是 `412` 等严重错误，程序会触发熔断机制停止任务，请检查账号状态或网络环境后尝试继续发送。

---

## 🤝 贡献

本项目基于 [MIT License](LICENSE) 开源。

*   遇到 Bug？请提交 [Issue](https://github.com/TouhouGleaners/danmaku-sender/issues)。
*   有新功能想法？欢迎提交 PR！

---
**Made with ❤️ by [Miku_oso](https://github.com/Mikuoso)**