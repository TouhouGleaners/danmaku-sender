from pydantic import Field

from .base import AtomicModel


class ValidationConfig(AtomicModel):
    """校验规则"""

    # 用户自定义规则
    enabled: bool = True
    blocked_keywords: list[str] = Field(default_factory=list)
