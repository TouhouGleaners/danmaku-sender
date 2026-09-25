"""Pydantic 配置模型的公共基类。

pydantic 的 ``validate_assignment`` 赋值不原子：字段级校验失败会拒绝写入，
但 ``model_validator(mode='after')`` 在赋值后运行、失败不回滚，跨字段规则
（如最小延迟 ≤ 最大延迟）会留下脏值。本模块补上事务性——「先整模型试算、
通过才落值」。
"""

from collections.abc import Iterable
from typing import Any, Self

from pydantic import BaseModel


class AtomicModel(BaseModel):
    """赋值原子化的 BaseModel，适用于被 UI 反复写入的可变配置对象。

    两条写入路径：

    - 单字段写入（``model.field = v``）走 :meth:`__setattr__`，先整模型试算；
    - 批量落账走 :meth:`commit`，跳过逐字段试算（中间态会再次失败）。

    注意：``model_copy(update=...)`` 不经过 ``__setattr__``，会绕过上述保护；
    需要原子写入请用普通属性赋值。
    """

    def __setattr__(self, name: str, value: Any) -> None:
        """写入单个字段；整模型校验失败则保持原状。"""
        if name in type(self).model_fields:
            # 取完整字段值试算：model_dump() 不含 exclude=True 的字段，
            # 那些字段会被当成默认值参与校验
            probe = {n: getattr(self, n) for n in type(self).model_fields}
            probe[name] = value
            type(self).model_validate(probe)
        super().__setattr__(name, value)

    def commit(self, fresh: Self, fields: Iterable[str]) -> None:
        """把 fresh 的指定字段批量写入自身，跳过逐字段试算。

        批量落账的中间态可能再次校验失败，所以不能逐字段走 ``__setattr__``。

        Args:
            fresh: 已通过 ``model_validate`` 的同类型实例。
            fields: 要写入的字段名（通常就是试算用的字典，迭代它取键）。
                只写这里出现的字段——试算时没收集到的（如 ``exclude=True``
                的字段）保持原状，不会被 fresh 的默认值冲掉。
        """
        for name in fields:
            if name in type(self).model_fields:
                object.__setattr__(self, name, getattr(fresh, name))
