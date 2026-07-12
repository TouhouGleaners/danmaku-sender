# BiliDanmakuSender 开发指南

本文档为 Claude Code (claude.ai/code) 和 Cline 等 AI 代理提供本仓库的代码规范与架构指导。

## 项目概述
BiliDanmakuSender (B站弹幕发射器) — 一个基于 PySide6 的桌面应用程序，用于批量发送、编辑和监视 Bilibili 弹幕。支持加载 XML 弹幕导出文件，发送至目标视频并具备查重去重/重试机制，同时跟踪弹幕的存活率。

## 常用指令 (Commands)
```bash
# 开发环境运行
python run.py                  # 推荐 (会自动将 src/ 加入 sys.path)
python -m danmaku_sender       # 模块入口运行

# 安装依赖
pip install -e .               # 可编辑模式安装
pip install -e ".[dev]"        # + pytest, nuitka, types-peewee
pip install -e ".[docs]"       # + mkdocs

# 生产环境构建 (Nuitka → Windows 原生 exe)
python -m nuitka --standalone run.py
python -m nuitka --onefile run.py
```

## 架构与数据流 (Architecture)
采用标准的三层 MVC 架构。所有源码位于 `src/danmaku_sender/` 下。

### 核心分层
- **API 层 (`api/`)**: `BiliApiClient` 是所有 B站 API 调用的唯一 HTTP 客户端，封装了 Cookie 鉴权和 WBI 参数签名 (`WbiSigner`)。
- **Core 层 (`core/`)**:
  - `Entities`: 纯数据类 (如 `Danmaku`, `VideoInfo`)。
  - `Engines`: 状态机与核心引擎 (`DanmakuScheduler`, `BiliDanmakuMonitor`, `EditorSession`)。
  - `Database`: `HistoryManager` 单例，使用 Peewee ORM + SQLite (WAL 模式)。
  - `State`: `AppState` (QObject) 是全局状态容器，由 Pydantic 校验配置。
- **UI 层 (`ui/`)**: 纯 UI 渲染。`MainWindow` 包含侧边栏和5个页面模块。
- **Controllers 控制层 (`controllers/`)**: 连接 UI 与 Core 的桥梁。短时异步操作使用 `PoolTask.submit()`，长驻任务继承 `WorkerThread`。

### 数据流向 (发送管线)
1. 视频获取 → `VideoState` → 加载 XML → `DanmakuParser` → `EditorSession` 进行编辑
2. `SenderController` → 构建 `SendJob` → `SendTaskWorker` (QThread) → 交给 `DanmakuExecutor` + `DanmakuScheduler`
3. Scheduler 遍历队列，与数据库查重，委派 Executor 发送。
4. 结果通过 Qt 信号 (Signals) 流式传回 UI 层。

## 核心约定 (Key Conventions)
- **语言**: 提交信息(Commit messages)、Issue、文档以及 UI 文本统一使用**中文**。
- **Commits**: 遵循 Conventional Commits 格式 — `类型(作用域): 描述` (如 `feat:`, `fix:`, `refactor:`)。
- **配置持久化**: 运行时配置保存在用户数据目录 (`platformdirs`)。凭据使用 Fernet 加密并由系统 keyring 管理。
- **版本控制**: 唯一事实来源是 `src/danmaku_sender/_version.py`。
- **Python环境**: 必须兼容 Python 3.12+。

---

## 严苛的开发规范与反模式 (CRITICAL RULES)

在修改或添加新功能时，**必须**严格遵守以下约束，以维护项目架构：

### Rule 1: 绝对禁止阻塞 UI 线程
- **反模式 (Anti-pattern)**: 在 UI 或 Controller 方法中直接调用 `requests.get()` 或执行复杂的 SQLite 查询。
- **正确做法**: 对于短期的异步操作（API 调用、文件解析等），**必须**使用 `PoolTask`。
  ```python
  from ..framework.concurrency import PoolTask

  PoolTask.submit(your_blocking_function, self.on_success, self.on_error, arg1, arg2)
  ```
- 对于长期运行的循环任务（如监视或发送），请继承 `WorkerThread` (QThread)。
- **职责分层**: `PoolTask` 只在 Controller 层使用，UI 页面**不得**直接创建 `PoolTask`。所有涉及 IO 的异步操作（如文件导出）应由 Controller 暴露方法，UI 页面只负责调用和处理回调。

### Rule 2: 始终使用 UIBinder 处理状态持久化 (State Persistence)
- **强制要求 (Mandatory)**: 任何反映或修改全局配置 (Config)、用户凭据或持久化应用状态 (`AppState`) 的 UI 元素，**必须**使用 `UIBinder`。这能自动处理 Pydantic 校验异常并触发 QSS 样式反馈。
  ```python
  from .framework.binder import UIBinder
  UIBinder.bind(self.sessdata_input, state, "sessdata", realtime=True)
  UIBinder.bind(self.prevent_sleep_checkbox, state.sender_config, "prevent_sleep")
  ```
- **实用例外 (The Lambda Rule)**: 对于纯粹的瞬态 (ephemeral)、无状态 (stateless) 或局部 UI 交互（例如：切换控件可见性、清空搜索栏、触发一次性对话框），**鼓励**直接使用 lambda 信号连接，以保持开发效率并避免污染全局状态。

### Rule 3: 异常处理标准
- `BiliApiClient` 在发生错误时会抛出 `BiliApiError` (code != 0) 或 `BiliNetworkError` (HTTP/连接问题)。
- 业务逻辑**必须**捕获这些异常，并通过 `BiliDmErrorCode.from_code(e.code).is_fatal` 检查是否为致命错误，以决定是否中断任务。

### Rule 4: PySide6 编码规范
- **类型提示 (Type Hints)**: 所有的函数签名和类属性**必须**包含 Python 3.12+ 的类型注解（例如：`list[str]`, `dict[str, Any]`）。
- **Qt 槽函数**: 所有的信号回调函数**必须**使用 `@Slot()` 装饰器并标注参数类型（例如：`@Slot(str, int)`）。
- **日志系统**: 使用命名空间日志（例如：`logging.getLogger("App.Sender.UI")`）。底层的 `GuiLoggingHandler` 会自动将这些日志路由到正确的 UI 面板。**严禁**手动通过代码向 `QTextEdit` 追加文本。