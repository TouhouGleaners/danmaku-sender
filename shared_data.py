import tkinter as tk


class SharedDataModel:
    """
    一个集中的数据模型，用于在GUI的不同组件之间共享状态。
    使用Tkinter的变量类型 (StringVar, BooleanVar等) 可以让UI组件自动响应数据变化。
    """
    def __init__(self):
        # --- 身份凭证 ---
        # 这些变量将直接绑定到凭证输入框
        self.sessdata = tk.StringVar()
        self.bili_jct = tk.StringVar()

        # --- 核心参数 ---
        self.bvid = tk.StringVar()
        self.part_var = tk.StringVar()
        self.danmaku_xml_path = tk.StringVar()
        
        # --- 弹幕文件路径 ---
        self.danmaku_xml_path = tk.StringVar()

        # --- 高级设置 ---
        # 这些将绑定到高级设置里的延迟输入框
        self.min_delay = tk.StringVar(value="5.0")
        self.max_delay = tk.StringVar(value="10.0")

        # --- 状态信息 (用于状态栏显示) ---
        # 这些变量将由后台任务更新，并由状态栏显示
        self.sender_status_text = tk.StringVar(value="发送状态：待命")
        self.verify_status_text = tk.StringVar(value="校验状态：未开始")