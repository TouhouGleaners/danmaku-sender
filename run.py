import sys
import logging

from PySide6.QtWidgets import QApplication

from src.danmaku_sender.ui.main_window import MainWindow
from src.danmaku_sender.utils.log_utils import GuiLoggingHandler


def setup_logging():
    gui_handler = GuiLoggingHandler()
    gui_handler.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s - %(message)s'))
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(gui_handler)

def main():
    setup_logging()

    app = QApplication(sys.argv)
    
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()