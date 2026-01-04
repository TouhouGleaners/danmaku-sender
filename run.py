import sys
import logging

from PySide6.QtWidgets import QApplication

from src.danmaku_sender.ui.main_window import MainWindow


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    app = QApplication(sys.argv)
    
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()