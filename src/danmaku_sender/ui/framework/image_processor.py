import logging

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPixmap, QImage, QPainter, QPainterPath
from PySide6.QtSvg import QSvgRenderer


logger = logging.getLogger("App.System.ImageProcessor")


class QtImageProcessor:
    @staticmethod
    def render_svg(raw_bytes: bytes, logical_size: int, dpr: float = 1.0, *, preserve_aspect: bool = False) -> QPixmap:
        """
        将 SVG 字节流高质量渲染为 Pixmap

        raw_bytes: SVG 文件内容
        logical_size: 逻辑尺寸。preserve_aspect=False 时为正方形边长，True 时为高度（宽度按 viewBox 宽高比计算）
        dpr: 屏幕缩放比例 (devicePixelRatio)
        preserve_aspect: 是否保持 SVG 原始宽高比
        """
        renderer = QSvgRenderer(raw_bytes)
        if not renderer.isValid():
            logger.error("SVG 渲染器初始化失败: 数据可能已损坏")
            return QPixmap()

        if preserve_aspect:
            vb = renderer.viewBoxF()
            aspect = vb.width() / vb.height() if vb.height() > 0 else 1.0
            logical_w = max(1, int(logical_size * aspect))
        else:
            logical_w = logical_size

        phys_w = max(1, int(logical_w * dpr))
        phys_h = max(1, int(logical_size * dpr))

        pixmap = QPixmap(phys_w, phys_h)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        renderer.render(painter, QRectF(0, 0, float(phys_w), float(phys_h)))
        painter.end()

        pixmap.setDevicePixelRatio(dpr)
        return pixmap

    @staticmethod
    def make_circular_pixmap(raw_bytes: bytes, logical_size: int, device_pixel_ratio: float = 1.0) -> QPixmap:
        """
        DPI 感知的图像处理

        logical_size: UI 设计的逻辑像素 (36)
        device_pixel_ratio: 屏幕缩放比例 (1.0, 1.5, 2.0 ...)
        """
        if not raw_bytes or logical_size <= 0 or device_pixel_ratio <= 0:
            return QPixmap()

        image = QImage.fromData(raw_bytes)
        if image.isNull():
            return QPixmap()

        physical_size = max(1, int(logical_size * device_pixel_ratio))

        image = image.scaled(physical_size, physical_size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)

        pixmap = QPixmap(physical_size, physical_size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        path = QPainterPath()
        path.addEllipse(0, 0, physical_size, physical_size)
        painter.setClipPath(path)
        painter.drawImage(0, 0, image)
        painter.end()

        pixmap.setDevicePixelRatio(device_pixel_ratio)
        return pixmap