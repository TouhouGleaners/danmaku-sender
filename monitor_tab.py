import ttkbootstrap as ttk

class MonitorTab(ttk.Frame):
    def __init__(self, parent, model, app):
        """
        弹幕监视器标签页 (待开发)
        """
        super().__init__(parent, padding=15)
        self.model = model
        self.app = app

        self._create_widgets()

    def _create_widgets(self):
        """创建占位控件"""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        
        label = ttk.Label(
            self, 
            text="弹幕监视器功能正在开发中...", 
            font=("", 16, "bold"), 
            style="secondary.TLabel",
            anchor="center"
        )
        label.grid(row=0, column=0, sticky="nsew")
