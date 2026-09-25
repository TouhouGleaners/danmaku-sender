from .base import AtomicModel


class GlobalConfig(AtomicModel):
    """全局系统设置（跨发送器/监视器共享，只此一份）"""

    # 系统设置
    prevent_sleep: bool = True
    use_system_proxy: bool = True
