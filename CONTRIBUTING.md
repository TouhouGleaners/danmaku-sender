# 贡献指南

我们非常欢迎社区的贡献。在提交你的贡献之前，请花点时间阅读以下指南。

---

## 目录

- [如何贡献](#如何贡献)
  - [报告 Bug](#报告-bug)
  - [提出功能建议](#提出功能建议)
  - [提交你的贡献 (Pull Request)](#提交你的贡献-pull-request)
- [本地开发设置](#本地开发设置)
- [项目架构](#项目架构)
- [代码风格指南](#代码风格指南)
  - [Commit 消息规范](#commit-消息规范)
  - [分支命名规范](#分支命名规范)
  - [导入规范](#导入规范)
  - [类型注解](#类型注解)
  - [日志规范](#日志规范)

---

## 如何贡献

### 报告 Bug

如果你在使用的过程中发现了 Bug，请通过创建 [Issue](https://github.com/TouhouGleaners/danmaku-sender/issues/new?template=bug_report_cn.yml) 来报告它。

为了让我们能更快地定位问题，请在 Issue 中尽量包含以下信息：

- **清晰的标题**：简明扼要地描述问题。
- **复现步骤**：详细说明如何一步步地复现这个 Bug。
- **期望的行为**：你认为在上述步骤后应该发生什么。
- **实际发生的行为**：实际发生了什么，包括错误信息、截图等。
- **你的环境**：操作系统、软件版本等。

### 提出功能建议

我们随时欢迎新的功能建议！请通过创建 [Issue](https://github.com/TouhouGleaners/danmaku-sender/issues/new?template=feature_request_cn.yml) 来告诉我们你的想法。

请在建议中详细描述：

- **解决了什么问题**：这个功能主要用于解决用户的什么痛点。
- **你建议的实现方式**：尽可能详细地描述这个功能应该如何工作。

### 提交你的贡献 (Pull Request)

我们通过 Pull Request (PR) 来接受代码贡献。提交流程如下：

1.  **Fork 本仓库** 到你自己的 GitHub 账户。
2.  将你 Fork 的仓库 **Clone** 到你的本地。
3.  从 `main` 分支创建一个新的分支，遵循 [分支命名规范](#分支命名规范)。
4.  在新的分支上进行修改和开发。
5.  **Commit** 你的修改，遵循 [Commit 消息规范](#commit-消息规范)。
6.  将你的分支 **Push** 到你 Fork 的仓库。
7.  在 GitHub 上创建一个 **Pull Request**，目标分支为本仓库的 `main` 分支。

**PR 标题规范：**

PR 标题应遵循 Conventional Commits 格式，与 Commit 消息一致：

- `feat(sender): 添加队列拖拽排序功能`
- `fix(monitor): 修复监视器日志路由问题`
- `refactor(editor): 编辑器改为发射器附属弹窗`

**PR 描述：**

请在 PR 描述中说明：
- 改动内容：简要描述你做了什么
- 关联 Issue：如果有相关 Issue，请引用（如 `#123`）

---

## 本地开发设置

1.  Clone 你 Fork 的仓库到本地：
    ```bash
    git clone https://github.com/TouhouGleaners/danmaku-sender.git
    cd danmaku-sender
    ```

2.  创建虚拟环境（推荐）：
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # Linux/macOS
    # 或
    .venv\Scripts\activate     # Windows
    ```

3.  安装项目依赖：
    ```bash
    pip install -e .[dev]
    ```

4.  运行程序：
    ```bash
    python -m danmaku_sender
    ```

5.  运行测试：
    ```bash
    python -m pytest -q
    ```

---

## 项目架构

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

> [!WARNING]
> - 同包内使用相对导入（如 `from .system_utils import KeepSystemAwake`）
> - 跨包使用绝对导入（如 `from danmaku_sender.repo.bili_api_client import BiliApiClient`）
> - 禁止反向依赖

---

## 代码风格指南

我们遵循 [PEP 8](https://www.python.org/dev/peps/pep-0008/) 代码风格。在提交代码前，请使用 `black` 或 `flake8` 等工具进行检查和格式化。

### Commit 消息规范

我们遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范。这能让我们的提交历史更加清晰，并有助于自动化生成版本日志。

提交语言可根据个人习惯选择。

Commit 消息格式为：`<type>(<scope>): <description>`

-   **feat**: 新增功能
-   **fix**: 修复 Bug
-   **docs**: 仅修改文档
-   **style**: 代码格式修改（不影响代码逻辑）
-   **refactor**: 代码重构
-   **test**: 新增或修改测试
-   **chore**: 构建流程、辅助工具的变动

**示例:**
- `feat(sender): 添加队列拖拽排序功能`
- `fix(monitor): 修复监视器日志路由问题`
- `refactor(editor): 编辑器改为发射器附属弹窗`
- `docs: 更新 README 使用指南`

### 分支命名规范

分支名称应遵循以下格式：`<type>/<description>`

- `feat/queue-monitor-v2` - 新功能
- `fix/config-atomic-write` - Bug 修复
- `refactor/service-pure-di` - 代码重构
- `docs/readme-rewrite` - 文档更新

### 导入规范

- **文件顶部导入**：所有导入必须写在文件最上方，禁止局部导入
- **同包内**：使用相对导入（如 `from .components import EditorTableModel`）
- **跨包**：使用绝对导入（如 `from danmaku_sender.repo.bili_api_client import BiliApiClient`）

```python
# 正确
from danmaku_sender.types.models.queue import QueueTask
from danmaku_sender.config import SenderConfig

# 错误 - 局部导入
def some_function():
    from danmaku_sender.types.models.queue import QueueTask
```

### 类型注解

所有函数签名和类属性必须包含 Python 3.12+ 的类型注解：

```python
# 正确
def process_task(task: QueueTask, config: SenderConfig) -> bool:
    ...

# 错误
def process_task(task, config):
    ...
```

### 日志规范

使用命名空间日志，禁止手动向 QTextEdit 追加文本：

```python
# 正确
logger = logging.getLogger(__name__)
logger.info(f"任务已创建: {task.target.display_string}")

# 错误
self.log_output.append(f"任务已创建: {task.target.display_string}")
```

---

再次感谢你的贡献！
