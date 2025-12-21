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

        # 提示信息
        info_label = ttk.Label(
            self, 
            text="ℹ️ 提示：凭证修改后会自动保存，重启软件后依然有效。",
            bootstyle="secondary"
        )
        info_label.grid(row=1, column=0, sticky="w", padx=15, pady=(10, 5))