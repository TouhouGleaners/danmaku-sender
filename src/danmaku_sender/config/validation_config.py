from pydantic import BaseModel, ConfigDict, Field


class ValidationConfig(BaseModel):
    """校验规则"""
    model_config = ConfigDict(validate_assignment=True)

    # 用户自定义规则
    enabled: bool = True
    blocked_keywords: list[str] = Field(default_factory=list)
