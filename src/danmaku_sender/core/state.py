import time
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, model_validator
from PySide6.QtCore import QObject, Signal

from .entities.danmaku import Danmaku


@dataclass
class ApiAuthConfig:
    sessdata: str
    bili_jct: str
    use_system_proxy: bool


class SenderConfig(BaseModel):
    """发送器的配置数据"""
    model_config = ConfigDict(validate_assignment=True)  # 赋值时校验

    # 延迟设置
    min_delay: float = Field(default=8.0, ge=0.1)
    max_delay: float = Field(default=8.5, ge=0.1)

    # 爆发模式
    burst_size: int = Field(default=3, ge=0)
    rest_min: float = Field(default=40.0, ge=0.0)
    rest_max: float = Field(default=45.0, ge=0.0)

    # 自动停止
    stop_after_count: int = Field(default=0, ge=0)
    stop_after_time: int = Field(default=0, ge=0)

    # 系统设置
    prevent_sleep: bool = True
    use_system_proxy: bool = True

    # 断点续传
    skip_sent: bool = True

    @model_validator(mode='after')
    def check_logic(self) -> 'SenderConfig':
        """业务逻辑级校验：最小不能大于最大"""
        # 抛出错误，外层加载时会回退默认值
        if self.min_delay > self.max_delay:
            raise ValueError("最小延迟不能大于最大延迟")
        if self.burst_size > 1 and self.rest_min > self.rest_max:
            raise ValueError("爆发休息的最小值不能大于最大值")
        return self


class MonitorConfig(BaseModel):
    """监视器的配置数据"""
    model_config = ConfigDict(validate_assignment=True)  # 赋值时校验

    refresh_interval: int = Field(default=60, ge=10)  # 刷新间隔，单位秒

    # 复用全局设置
    prevent_sleep: bool = True
    use_system_proxy: bool = True

    stats_baseline: float = Field(default=0.0, exclude=True)


class ValidationConfig(BaseModel):
    """校验规则"""
    model_config = ConfigDict(validate_assignment=True)  # 赋值时校验

    # 用户自定义规则
    enabled: bool = True
    blocked_keywords: list[str] = Field(default_factory=list)


@dataclass
class VideoState:
    """视频相关的运行时状态"""
    bvid: str = ""
    video_title: str = "（未获取到视频标题）"
    selected_cid: int | None = None
    selected_part_name: str = ""
    selected_part_duration_ms: int = 0
    loaded_danmakus: list[Danmaku] = field(default_factory=list)

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
    credentialsChanged = Signal()
    senderLogReceived = Signal(str)
    monitorLogReceived = Signal(str)
    senderActiveChanged = Signal()
    monitorActiveChanged = Signal()
    editorDirtyChanged = Signal()

    def __init__(self):
        super().__init__()
        self.app_launch_time = time.time()

        # 核心凭证
        self._sessdata: str = ""
        self._bili_jct: str = ""

        # 各模块配置
        self.sender_config = SenderConfig()
        self.monitor_config = MonitorConfig()
        self.validation_config = ValidationConfig()

        # 运行时状态
        self.video_state = VideoState()

        self._sender_is_active: bool = False
        self._monitor_is_active: bool = False
        self._editor_is_dirty: bool = False

    @property
    def sessdata(self) -> str:
        return self._sessdata

    @sessdata.setter
    def sessdata(self, value: str):
        if self._sessdata != value:
            self._sessdata = value
            self.credentialsChanged.emit()

    @property
    def bili_jct(self) -> str:
        return self._bili_jct

    @bili_jct.setter
    def bili_jct(self, value: str):
        if self._bili_jct != value:
            self._bili_jct = value
            self.credentialsChanged.emit()

    @property
    def sender_is_active(self) -> bool:
        return self._sender_is_active

    @sender_is_active.setter
    def sender_is_active(self, value: bool):
        if self._sender_is_active != value:
            self._sender_is_active = value
            self.senderActiveChanged.emit()

    @property
    def monitor_is_active(self) -> bool:
        return self._monitor_is_active

    @monitor_is_active.setter
    def monitor_is_active(self, value: bool):
        if self._monitor_is_active != value:
            self._monitor_is_active = value
            self.monitorActiveChanged.emit()

    @property
    def editor_is_dirty(self) -> bool:
        return self._editor_is_dirty

    @editor_is_dirty.setter
    def editor_is_dirty(self, value: bool):
        if self._editor_is_dirty != value:
            self._editor_is_dirty = value
            self.editorDirtyChanged.emit()

    def get_api_auth(self) -> ApiAuthConfig:
        """
        工厂方法：从当前状态生成一个用于初始化的 API 凭证对象。
        """
        return ApiAuthConfig(
            sessdata=self.sessdata,
            bili_jct=self.bili_jct,
            use_system_proxy=self.sender_config.use_system_proxy
        )