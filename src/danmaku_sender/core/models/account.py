from pydantic import BaseModel, Field


def _mask(value: str) -> str:
    """遮蔽凭据：保留前4后4，中间用 * 替代，总长不超过 20"""
    if len(value) <= 4:
        return "*" * len(value)
    if len(value) <= 8:
        return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"
    stars = min(len(value) - 8, 8)
    return f"{value[:4]}{'*' * stars}{value[-4:]}"


class AccountCredential(BaseModel):
    """已保存的账号凭证"""
    uid: int = 0
    name: str = ""
    avatar_url: str = ""
    sessdata: str = ""
    bili_jct: str = ""
    is_valid: bool | None = Field(default=None, exclude=True)  # None=未检测, True=有效, False=失效 (UI 瞬态)

    @property
    def masked_sessdata(self) -> str:
        return _mask(self.sessdata)

    @property
    def masked_bili_jct(self) -> str:
        return _mask(self.bili_jct)
