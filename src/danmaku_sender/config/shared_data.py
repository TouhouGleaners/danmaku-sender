import ttkbootstrap as ttk
from dataclasses import dataclass, field


@dataclass
class SenderConfig:
    """发送器的配置数据"""
    sessdata: str = ""
    bili_jct: str = ""

    # 普通延迟
    min_delay: float = 8.0
    max_delay: float = 8.5

    # 爆发延迟
    burst_size: int = 3
    rest_min: float = 40.0
    rest_max: float = 45.0

    # 系统设置
    prevent_sleep: bool = True

    # 网络设置
    use_system_proxy: bool = True

    def is_valid(self) -> bool:
        """自身的数据校验逻辑"""
        basic_valid = (
            self.min_delay > 0 and 
            self.max_delay > 0 and 
            self.min_delay <= self.max_delay and
            bool(self.sessdata) and 
            bool(self.bili_jct)
        )

        if not basic_valid:
            return False
        
        if self.burst_size < 0:
            return False
        
        if self.burst_size > 1:
            if self.rest_min < 0 or self.rest_max < 0 or self.rest_min > self.rest_max:
                return False
        
        return True


@dataclass
class MonitorConfig:
    """监视器的配置数据"""
    sessdata: str = ""
    bili_jct: str = ""
    interval: int = 60
    tolerance: int = 500

    prevent_sleep: bool = True
    use_system_proxy: bool = True

    def is_valid(self) -> bool:
        return (self.interval > 0 and 
                self.tolerance >= 0 and 
                bool(self.sessdata) and 
                bool(self.bili_jct))

    
@dataclass
class VideoState:
    """视频相关的运行时状态"""
    bvid: str = ""
    video_title: str = "（未获取到视频标题）"
    selected_cid: int | None = None
    selected_part_name: str = ""
    selected_part_duration_ms: int = 0
    loaded_danmakus: list[dict] = field(default_factory=list)

    @property
    def danmaku_count(self) -> int:
        return len(self.loaded_danmakus)
    
    @property
    def is_ready_to_send(self) -> bool:
        """是否具备发送/监视的基本条件"""
        return bool(self.bvid and self.selected_cid and self.loaded_danmakus)


class SharedDataModel:
    """ViewModel: 负责连接 UI (StringVar) 和 纯数据 (Dataclass)"""
    def __init__(self):
        # --- 核心数据实体 ---
        self._video_state = VideoState()

        # --- UI 绑定变量 ---
        # 身份凭证
        self.sessdata = ttk.StringVar()
        self.bili_jct = ttk.StringVar()

        # 核心参数 UI
        self.bvid = ttk.StringVar()
        self.part_var = ttk.StringVar()
        self.source_danmaku_filepath = ttk.StringVar()
        self.video_title = ttk.StringVar(value="（未获取到视频标题）")

        # 辅助数据 (仅用于 UI 下拉框逻辑)
        self.cid_parts_map = {}
        self.ordered_cids = []
        self.ordered_durations = []

        # 高级设置 (UI)
        # 实例化默认配置对象
        _default_config = SenderConfig()

        self.min_delay = ttk.StringVar(value=str(_default_config.min_delay))
        self.max_delay = ttk.StringVar(value=str(_default_config.max_delay))
        self.burst_size = ttk.StringVar(value=str(_default_config.burst_size))
        self.rest_min = ttk.StringVar(value=str(_default_config.rest_min))
        self.rest_max = ttk.StringVar(value=str(_default_config.rest_max))

        # 系统设置 (UI)
        self.prevent_sleep = ttk.BooleanVar(value=True)
        self.use_system_proxy = ttk.BooleanVar(value=True)

        # 监视器设置 (UI)
        self.monitor_interval = ttk.StringVar(value="60")
        self.time_tolerance = ttk.StringVar(value="500")

        # 全局校验器脏状态
        self.validator_is_dirty = False  # True 表示校验器有未应用的修改，SenderTab 应该拦截发送

        # 状态栏信息
        self.sender_status_text = ttk.StringVar(value="发送器：待命")
        self.sender_progress_var = ttk.DoubleVar(value=0.0)
        self.monitor_status_text = ttk.StringVar(value="监视器：待命")
        self.monitor_progress_var = ttk.DoubleVar(value=0.0)

        # --- 绑定 UI 变化到数据实体 ---
        self.bvid.trace_add("write", self._sync_bvid)
        self.part_var.trace_add("write", self._sync_part_name)
        self.video_title.trace_add("write", self._sync_video_title)
    
    def _sync_bvid(self, *args):
        self._video_state.bvid = self.bvid.get()

    def _sync_part_name(self, *args):
        self._video_state.selected_part_name = self.part_var.get()

    def _sync_video_title(self, *args):
        self._video_state.video_title = self.video_title.get()

    @property
    def loaded_danmakus(self) -> list[dict]:
        return self._video_state.loaded_danmakus
    
    @loaded_danmakus.setter
    def loaded_danmakus(self, value: list[dict]):
        self._video_state.loaded_danmakus = value

    @property
    def selected_cid(self) -> int | None:
        return self._video_state.selected_cid
    
    @selected_cid.setter
    def selected_cid(self, value: int | None):
        self._video_state.selected_cid = value
        
    @property
    def selected_part_duration_ms(self) -> int:
        return self._video_state.selected_part_duration_ms
    
    @selected_part_duration_ms.setter
    def selected_part_duration_ms(self, value: int):
        self._video_state.selected_part_duration_ms = value


    def get_sender_config(self) -> SenderConfig | None:
        """
        从 UI 变量中提取并构建 SenderConfig 对象。
        如果转换失败（如延迟不是数字），返回 None。
        """
        try:
            config = SenderConfig(
                sessdata=self.sessdata.get().strip(),
                bili_jct=self.bili_jct.get().strip(),
                min_delay=float(self.min_delay.get()),
                max_delay=float(self.max_delay.get()),
                burst_size=int(self.burst_size.get()),
                rest_min=float(self.rest_min.get()),
                rest_max=float(self.rest_max.get()),
                prevent_sleep=self.prevent_sleep.get(),
                use_system_proxy=self.use_system_proxy.get()
            )
            return config
        except ValueError:
            return None
        
    def get_monitor_config(self) -> MonitorConfig | None:
        """
        从 UI 变量提取并构建 MonitorConfig 对象。
        """
        try:
            config = MonitorConfig(
                sessdata=self.sessdata.get().strip(),
                bili_jct=self.bili_jct.get().strip(),
                interval=int(self.monitor_interval.get()),
                tolerance=int(self.time_tolerance.get()),
                prevent_sleep=self.prevent_sleep.get(),
                use_system_proxy=self.use_system_proxy.get()
            )
            return config
        except ValueError:
            return None

    def get_video_state(self) -> VideoState:
        """获取当前的视频状态对象 (用于 MonitorTab 读取)"""
        self._video_state.bvid = self.bvid.get()
        self._video_state.video_title = self.video_title.get()
        return self._video_state