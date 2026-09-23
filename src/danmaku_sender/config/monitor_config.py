from pydantic import BaseModel, ConfigDict, Field


class MonitorConfig(BaseModel):
    """监视器的配置数据"""
    model_config = ConfigDict(validate_assignment=True)

    refresh_interval: int = Field(default=60, ge=10)
