import json
import logging

from pydantic import BaseModel, ValidationError

from danmaku_sender.config import (
    GlobalConfig,
    MonitorConfig,
    SenderConfig,
    ThemeConfig,
    ValidationConfig,
)
from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.utils.file_utils import atomic_write, read_json

logger = logging.getLogger(__name__)

CONFIG_PATH = AppInfo.Paths.CONFIG


class ConfigManager:
    """配置管理器"""

    def save(self, state: AppState) -> None:
        """保存非敏感配置到 config.json"""
        config_data = {
            "global": state.global_config.model_dump(),
            "sender": state.sender_config.model_dump(),
            "monitor": state.monitor_config.model_dump(),
            "theme": state.theme_config.model_dump(mode="json"),
            "validation": state.validation_config.model_dump()
        }

        try:
            with atomic_write(CONFIG_PATH) as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            logger.info(f"配置已保存: {CONFIG_PATH}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def load(self, state: AppState) -> None:
        """从 config.json 加载配置到 state"""
        data = read_json(CONFIG_PATH)
        if not isinstance(data, dict):
            logger.info("未找到配置文件或格式异常，使用默认设置。")
            return

        def _apply_section[T: BaseModel](key: str, model_class: type[T], target: T) -> None:
            """把 config.json 的段校验后原地灌进 target。

            必须原地更新、不得换实例：UI 绑定表持有 target 的引用，
            换实例会让既有绑定指向孤儿模型。
            """
            if key not in data:
                return
            try:
                fresh = model_class.model_validate(data[key])
            except ValidationError as e:
                logger.warning(f"模块 [{key}] 配置存在非法值，已回退为安全默认值。详情:\n{e}")
                return
            # 只落文件里出现过的字段：exclude=True 等不参与序列化的字段
            # 不能让 fresh 的默认值把它们冲掉
            raw = data[key]
            for name in model_class.model_fields:
                if name in raw:
                    object.__setattr__(target, name, getattr(fresh, name))

        _apply_section("global", GlobalConfig, state.global_config)
        _apply_section("sender", SenderConfig, state.sender_config)
        _apply_section("monitor", MonitorConfig, state.monitor_config)
        _apply_section("theme", ThemeConfig, state.theme_config)
        _apply_section("validation", ValidationConfig, state.validation_config)

        logger.info(f"配置文件加载与校验流程结束[{CONFIG_PATH}]。")
