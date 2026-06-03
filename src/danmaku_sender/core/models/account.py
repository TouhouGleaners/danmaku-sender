from pydantic import BaseModel


class AccountCredential(BaseModel):
    """已保存的账号凭证"""
    uid: int = 0
    name: str = ""
    avatar_url: str = ""
    sessdata: str
    bili_jct: str
