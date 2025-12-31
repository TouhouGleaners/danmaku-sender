# B站弹幕发射器 (BiliDanmakuSender)

<p align="center">
  <img src="https://img.shields.io/github/v/tag/TouhouGleaners/danmaku-sender?label=Pre-Release&color=orange" alt="Pre-release">
  <img src="https://img.shields.io/github/v/release/TouhouGleaners/danmaku-sender?label=Release&color=bright-green" alt="Release">
  <img src="https://img.shields.io/github/downloads/TouhouGleaners/danmaku-sender/total?label=Downloads" alt="Total Downloads">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/github/license/TouhouGleaners/danmaku-sender?label=License" alt="License">
</p>

B站弹幕发射工具，基于 **Python 3.12** 与 `ttkbootstrap` 构建。  
它能帮助您将本地的 B 站 XML 弹幕文件重新发送到指定的视频分 P 中，实现弹幕的**备份、迁移和恢复**。针对大规模补档场景，提供了稳健的挂机支持与风控规避机制。

## 目录

- [✨ 主要特性](#-主要特性)
- [🚀 安装与运行](#-安装与运行)
- [📖 使用指南](#-使用指南)
  - [🔑 1. 获取 Cookie](#-1-获取-cookie)
  - [⚙️ 2. 全局配置 (重要)](#-2-全局配置-重要)
  - [🚀 3. 发送弹幕](#-3-发送弹幕)
  - [🔧 4. 校验与监视](#-4-校验与监视)
- [🤝 贡献](#-贡献)
- [📄 许可证](#-许可证)

---

## ✨ 主要特性

*   **🛡️ 任务防中断**：新增**阻止系统休眠**逻辑。任务运行期间自动保持系统唤醒，防止因电脑睡眠导致的长任务中断。
*   **🚀 智能控频**：支持**随机延迟**与**爆发模式**（每发送 N 条休息 M 秒），有效模拟人工行为，降低风控风险。
*   **🌐 网络适配器**：支持**系统代理开关**。允许手动禁用代理强制直连 B 站，解决 VPN 或加速器导致的连接超时。
*   **🔍 弹幕校验**：内置校验器，支持在发送前识别并选择编辑或删除过长、含换行符或特殊符号的非法弹幕。
*   **🔭 进度监视**：实时比对线上弹幕与本地文件，直观掌握弹幕补全进度。
*   **🔔 自动检测更新**：启动时自动检查 GitHub 最新版本，确保及时获取功能改进与 Bug 修复。
*   **📦 开箱即用**：提供 Windows 绿色打包版，无需安装 Python 环境。


## 🚀 安装与运行

### 📦 打包版 (推荐)

下载解压后直接运行 `BiliDanmakuSender.exe`。

<p align="center">
  <a href="https://github.com/TouhouGleaners/danmaku-sender/releases/latest">
    <img src="https://img.shields.io/badge/下载最新版-BiliDanmakuSender.exe-brightgreen?style=for-the-badge&logo=github" alt="下载最新版">
  </a>
</p>

### 🐍 源码版 (开发者)

```bash
git clone https://github.com/TouhouGleaners/danmaku-sender.git
cd danmaku-sender
pip install -r requirements.txt
python run.py
```

## 📖 使用指南

### 🔑 1. 获取 Cookie
1.  在浏览器（Chrome/Edge）中登录 Bilibili。
2.  按 `F12` -> **"应用" (Application)** -> **"Cookie"**。
3.  复制 `SESSDATA` 和 `bili_jct` 的值。

### ⚙️ 2. 全局配置 (重要)
在正式发送前，请先前往 **“全局设置”** 标签页：
*   **身份凭证**：填写上一步获取的 `SESSDATA` 和 `bili_jct`（自动加密保存）。
*   **系统设置**：建议勾选 **“阻止电脑休眠”** 以确保挂机任务稳定。
*   **网络设置**：若开启 VPN 后无法连接，请尝试取消勾选 **“使用系统代理”**。

### 🚀 3. 发送弹幕
1.  在 **“弹幕发射器”** 标签页输入 **BV 号** 并点击 **“获取分 P”**。
2.  选择目标分 P 并加载本地 **XML 弹幕文件**。
3.  **高级设置**：根据视频热度调整延迟。推荐使用爆发模式（如：每 3 条休息 40 秒）以规避高频风控。
4.  点击 **“开始任务”**。

### 🔧 4. 校验与监视
*   **校验器**：发送前可切换至“弹幕校验器”找出并修改有问题的弹幕，应用修改后会同步至发送队列。
*   **监视器**：任务开始后，可开启监视器定期比对线上已存在的弹幕，防止重复发送。

## 🤝 贡献

我们欢迎任何形式的贡献！请参考 [**贡献指南**](CONTRIBUTING.md)。

*   [**报告 Issue**](https://github.com/TouhouGleaners/danmaku-sender/issues)
*   [**提交 PR**](https://github.com/TouhouGleaners/danmaku-sender/pulls)

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源。
