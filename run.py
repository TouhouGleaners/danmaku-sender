import sys
from pathlib import Path


root_dir = Path(__file__).resolve().parent
src_dir = root_dir / 'src'
sys.path.insert(0, str(src_dir))


from danmaku_sender.ui.main_app import main


if __name__ == '__main__':
    main()