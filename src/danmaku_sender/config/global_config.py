from pydantic import ConfigDict

from danmaku_sender.types.models.evented_model import EventedModel


class GlobalConfig(EventedModel):
    """全局系统设置（跨发送器/监视器共享，只此一份）"""
    model_config = ConfigDict(validate_assignment=True)

    # 系统设置
    prevent_sleep: bool = True
    use_system_proxy: bool = True
