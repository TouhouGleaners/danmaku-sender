import ttkbootstrap as ttk
from ttkbootstrap.tooltip import ToolTip

from ..config.shared_data import SharedDataModel


class SettingsTab(ttk.Frame):
    def __init__(self, parent, model: SharedDataModel):
        super().__init__(parent, padding=15)
        self.model = model
        self.columnconfigure(0, weight=1)
        self._create_widgets()

    def _create_widgets(self):
        """创建并布局标签页中的所有UI控件"""
        # --- 身份凭证输入区 ---
        auth_frame = ttk.Labelframe(self, text="身份凭证 (Cookie)", padding=15)
        auth_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        auth_frame.columnconfigure(1, weight=1)

        # SESSDATA
        ttk.Label(auth_frame, text="SESSDATA:").grid(row=0, column=0, sticky="w", padx=5, pady=8)
        self.sessdata_entry = ttk.Entry(auth_frame, show="*", textvariable=self.model.sessdata, takefocus=0)
        self.sessdata_entry.grid(row=0, column=1, sticky="ew", padx=5)
        ToolTip(self.sessdata_entry, "SESSDATA | 请勿泄露")

        # BILI_JCT
        ttk.Label(auth_frame, text="BILI_JCT:").grid(row=1, column=0, sticky="w", padx=5, pady=8)
        self.bili_jct_entry = ttk.Entry(auth_frame, show="*", textvariable=self.model.bili_jct, takefocus=0)
        self.bili_jct_entry.grid(row=1, column=1, sticky="ew", padx=5)
        ToolTip(self.bili_jct_entry, "BILI_JCT | 请勿泄露")

        # --- 系统设置区 ---
        sys_frame = ttk.Labelframe(self, text="系统设置", padding=15)
        sys_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        sys_frame.columnconfigure(0, weight=1)

        # 阻止系统休眠
        sleep_chk = ttk.Checkbutton(
            sys_frame,
            text="任务运行时阻止电脑休眠",
            variable=self.model.prevent_sleep,
            bootstyle="round-toggle"
        )
        sleep_chk.grid(row=0, column=0, sticky="w", padx=5)
        ToolTip(sleep_chk, "勾选后，在发送或监视弹幕时，将禁止Windows进入睡眠状态。\n(保持网络和CPU运行，但允许屏幕关闭)")

        # --- 网络设置区 ---
        net_frame = ttk.Labelframe(self, text="网络设置", padding=15)
        net_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        net_frame.columnconfigure(0, weight=1)

        proxy_chk = ttk.Checkbutton(
            net_frame, 
            text="使用系统代理 (兼容VPN/加速器)", 
            variable=self.model.use_system_proxy, 
            bootstyle="round-toggle"
        )
        proxy_chk.grid(row=0, column=0, sticky="w", padx=5)
        ToolTip(proxy_chk, "默认开启。\n如果你开启了VPN/加速器但无法发送弹幕，尝试【取消勾选】此项以强制直连。")

        # 提示信息
        info_label = ttk.Label(
            self, 
            text="ℹ️ 提示：凭证修改后会自动保存，重启软件后依然有效。",
            bootstyle="secondary"
        )
        info_label.grid(row=3, column=0, sticky="w", padx=15, pady=(10, 5))