"""表单与模型绑定基础设施 (Form Binder)

将 PySide 控件与 Pydantic 模型字段安全连接。

按表单的提交方式选择绑定器：
  - LiveFormBinder:（实时修改）：没有「保存」按钮，控件变更立即写入模型（如设置页）。
    页面 ``showEvent`` 时调用 ``fill()`` 刷新。
  - DraftFormBinder:（草稿修改）：有「保存」按钮，控件即草稿，确认时才写入模型（如任务详情对话框）。
    打开时 ``fill()``，确认时 ``collect()``。
"""

from .base import clear_invalid, mark_invalid
from .draft import DraftFormBinder
from .live import LiveFormBinder

__all__ = [
    "DraftFormBinder",
    "LiveFormBinder",
    "clear_invalid",
    "mark_invalid",
]
