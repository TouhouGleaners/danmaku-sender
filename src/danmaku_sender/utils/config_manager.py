import json
import logging
from pathlib import Path
from platformdirs import user_data_dir

from pydantic import ValidationError

from ..config.app_config import AppInfo
from ..core.state import AppState, SenderConfig, MonitorConfig, ValidationConfig


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
    except json.JSONDecodeError as e:
        logger.error(f"配置文件 JSON 格式完全损坏，将使用默认设置: {e}")
        return
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        return

    # 校验配置
    if "sender" in data:
        try:
            state.sender_config = SenderConfig.model_validate(data["sender"])
        except ValidationError as e:
            logger.warning(f"Sender 配置存在非法值被拦截，已回退为安全默认值。详情:\n{e}")

    if "monitor" in data:
        try:
            state.monitor_config = MonitorConfig.model_validate(data["monitor"])
        except ValidationError as e:
            logger.warning(f"Monitor 配置存在非法值被拦截，已回退为安全默认值。详情:\n{e}")

    if "validation" in data:
        try:
            state.validation_config = ValidationConfig.model_validate(data["validation"])
        except ValidationError as e:
            logger.warning(f"Validation 配置存在非法值被拦截，已回退为安全默认值。详情:\n{e}")

    logger.info("配置文件加载与校验流程结束。")