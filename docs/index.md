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
  <img src="https://img.shields.io/github/v/tag/TouhouGleaners/danmaku-sender?label=Pre-Release&color=orange" alt="Pre-release">
  <img src="https://img.shields.io/github/v/release/TouhouGleaners/danmaku-sender?label=Release&color=bright-green" alt="Release">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/UI-PySide6-41cd52.svg" alt="PySide6">
</p>

---

## 💡 为什么选择 BiliDanmakuSender？

本项目专为 B 站视频搬运工、创作者及补档爱好者设计，针对高频补档场景中的“封禁、偏移、重复、低效”等痛点进行了深度优化。

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } __专业级发射器__
    ---
    支持随机延迟、爆发模式与任务结束时间 (ETA) 预测。内置 WBI 签名算法，完美模拟网页端行为，告别“发送失败”。

-   :material-layers-edit:{ .lg .middle } __原子化弹幕编辑器__
    ---
    基于原子变换架构。配备侧边栏属性检查器，支持实时修改颜色、模式、字号，支持毫秒级时间轴平移与批量去换行。

-   :material-shield-check:{ .lg .middle } __独家弹幕监视器__
    ---
    实时对账系统。自动抓取在线弹幕与发送记录对比，一眼识别被系统后台拦截的“幽灵弹幕”，确保补档真实存活。

-   :material-database-check:{ .lg .middle } __稳健的数据管理__
    ---
    基于 Peewee ORM 的持久化历史记录，支持断点续传。智能查重算法确保不会在同一视频位置发送重复弹幕。

</div>

---

## 🛠️ 快速开始

<div class="grid cards" markdown>

-   [:octicons-download-16: **下载安装**](https://github.com/TouhouGleaners/danmaku-sender/releases/latest)
    获取最新版本的可执行文件。

-   [:octicons-book-16: **快速入门**](setup.md)
    从获取 Cookie 到发送第一批弹幕。

-   [:octicons-question-24: **常见问题**](faq.md)
    解决发送频繁、登录失效等疑问。

-   [:octicons-mark-github-16: **GitHub 仓库**](https://github.com/TouhouGleaners/danmaku-sender)
    查看源码、提交 Issue 或贡献代码。

</div>

---

<p align="center">
  <small>本项目由 <strong>Mikuoso</strong> 维护。与 Bilibili 官方无关联，仅供学习与技术交流使用。</small>
</p>