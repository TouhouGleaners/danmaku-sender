# 重构大纲：Types → Config → Repo → Service → Runtime → UI 严格六层架构

## 目标

```
ui → runtime → service → repo → config → types
```

单向依赖，无跨级，无反向。消灭 `core/`、`api/`、`utils/` 三个包。

---

## 当前状态

| 包            | 状态                         |
| ------------- | ---------------------------- |
| `types/`      | ✅ 已完成（models + exceptions） |
| `config/`     | ✅ 已完成                     |
| `runtime/`    | ✅ 已完成                     |
| `repo/`       | ❌ 目录已建，空的             |
| `service/`    | ❌ 不存在                     |
| `core/`       | ⚠️ 残留 database/ engines/ services/ |
| `api/`        | ⚠️ 3 个文件待迁移            |
| `utils/`      | ⚠️ 6 个模块待消化            |

---

## 依赖违规清单（需消除）

| 违规                                                         | 类型     |
| ------------------------------------------------------------ | -------- |
| `core/engines/sender/executor.py` → `api.bili_api_client`    | 反向依赖 |
| `core/engines/bili_monitor.py` → `api.bili_api_client`       | 反向依赖 |
| `core/services/video_fetcher.py` → `api.bili_api_client`     | 反向依赖 |
| `ui/controllers/account_controller.py` → `api.bili_api_client` | UI 跨级  |
| `ui/controllers/auth_controller.py` → `api.bili_api_client`  | UI 跨级  |
| `ui/controllers/monitor_controller.py` → `api.bili_api_client` | UI 跨级  |
| `ui/controllers/sender_controller.py` → `api.bili_api_client` | UI 跨级  |
| `ui/controllers/video_controller.py` → `api.bili_api_client` | UI 跨级  |
| `ui/controllers/system_controller.py` → `api.update_checker` | UI 跨级  |
| `core/database/history_manager.py` → `config.app_meta.AppInfo` | 跨级（迁移后合规） |

---

## 目标目录结构

```
src/danmaku_sender/
  types/                          # 叶子层：纯类型定义，零外部依赖
    models/                       # （已完成）
    exceptions/                   # （已完成）
    protocols.py                  # 【新增】BiliApiProtocol
  config/                         # 配置层：只依赖 types
    app_meta.py                   # （已完成）
    sender_config.py              # （已完成）
    monitor_config.py             # （已完成）
    validation_config.py          # （已完成）
    api_auth_config.py            # （已完成）
  repo/                           # 数据访问层：本地 DB + 远程 API
    history_manager.py            # ← core/database/
    orm_models.py                 # ← core/database/
    bili_api_client.py            # ← api/
    wbi_signer.py                 # ← api/
    github_client.py              # ← api/update_checker.py（改名）
  service/                        # 业务逻辑层：无状态工具 + 有状态引擎
    danmaku_parser.py             # ← core/services/
    danmaku_validator.py          # ← core/services/
    danmaku_exporter.py           # ← core/services/
    video_fetcher.py              # ← core/services/
    editor_session.py             # ← core/engines/
    danmaku_scheduler.py          # ← core/engines/sender/scheduler.py
    danmaku_executor.py           # ← core/engines/sender/executor.py
    sending_context.py            # ← core/engines/sender/context.py
    delay_manager.py              # ← core/engines/sender/delay_manager.py
    bili_monitor.py               # ← core/engines/
  runtime/                        # 组装层（已有，微调）
    runtime.py
    app_state.py
    config_manager.py
    account_manager.py
    theme_manager.py
    resources.py
    log_utils.py                  # ← utils/log_utils.py
  ui/                             # UI 层（已有，内部消化 utils）
    framework/
      binder.py
      concurrency.py
      image_processor.py
      style_loader.py
      path_utils.py               # ← utils/path_utils.py
    common/
      formatting.py               # ← utils/time_utils.py + string_utils.py 合并
    controllers/
      system_utils.py             # ← utils/system_utils.py 移入
      ...
    sender_page.py                # notification_utils 内联
    ...
  （core/ 删除）
  （api/ 删除）
  （utils/ 删除）
```

---

## 阶段一：Repo 层 — 合并数据访问

> **目标**：`core/database/` + `api/` → `repo/`，建立统一的数据访问层

### 步骤 1.1：迁移 `core/database/` → `repo/`

- 移动 `core/database/orm_models.py` → `repo/orm_models.py`
- 移动 `core/database/history_manager.py` → `repo/history_manager.py`
- 创建 `repo/__init__.py`
- 更新 `history_manager.py` 内的相对 import

**影响范围**（需改 import 路径的文件）：
- `core/engines/bili_monitor.py`
- `core/engines/sender/scheduler.py`
- `ui/controllers/sender_controller.py`

**验证**：`grep -rn "core.database" src/` 应返回 0 结果

### 步骤 1.2：迁移 `api/` → `repo/`

- 移动 `api/bili_api_client.py` → `repo/bili_api_client.py`
- 移动 `api/wbi_signer.py` → `repo/wbi_signer.py`
- 移动 `api/update_checker.py` → `repo/github_client.py`（改名）
- 更新 `bili_api_client.py` 内的 `from .wbi_signer` 相对 import
- 更新 `github_client.py` 中 `Links.GITHUB_API_RELEASES` 的 import（指向 `config.app_meta`）

**影响范围**（需改 import 路径的文件，共 11 个）：
- `core/engines/sender/executor.py`
- `core/engines/bili_monitor.py`
- `core/services/video_fetcher.py`
- `ui/controllers/account_controller.py`
- `ui/controllers/auth_controller.py`
- `ui/controllers/monitor_controller.py`
- `ui/controllers/sender_controller.py`
- `ui/controllers/video_controller.py`
- `ui/controllers/system_controller.py`（update_checker → github_client）

**验证**：`grep -rn "from danmaku_sender.api" src/` 应返回 0 结果

### 步骤 1.3：消除 `history_manager.py` 对 `config.app_meta.AppInfo` 的直接依赖

当前 `HistoryManager.__init__` 里用 `AppInfo` 算 SQLite 路径。改为构造函数接收 `db_path: Path`：

```python
# repo/history_manager.py
class HistoryManager:
    def __init__(self, db_path: Path):  # 不再 import AppInfo
        ...
```

路径计算上移到 `runtime/runtime.py` 组装时：

```python
# runtime/runtime.py
from config.app_meta import AppInfo
db_path = Path(platformdirs.user_data_dir(AppInfo.NAME_EN, AppInfo.AUTHOR)) / "history.db"
history_repo = HistoryManager(db_path)
```

**验证**：`repo/` 内 `grep -rn "from danmaku_sender.config" .` 应只出现 `bili_api_client` 对 `BiliConfigProto` 的引用（合规），`history_manager` 不再引用 config

---

## 阶段二：Types 层 — 新增 Protocol 抽象

> **目标**：定义 `BiliApiProtocol`，让 service 层依赖抽象而非具体实现

### 步骤 2.1：创建 `types/protocols.py`

梳理 service 层实际调用 `BiliApiClient` 的方法：

| 方法                    | 调用者                  |
| ----------------------- | ----------------------- |
| `post_danmaku()`        | `executor.py`           |
| `get_danmaku_list_xml()` | `bili_monitor.py`       |
| `get_video_info()`      | `video_fetcher.py`      |
| `get_user_info()`       | `video_fetcher.py`（可能） |
| `from_config()`         | 各 controller 构造时    |

```python
# types/protocols.py
from typing import Protocol, Any

class BiliApiProtocol(Protocol):
    def post_danmaku(self, ...) -> dict: ...
    def get_danmaku_list_xml(self, ...) -> str: ...
    def get_video_info(self, ...) -> dict: ...
    def get_user_info(self, ...) -> dict: ...
```

注意：`from_config()` 是工厂方法，不属于 Protocol（调用方在 runtime/controller 层，不在 service 层）。

### 步骤 2.2：service 层改为依赖 Protocol

将 `executor.py`、`bili_monitor.py`、`video_fetcher.py` 的类型注解从 `BiliApiClient` 改为 `BiliApiProtocol`：

```python
# 之前
from danmaku_sender.api.bili_api_client import BiliApiClient
def __init__(self, api_client: BiliApiClient, ...): ...

# 之后
from danmaku_sender.types.protocols import BiliApiProtocol
def __init__(self, api_client: BiliApiProtocol, ...): ...
```

import 路径变了，但运行时传入的仍然是 `BiliApiClient` 实例（duck typing）。

**验证**：`service/` 内 `grep -rn "BiliApiClient" .` 应返回 0 结果

---

## 阶段三：Service 层 — 合并业务逻辑

> **目标**：`core/services/` + `core/engines/` → `service/`

### 步骤 3.1：迁移 `core/services/` → `service/`

- 移动 `danmaku_parser.py`、`danmaku_validator.py`、`danmaku_exporter.py`、`video_fetcher.py`
- 创建 `service/__init__.py`
- 更新内部 import（`types.models`、`config.ValidationConfig`）

**影响范围**：
- `core/engines/editor_session.py`（import danmaku_validator）
- `core/engines/bili_monitor.py`（import danmaku_parser）
- `ui/controllers/editor_controller.py`（import danmaku_parser, danmaku_exporter）
- `ui/controllers/sender_controller.py`（import danmaku_parser, danmaku_exporter）
- `ui/controllers/video_controller.py`（import video_fetcher）

### 步骤 3.2：迁移 `core/engines/` → `service/`

- 移动 `editor_session.py` → `service/editor_session.py`
- 移动 `sender/scheduler.py` → `service/danmaku_scheduler.py`
- 移动 `sender/executor.py` → `service/danmaku_executor.py`
- 移动 `sender/context.py` → `service/sending_context.py`
- 移动 `sender/delay_manager.py` → `service/delay_manager.py`
- 移动 `bili_monitor.py` → `service/bili_monitor.py`
- 删除 `core/engines/sender/__init__.py` 的 re-export，在 `service/__init__.py` 中按需导出

**影响范围**：
- `ui/controllers/sender_controller.py`（最大消费者，import scheduler/executor/context/delay_manager）
- `ui/controllers/monitor_controller.py`（import bili_monitor）
- `ui/controllers/editor_controller.py`（import editor_session）

### 步骤 3.3：更新 service 内部 import

service 内部互相引用改为同包相对 import：

```python
# service/danmaku_scheduler.py
from .danmaku_executor import DanmakuExecutor
from .sending_context import SendingContext, SendJob
from .delay_manager import DelayManager
from ..repo.history_manager import HistoryManager  # service → repo（合规）
```

**验证**：
- `grep -rn "core.engines" src/` 应返回 0 结果
- `grep -rn "core.services" src/` 应返回 0 结果
- `grep -rn "core.database" src/` 应返回 0 结果

---

## 阶段四：Utils 消化

> **目标**：消灭 `utils/`，各模块归入所属层

### 逐模块处置

| 模块                    | 消费者                                   | 去向                               | 操作                 |
| ----------------------- | ---------------------------------------- | ---------------------------------- | -------------------- |
| `log_utils.py`          | `main.py` + `ui/main_window.py`          | `runtime/log_utils.py`             | 移动                 |
| `path_utils.py`         | `ui/dialogs.py` + `ui/framework/style_loader.py` + `notification_utils.py` | `ui/framework/path_utils.py`       | 移动                 |
| `time_utils.py`         | `ui/sender_page.py` + `ui/editor/components.py` | `ui/common/formatting.py`          | 移动并重命名         |
| `string_utils.py`       | `ui/sender_page.py`                      | `ui/common/formatting.py`          | 合并进 formatting.py |
| `notification_utils.py` | `ui/sender_page.py`                      | 内联到 `ui/sender_page.py`         | 内联                 |
| `system_utils.py`       | `ui/controllers/monitor_controller.py` + `sender_controller.py` | `ui/controllers/system_utils.py`   | 移动                 |

### 注意事项

- `notification_utils.py` 依赖 `path_utils.py` 的 `get_assets_path()`。先迁移 `path_utils`，再处理 `notification_utils`。
- `string_utils.py` 和 `time_utils.py` 都是 UI 格式化工具，合并为 `ui/common/formatting.py` 合理。

**验证**：`src/danmaku_sender/utils/` 目录应不存在

---

## 阶段五：清理

> **目标**：删除 `core/`、`api/`、`utils/` 空目录，更新项目配置

### 步骤 5.1：删除空目录

```bash
rm -rf src/danmaku_sender/core/
rm -rf src/danmaku_sender/api/
rm -rf src/danmaku_sender/utils/
```

### 步骤 5.2：全量 import 验证

```bash
grep -rn "from danmaku_sender.core" src/   # 应为 0
grep -rn "from danmaku_sender.api" src/    # 应为 0
grep -rn "from danmaku_sender.utils" src/  # 应为 0
```

### 步骤 5.3：运行测试

```bash
python -m pytest
```

### 步骤 5.4：更新 CLAUDE.md

更新架构图、分层说明、import 规则，反映新的六层结构。

---

## 依赖方向验证矩阵

迁移完成后逐层检查：

| 层        | 允许依赖         | 禁止依赖                    |
| --------- | ---------------- | --------------------------- |
| `types/`  | （无）           | 所有其他层                  |
| `config/` | `types/`         | `repo/` `service/` `runtime/` `ui/` |
| `repo/`   | `types/` `config/` | `service/` `runtime/` `ui/` |
| `service/` | `types/` `config/` `repo/` | `runtime/` `ui/` |
| `runtime/` | `types/` `config/` `repo/` `service/` | `ui/` |
| `ui/`     | 所有             | （无）                      |

---

## 迁移顺序与 PR 策略

每个阶段一个 PR，独立可验证：

| PR  | 内容                              | 风险   | 预计改动文件数 |
| --- | --------------------------------- | ------ | -------------- |
| #1  | 阶段一：Repo 层（database + api 合并） | 中     | ~15            |
| #2  | 阶段二：Protocol 抽象             | 低     | ~4             |
| #3  | 阶段三：Service 层（engines + services 合并） | 中     | ~15            |
| #4  | 阶段四：Utils 消化                | 低     | ~10            |
| #5  | 阶段五：清理 + 文档更新           | 极低   | ~3             |

**关键约束**：每个 PR 合并后必须保证 `python -m pytest` 全部通过 + 应用可正常启动。

---

## 风险与注意事项

1. **Peewee `DatabaseProxy` 对模块路径可能有隐式依赖** — 迁移 `orm_models.py` 时需验证 SQLite 连接是否正常初始化
2. **PySide6 Signal/Slot 的 import 路径** — 如果 Signal 定义在被移动的模块里，需确认运行时绑定正确
3. **`sender/__init__.py` 的 re-export** — 当前 controller 用 `from core.engines.sender import DanmakuScheduler, ...`，迁移后需在 `service/__init__.py` 或 `service/danmaku_scheduler.py` 中保持等价导出
4. **`github_client.py`（原 update_checker）引用 `config.app_meta.Links`** — repo → config 是合规方向，无问题
5. **`notification_utils` 内联时注意 `get_assets_path` 的 import 路径** — 确保 `path_utils` 先迁移完成
