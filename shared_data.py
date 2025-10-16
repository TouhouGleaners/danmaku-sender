import ttkbootstrap as ttk


class SharedDataModel:
    """
    一个集中的数据模型，用于在GUI的不同组件之间共享状态。
    使用Tkinter的变量类型 (StringVar, BooleanVar等) 可以让UI组件自动响应数据变化。
    """
    def __init__(self):
        # --- 身份凭证 ---
        # 这些变量将直接绑定到凭证输入框
        self.sessdata = ttk.StringVar()
        self.bili_jct = ttk.StringVar()

        # --- 核心参数 ---
        self.bvid = ttk.StringVar()
        self.part_var = ttk.StringVar()
        self.danmaku_xml_path = ttk.StringVar()

        self.cid_parts_map = {}  # 存储 {cid: 'title'} 的映射关系
        self.ordered_cids = []  # 存储一个与下拉框显示顺序完全对应的CID列表
        self.selected_cid = None

        # --- 高级设置 (仅SenderTab使用) ---
        self.min_delay = ttk.StringVar(value="5.0")
        self.max_delay = ttk.StringVar(value="10.0")

        # --- 高级设置 (仅MonitorTab使用) ---
        self.monitor_interval = ttk.StringVar(value="60")  # 刷新间隔，默认60秒
        self.time_tolerance = ttk.StringVar(value="500")  # 时间容差，默认500毫秒
        self.monitor_progress_var = ttk.DoubleVar(value=0.0)
        self.parsed_local_danmakus = []  # 解析后的本地弹幕列表

        # --- 状态信息 (用于状态栏显示) ---
        # 这些变量将由后台任务更新，并由状态栏显示
        self.sender_status_text = ttk.StringVar(value="发送器：待命")
        self.monitor_status_text = ttk.StringVar(value="监视器：待命")