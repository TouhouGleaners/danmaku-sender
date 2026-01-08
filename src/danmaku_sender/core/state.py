import json
from dataclasses import dataclass, field, asdict

from PySide6.QtCore import QObject, Signal


@dataclass
class ApiAuthConfig:
    sessdata: str
    bili_jct: str
    use_system_proxy: bool


@dataclass
class SenderConfig:
    """发送器的配置数据"""
    # 延迟设置
    min_delay: float = 8.0
    max_delay: float = 8.5
    
    # 爆发模式
    burst_size: int = 3
    rest_min: float = 40.0
    rest_max: float = 45.0
    
    # 自动停止
    stop_after_count: int = 0
    stop_after_time: int = 0

    # 系统设置
    prevent_sleep: bool = True
    use_system_proxy: bool = True

    def is_valid(self) -> bool:
        """简单的逻辑校验"""
        if self.min_delay > self.max_delay:
            return False
        if self.burst_size > 1 and self.rest_min > self.rest_max:
            return False
        return True

    def to_dict(self):
        return asdict(self)
    
    def from_dict(self, data: dict):
        if not data:
            return
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)
            
    

@dataclass
class MonitorConfig:
    """监视器的配置数据"""
    refresh_interval: int = 60  # 刷新间隔，单位秒
    tolerance: int = 500
    
    # 复用全局设置
    prevent_sleep: bool = True
    use_system_proxy: bool = True

    def to_dict(self):
        return asdict(self)
    
    def from_dict(self, data: dict):
        if not data:
            return
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)


@dataclass
class VideoState:
    """视频相关的运行时状态"""
    bvid: str = ""
    video_title: str = "（未获取到视频标题）"
    selected_cid: int | None = None
    selected_part_name: str = ""
    selected_part_duration_ms: int = 0
    loaded_danmakus: list[dict] = field(default_factory=list)
    
    # CID 到 分P名 的映射
    cid_parts_map: dict = field(default_factory=dict)

    @property
    def is_ready_to_send(self) -> bool:
        return bool(self.bvid) and (self.selected_cid is not None) and bool(self.loaded_danmakus)
    
    @property
    def danmaku_count(self) -> int:
        return len(self.loaded_danmakus)
    

class AppState(QObject):
    """
    应用程序全局状态管理。
    继承自 QObject 以支持信号槽机制，实现 UI 与 逻辑 的解耦。
    """
    credentials_changed = Signal(str, str)
    sender_log_received = Signal(str)
    monitor_log_received = Signal(str)

    def __init__(self):
        super().__init__()
        
        # 核心凭证
        self.sessdata: str = ""
        self.bili_jct: str = ""

        # 各模块配置
        self.sender_config = SenderConfig()
        self.monitor_config = MonitorConfig()

        # 运行时状态
        self.video_state = VideoState()

        # True 表示校验器有未应用的修改，SenderTab 拦截发送
        self.validator_is_dirty: bool = False

    def update_credentials(self, sessdata: str, bili_jct: str):
        """更新凭证并通知监听者"""
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.credentials_changed.emit(sessdata, bili_jct)

    def get_api_auth(self) -> ApiAuthConfig:
        """
        工厂方法：从当前状态生成一个用于初始化的 API 凭证对象。
        """
        return ApiAuthConfig(
            sessdata=self.sessdata,
            bili_jct=self.bili_jct,
            use_system_proxy=self.sender_config.use_system_proxy
        )

    def log_sender(self, message: str):
        self.sender_log_received.emit(message)

    def log_monitor(self, message: str):
        self.monitor_log_received.emit(message)