import json
import logging

from pydantic import ValidationError, BaseModel

from .app_state import AppState

from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.config import SenderConfig, MonitorConfig, ValidationConfig


logger = logging.getLogger("App.System.Config")

CONFIG_PATH = AppInfo.Paths.CONFIG


class ConfigManager:
    """配置管理器"""

    def save(self, state: AppState) -> None:
        """保存非敏感配置到 config.json"""
        config_data = {
            "sender": state.sender_config.model_dump(),
            "monitor": state.monitor_config.model_dump(),
            "validation": state.validation_config.model_dump()
        }

        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)
            logger.info(f"配置已保存: {CONFIG_PATH}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def load(self, state: AppState) -> None:
        """从 config.json 加载配置到 state"""
        if not CONFIG_PATH.exists():
            logger.info("未找到配置文件，使用默认设置。")
            return

        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"配置文件 JSON 格式损坏，将使用默认设置[{CONFIG_PATH}]: {e}")
            return
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
            return

        def _load_section[T: BaseModel](key: str, model_class: type[T], default_instance: T) -> T:
            if key in data:
                try:
                    return model_class.model_validate(data[key])
                except ValidationError as e:
                    logger.warning(f"模块 [{key}] 配置存在非法值，已回退为安全默认值。详情:\n{e}")
            return default_instance

        # 校验配置
        state.sender_config = _load_section("sender", SenderConfig, state.sender_config)
        state.monitor_config = _load_section("monitor", MonitorConfig, state.monitor_config)
        state.validation_config = _load_section("validation", ValidationConfig, state.validation_config)

        logger.info(f"配置文件加载与校验流程结束[{CONFIG_PATH}]。")
