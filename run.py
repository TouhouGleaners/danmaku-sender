import sys
import os
from pathlib import Path


current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

from src.danmaku_sender.main import main


if __name__ == "__main__":
    main()