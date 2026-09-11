# B站弹幕发射器 (BiliDanmakuSender)

<p align="center">
  <img src="https://img.shields.io/github/v/tag/TouhouGleaners/danmaku-sender?filter=v*&label=Pre-Release&color=orange" alt="Pre-release">
  <img src="https://img.shields.io/github/v/release/TouhouGleaners/danmaku-sender?label=Release&color=bright-green" alt="Release">
  <img src="https://img.shields.io/github/downloads/TouhouGleaners/danmaku-sender/total?label=Downloads" alt="Total Downloads">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/UI-PySide6-41cd52.svg" alt="PySide6">
  <img src="https://img.shields.io/badge/Build-Nuitka-cea113.svg" alt="Nuitka">
  <img src="https://img.shields.io/github/license/TouhouGleaners/danmaku-sender?label=License" alt="License">
</p>

**B站弹幕发射器** 是一款基于 **Python 3.12** 与 **PySide6 (Qt)** 的弹幕补档工具，采用 Nuitka 编译以获得最佳运行性能。

专为**弹幕搬运、备份恢复及大规模补档**场景设计，支持多任务队列、独立配置、断点续传、弹幕核销与存活率追踪。

---

## ✨ 核心特性

### 🚀 多任务队列
- 每个任务独立配置发送策略（延迟、爆发模式、自动停止条件等）
- 拖放 XML 文件到队列表格自动分配弹幕
- 拖拽排序、右键编辑、批量清除已完成任务
- 任务间可设防风控间隔

### 🛡️ 风控规避
- 原生支持 B 站 WBI 签名算法
- 随机延迟 + 爆发模式（每发 N 条休息一段时间）
- 限流自动重试（指数退避），致命错误自动熔断
- 任务运行期间自动阻止系统休眠

### ✂️ 弹幕编辑器
- 从发射器右键任务进入，直接编辑该任务的弹幕
- 支持批量去换行、截断过长弹幕、时间轴平移
- 撤销/重做、彩虹弹幕阵列生成
- 实时校验：长度、换行符、时间越界、屏蔽词

### 📊 弹幕监视器
- 队列总体监视：实时显示所有任务的存活率
- 后台在线核销：定期拉取 B 站在线弹幕列表，核销存活并标记丢失
- 按时间基线筛选统计（本次启动 / 24 小时 / 全量历史）

### 💾 历史记录与断点续传
- 每条发送成功的弹幕自动入库（SQLite + WAL）
- 弹幕指纹去重：相同内容+时间+颜色的弹幕自动跳过
- 支持按关键词、BV 号、弹幕状态筛选查询
- 双击查看详情，右键可验证单条弹幕存活状态

### ⚙️ 系统优化
- 配置与账号文件原子写入（写临时文件 + fsync + 原子替换），崩溃不损坏
- 账号凭据加密存储到系统密钥环
- 支持系统代理或强制直连
- Windows Toast 通知（任务完成/暂停/中止时提醒）

---

## 🚀 安装与运行

### 📦 打包版（推荐普通用户）

下载后直接运行 `BiliDanmakuSender.exe`，无需安装 Python 环境。

<p align="center">
  <a href="https://github.com/TouhouGleaners/danmaku-sender/releases/latest">
    <img src="https://img.shields.io/badge/⬇️_下载最新版-Windows_x64-00a1d6?style=for-the-badge&logo=windows" alt="下载最新版">
  </a>
</p>

### 🐍 源码版（开发者）

> [!NOTE]
> 请确保已安装 **Python 3.12 或更高版本**。

```bash
# 1. 克隆仓库
git clone https://github.com/TouhouGleaners/danmaku-sender.git
cd danmaku-sender

# 2. 安装依赖（推荐使用虚拟环境）
pip install -e .[dev]

# 3. 运行
python -m danmaku_sender.main
```

---

## 📖 使用指南

### 页面布局

软件采用左侧侧边栏导航，包含以下页面：

| 页面 | 功能 |
|------|------|
| **账号管理** | 管理登录账号、凭证加密存储、检测有效性 |
| **全局设置** | 网络代理、发送延迟、爆发模式、断点续传等 |
| **弹幕发射器** | 管理任务队列、发送弹幕、编辑弹幕、监视存活 |
| **弹幕监视器** | 监视队列中所有任务的存活率，支持在线核销 |
| **弹幕历史记录** | 查询弹幕发送历史，按状态/关键词/BV号筛选 |

### 1. 配置身份凭证

首次使用请点击左上角头像区域管理账号进行登录：

- **扫码登录**：点击 **"扫码登录"** → 扫码确认 → 自动获取 SESSDATA 和 bili_jct
- **手动输入**：浏览器登录 B 站 → F12 → 应用(Cookies) → **SESSDATA** 和 **bili_jct** 复制
- 凭证加密存储到系统密钥环，支持多账号管理与一键检测有效性

### 2. 创建与发送任务

1. 在 **"弹幕发射器"** 页面点击 **"新建任务"**（支持一次性创建多个任务）
2. 输入 BV 号或视频链接，获取视频信息，选择分 P
3. 加载本地 XML 弹幕文件
4. 调整发送策略（随机延迟、爆发模式、自动停止等）
5. 点击 **"启动队列"** 开始发送

支持拖放 XML 文件直接分配给队列中的任务。

### 3. 编辑弹幕

- 右键队列中的任务 → **"编辑弹幕"**
- 支持批量去换行、截断过长文本、时间轴平移
- 双击弹幕条目可编辑内容、颜色、字号、时间
- 编辑完成后点击 **"保存到任务"**

### 4. 监视发送

- 切换到 **"弹幕监视器"** 页面
- 点击 **"监视队列"** 开始在线核销
- 监视器会定期拉取 B 站在线弹幕，核销存活状态
- 支持设置统计基线（本次启动 / 24小时 / 全量历史）

### 5. 历史记录

- 切换到 **"弹幕历史记录"** 页面
- 支持按关键词、BV 号、弹幕状态（待验证/已存活/已丢失）筛选
- 双击条目查看完整详情（时间、颜色、字号、CID 等）
- 右键可验证单个分 P 的弹幕存活状态

---

## 🏗️ 项目架构

```
src/danmaku_sender/
├── types/          # 纯类型定义、异常、协议
├── config/         # Pydantic 配置模型
├── repo/           # 数据访问（SQLite + B站 API）
├── service/        # 业务逻辑（发送管线、解析、校验、核验）
├── runtime/        # 组装层、生命周期管理、平台服务
├── controller/     # UI 与服务的中间协调层
│   └── sender/     #   发送控制器与队列 Worker
└── ui/             # PySide6 界面
    ├── framework/  #   UI 框架基建（双向绑定、样式、图像处理）
    ├── views/      #   业务视图（发射器、编辑器、监视器、历史、设置、账号）
    └── dialogs/    #   通用弹窗（关于、帮助、更新、扫码登录）
```

**依赖方向（单向）：**
```
ui → controller → runtime → service → repo → config → types
```

---

## ❓ 常见问题

**Q: 为什么显示"SESSDATA 无效"？**

> [!WARNING]
> B 站 Cookie 有有效期（通常半个月到一个月），过期后需要重新提取。

A: 点击左上角头像区域，重新提取 SESSDATA 和 bili_jct 并更新。

**Q: "断点续传"是如何工作的？**
A: 程序将发送成功的弹幕指纹（内容+时间+颜色等）存入 SQLite 数据库。下次发送相同文件时，程序会查询数据库，跳过已存在的弹幕。

**Q: 遇到"致命错误"任务停止了怎么办？**

> [!TIP]
> 网络超时程序会自动重试（指数退避），一般无需手动干预。

A: 如果是 `412` 等严重风控错误，请检查账号状态或暂停一段时间后重试。

**Q: 如何批量发送多个视频的弹幕？**
A: 在发射器页面点击"新建任务"，为每个视频创建任务，然后点击"启动队列"即可批量发送。每个任务可独立配置发送策略。

**Q: 如何查看发送失败的弹幕？**
A: 队列完成后，失败的弹幕记录会保留在任务中。也可前往"弹幕历史记录"页面按状态筛选查看。

---

## 🤝 贡献

本项目基于 [MIT License](LICENSE) 开源。

- 遇到 Bug？请提交 [Issue](https://github.com/TouhouGleaners/danmaku-sender/issues)
- 有新功能想法？欢迎提交 PR！

---

**Made with ❤️ by [Miku_oso](https://github.com/Mikuoso)**
