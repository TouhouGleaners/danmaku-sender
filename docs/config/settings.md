# 全局发送与监视配置

本页是所有配置项的完整参考。所有配置均可在「全局设置」页面的 UI 控件中调整，无需手动编辑文件。

---

## 发送策略 (SenderConfig)

| 配置项 | 类型 | 默认值 | UI 控件 | 说明 |
|:-------|:-----|:-------|:--------|:-----|
| `min_delay` | float | 8.0 | QDoubleSpinBox | 两条弹幕之间的最小随机间隔（秒） |
| `max_delay` | float | 8.5 | QDoubleSpinBox | 两条弹幕之间的最大随机间隔（秒） |
| `burst_enabled` | bool | false | QCheckBox | 是否启用突发模式 |
| `burst_size` | int | 3 | QSpinBox | 突发模式下每轮连发条数 |
| `rest_min` | float | 40.0 | QDoubleSpinBox | 突发模式休息期最小时间（秒） |
| `rest_max` | float | 45.0 | QDoubleSpinBox | 突发模式休息期最大时间（秒） |
| `stop_after_count` | int | 0 | QSpinBox | 发送 N 条后自动停止（0=不限） |
| `stop_after_time` | int | 0 | QSpinBox | 运行 N 分钟后自动停止（0=不限） |
| `delay_between_tasks` | float | 30 | QDoubleSpinBox | 两个任务之间的等待时间（秒） |
| `prevent_sleep` | bool | true | QCheckBox | 发送期间阻止系统休眠 |
| `use_system_proxy` | bool | true | QCheckBox | 是否使用系统代理 |
| `skip_sent` | bool | true | QCheckBox | 是否启用断点续传（发送前查重） |

详细说明见 [频率控制与并发策略](../features/sender/delay-control.md) 和 [断点续传与智能去重](../features/sender/resume.md)。

---

## 监视器配置 (MonitorConfig)

| 配置项 | 类型 | 默认值 | UI 控件 | 说明 |
|:-------|:-----|:-------|:--------|:-----|
| `refresh_interval` | int | 60 | QSpinBox | 轮询 B 站弹幕池的间隔（秒），范围 10~3600 |
| `prevent_sleep` | bool | true | QCheckBox | 监视期间阻止系统休眠 |
| `use_system_proxy` | bool | — | — | 是否使用系统代理 |
| `stats_baseline` | float | 程序启动时间 | QComboBox + 按钮 | 统计基线时间戳（瞬态，不持久化） |

详细说明见 [实时存活率仪表盘](../features/monitor/dashboard.md)。

---

## 弹幕校验配置 (ValidationConfig)

| 配置项 | 类型 | 默认值 | UI 控件 | 说明 |
|:-------|:-----|:-------|:--------|:-----|
| `enabled` | bool | true | QCheckBox | 是否启用自定义关键词过滤 |
| `blocked_keywords` | list[str] | [] | QLineEdit | 自定义屏蔽关键词列表（逗号分隔） |

!!! note "配置位置"
    校验配置的 UI 控件位于「弹幕编辑器」弹窗内的「校验与过滤规则」区域，而非全局设置页面。详见 [校验规则与异常标红](../features/editor/validation.md)。

---

## 配置持久化

所有配置在窗口关闭时自动保存到：

```
%LOCALAPPDATA%/Miku_oso/BiliDanmakuSender/config.json
```

保存机制：

- 使用 Pydantic 模型校验，确保写入的值合法。
- 使用 `atomic_write`（先写临时文件再重命名），避免写入中断导致文件损坏。
- 加载时如果某个配置段校验失败，自动回退到默认值，不影响其他配置段。
