import json
import logging
from pathlib import Path
from platformdirs import user_data_dir

from ..config.app_config import AppInfo
from ..core.state import AppState


logger = logging.getLogger("ConfigManager")

def get_config_path() -> Path:
    config_dir = Path(user_data_dir(AppInfo.NAME_EN, AppInfo.AUTHOR))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"

def save_app_config(state: AppState):
    """保存非敏感配置到 config.json"""
    config_data = {
        "sender": state.sender_config.model_dump(),
        "monitor": state.monitor_config.model_dump(),
        "validation": state.validation_config.model_dump()
    }

    try:
        path = get_config_path()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2)
        logger.info(f"配置已保存: {path}")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

def load_app_config(state: AppState):
    """从 config.json 加载配置到 state"""
    path = get_config_path()
    if not path.exists():
        logger.info("未找到配置文件，使用默认设置。")
        return

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if "sender" in data:
            state.sender_config = state.sender_config.model_validate(data["sender"])

        if "monitor" in data:
            state.monitor_config = state.monitor_config.model_validate(data["monitor"])

        if "validation" in data:
            state.validation_config = state.validation_config.model_validate(data["validation"])

        logger.info("配置加载并校验成功。")
    except Exception as e:
        logger.warning(f"加载配置失败（格式损坏或数据不合法），将回退使用默认值: {e}")