from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage, QPainter, QPainterPath


class QtImageProcessor:
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