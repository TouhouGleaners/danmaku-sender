"""历史页的弹幕详情对话框。"""
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QFrame, QLabel, QWidget

from danmaku_sender.types.models.common import DanmakuStatus
from danmaku_sender.types.models.video import VideoInfo


class DanmakuDetailDialog(QDialog):
    """单条弹幕的详情档案。

    Args:
        record (dict): 弹幕历史记录行。
        video_info (VideoInfo | None): 所属视频信息；None 表示尚未获取。
        parent (QWidget | None): 父控件。

    Typical usage example::

        dialog = DanmakuDetailDialog(record, video_info, self)
        dialog.exec()
    """

    def __init__(self, record: dict, video_info: VideoInfo | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("弹幕详情档案")
        self.resize(500, 450)
        self._record = record
        self._video_info = video_info
        self._create_ui()

    def _create_ui(self) -> None:
        """搭建表单布局。"""
        layout = QFormLayout(self)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        def add_row(label: str, value: Any) -> None:
            """向表单追加一行标签与值。

            Args:
                label (str): 标签文字。
                value (Any): 显示值，转换为文本后按字面显示。
            """
            lbl = QLabel(str(value))
            lbl.setTextFormat(Qt.TextFormat.PlainText)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setWordWrap(True)
            layout.addRow(f"{label}:", lbl)

        # --- 视频元数据 ---
        layout.addRow(QLabel("<b>[ 视频信息 ]</b>"))

        cid = self._record['cid']
        bvid = self._record['bvid']

        # 尝试从 VideoInfo 对象获取分P信息
        part_idx = "未知"
        part_title = "-"
        video_title = "加载中或未知..."

        if self._video_info:
            video_title = self._video_info.title
            part = self._video_info.get_part_by_cid(cid)
            if part:
                part_idx = f"P{part.page}"
                part_title = part.title

        add_row("BVID", bvid)
        add_row("视频标题", video_title)
        add_row("分P序号", part_idx)
        add_row("分P标题", part_title)
        add_row("CID", cid)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addRow(line)

        # --- 弹幕参数 ---
        layout.addRow(QLabel("<b>[ 弹幕参数 ]</b>"))

        status_map = {
            DanmakuStatus.PENDING: "⏳ 待验证",
            DanmakuStatus.VERIFIED: "✅ 已存活",
            DanmakuStatus.LOST: "❌ 已丢失"
        }
        status = status_map.get(self._record['status'], "未知")
        if self._record.get('is_visible', 1) == 0:
            status += " (API返回屏蔽)"

        add_row("当前状态", status)
        add_row("弹幕内容", self._record['msg'])
        add_row("DmID", self._record['dmid'])
        add_row("发送时间", datetime.fromtimestamp(self._record['ctime']).strftime('%Y-%m-%d %H:%M:%S'))
        add_row("视频内时间", f"{self._record['progress']} ms")
        add_row("字号", self._record['fontsize'])
        add_row("颜色", f"#{self._record['color']:06x}")
