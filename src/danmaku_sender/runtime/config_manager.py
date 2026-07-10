import json
import logging
from pathlib import Path
from platformdirs import user_data_dir

from pydantic import ValidationError, BaseModel

from ..config.app_config import AppInfo
from ..core.config import SenderConfig, MonitorConfig, ValidationConfig
from .app_state import AppState


logger = logging.getLogger("App.System.Config")


class ConfigManager:
    """配置管理器"""

    def get_config_path(self) -> Path:
        config_dir = Path(user_data_dir(AppInfo.NAME_EN, AppInfo.AUTHOR))
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.json"

    def save(self, state: AppState) -> None:
        """保存非敏感配置到 config.json"""
        config_data = {
            "sender": state.sender_config.model_dump(),
            "monitor": state.monitor_config.model_dump(),
            "validation": state.validation_config.model_dump()
        }

        try:
            path = self.get_config_path()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)
            logger.info(f"配置已保存: {path}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def load(self, state: AppState) -> None:
        """从 config.json 加载配置到 state"""
        path = self.get_config_path()
        if not path.exists():
            logger.info("未找到配置文件，使用默认设置。")
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"配置文件 JSON 格式损坏，将使用默认设置[{path}]: {e}")
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

        logger.info(f"配置文件加载与校验流程结束[{path}]。")
