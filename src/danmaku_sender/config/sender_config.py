from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SenderConfig(BaseModel):
    """发送器的配置数据"""
    model_config = ConfigDict(validate_assignment=True)

    # 延迟设置
    min_delay: float = Field(default=8.0, ge=0.1)
    max_delay: float = Field(default=8.5, ge=0.1)

    # 爆发模式
    burst_enabled: bool = False
    burst_size: int = Field(default=3, ge=2)
    rest_min: float = Field(default=40.0, ge=0.0)
    rest_max: float = Field(default=45.0, ge=0.0)

    # 自动停止
    stop_after_count: int = Field(default=0, ge=0)
    stop_after_time: int = Field(default=0, ge=0)

    # 断点续传
    skip_sent: bool = True

    # 队列设置
    delay_between_tasks: float = Field(default=30.0, ge=0.0)

    @model_validator(mode='after')
    def check_logic(self) -> 'SenderConfig':
        """业务逻辑级校验：最小不能大于最大"""
        if self.min_delay > self.max_delay:
            raise ValueError("最小延迟不能大于最大延迟")
        if self.burst_enabled and self.rest_min > self.rest_max:
            raise ValueError("爆发休息的最小值不能大于最大值")
        return self

    def __setattr__(self, name: str, value: Any) -> None:
        """赋值前整模型试算；失败则保持原状。

        ``validate_assignment`` 的赋值不原子：字段级校验失败会拒绝写入，
        但 ``model_validator(mode='after')`` 在赋值后运行、失败不回滚，
        跨字段规则（如最小延迟 ≤ 最大延迟）会留下脏值。
        先在副本上试算可保证「抛异常 = 模型未被改动」。
        """
        if name in type(self).model_fields:
            probe = self.model_dump()
            probe[name] = value
            type(self).model_validate(probe)
        super().__setattr__(name, value)
