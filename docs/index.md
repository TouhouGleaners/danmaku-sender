---
hide:
  - navigation
  - toc
---

# 🚀 B站弹幕补档工具

<p align="center">
  <strong>现代化 · 专业级 · 稳健的 Bilibili 弹幕一站式管理方案</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/github/v/tag/TouhouGleaners/danmaku-sender?filter=v*&label=Pre-Release&color=orange" alt="Pre-release">
  <img src="https://img.shields.io/github/v/release/TouhouGleaners/danmaku-sender?label=Release&color=bright-green" alt="Release">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/UI-PySide6-41cd52.svg" alt="PySide6">
</p>

---

## 💡 这个工具解决什么问题？

Bilibili 没有提供批量发送弹幕的官方工具。如果你需要将一个视频的弹幕「搬运」到另一个视频——比如补档、合集迁移、弹幕备份恢复——只能手动逐条复制粘贴，费时费力且无法追踪发送结果。

**BiliDanmakuSender** 将这个流程自动化：加载 XML 弹幕文件 → 校验修复 → 批量发送 → 追踪存活率，一站式完成。

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } __专业级发射器__
    ---
    支持随机延迟、爆发模式与任务结束时间 (ETA) 预测。内置 WBI 签名算法，完美模拟网页端行为，告别"发送失败"。

-   :material-layers-edit:{ .lg .middle } __原子化弹幕编辑器__
    ---
    基于原子变换架构。配备侧边栏属性检查器，支持实时修改颜色、模式、字号，支持毫秒级时间轴平移与批量去换行。

-   :material-shield-check:{ .lg .middle } __独家弹幕监视器__
    ---
    实时对账系统。自动抓取在线弹幕与发送记录对比，一眼识别被系统后台拦截的"幽灵弹幕"，确保补档真实存活。

-   :material-database-check:{ .lg .middle } __稳健的数据管理__
    ---
    基于 Peewee ORM 的持久化历史记录，支持断点续传。智能查重算法确保不会在同一视频位置发送重复弹幕。

</div>

---

## 🛠️ 快速开始

<div class="grid cards" markdown>

-   [:octicons-download-16: **下载安装**](https://github.com/TouhouGleaners/danmaku-sender/releases/latest)
    获取最新版本的可执行文件。

-   [:octicons-rocket-16: **5 分钟上手**](setup/first_send.md)
    从安装到成功发送第一条弹幕的完整流程。

-   [:octicons-sign-in-16: **登录 B 站账号**](setup/credentials.md)
    扫码登录或手动获取凭证。

-   [:octicons-question-24: **常见问题**](faq.md)
    解决发送频繁、登录失效等疑问。

-   [:octicons-mark-github-16: **GitHub 仓库**](https://github.com/TouhouGleaners/danmaku-sender)
    查看源码、提交 Issue 或贡献代码。

</div>

---

## 📖 文档导航

| 章节 | 适合谁 | 内容 |
|:-----|:-------|:-----|
| [🚀 快速上手](setup/first_send.md) | 第一次使用的用户 | 凭证获取 → 界面认识 → 发送第一条弹幕 |
| [📦 核心功能手册](features/sender/create-task.md) | 日常使用中查阅 | 发射器、编辑器、监视器、历史记录的详细操作指南 |
| [⚙️ 配置与数据](config/settings.md) | 需要调参或排查问题时 | 全局配置项说明、账号安全、数据存储结构 |
| [🔧 进阶与排查](advanced/troubleshooting.md) | 遇到错误或想进阶使用 | 错误码速查、故障排查、彩虹弹幕等高级玩法 |

---

<p align="center">
  <small>本项目由 <strong>Miku_oso</strong> 维护。与 Bilibili 官方无关联，仅供学习与技术交流使用。</small>
</p>
