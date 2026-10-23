"""配置落盘存储：config.json 读写。"""
import json
import logging

from pydantic import ValidationError

from danmaku_sender.config import (
    AtomicModel,
    GlobalConfig,
    MonitorConfig,
    SenderConfig,
    SendPolicy,
    Settings,
    ThemeConfig,
    ValidationConfig,
)
from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.utils.file_utils import atomic_write, read_json

logger = logging.getLogger(__name__)

CONFIG_PATH = AppInfo.Paths.CONFIG


class ConfigStorage:
    """配置存储：config.json 的加载与保存。"""

    def save(self, settings: Settings) -> None:
        """保存非敏感配置到 config.json。

        Args:
            settings: 待落盘的配置容器。
        """
        # 输出交给 json.dump，枚举须经 mode="json" 压成取值
        config_data = {
            "global": settings.global_config.model_dump(mode="json"),
            "sender": settings.sender_config.model_dump(mode="json"),
            "send_policy": settings.send_policy.model_dump(mode="json"),
            "monitor": settings.monitor_config.model_dump(mode="json"),
            "theme": settings.theme_config.model_dump(mode="json"),
            "validation": settings.validation_config.model_dump(mode="json")
        }

        try:
            with atomic_write(CONFIG_PATH) as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            logger.info(f"配置已保存: {CONFIG_PATH}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def load(self, settings: Settings) -> None:
        """从 config.json 加载配置到 settings。

        Args:
            settings: 就地更新的配置容器。
        """
        data = read_json(CONFIG_PATH)
        if not isinstance(data, dict):
            logger.info("未找到配置文件或格式异常，使用默认设置。")
            return

        def _apply_section[T: AtomicModel](key: str, model_class: type[T], target: T) -> None:
            """把 config.json 的段校验后原地灌进 target。

            必须原地更新、不得换实例。

            Args:
                key: config.json 中的段名。
                model_class: 该段对应的配置模型类。
                target: 就地更新的配置模型实例。
            """
            if key not in data:
                return
            # 试算输入取完整字段值再叠文件值：exclude=True 等不参与序列化的
            # 字段若参与跨字段校验，用默认值判断会得出错误结论。
            # 落账仍只写文件里出现过的字段，未出现的保持原状。
            probe = target.field_values()
            probe.update(data[key])
            try:
                fresh = model_class.model_validate(probe)
            except ValidationError as e:
                logger.warning(f"模块 [{key}] 配置存在非法值，已回退为安全默认值。详情:\n{e}")
                return
            target.commit(fresh, data[key])

        _apply_section("global", GlobalConfig, settings.global_config)
        _apply_section("sender", SenderConfig, settings.sender_config)
        _apply_section("send_policy", SendPolicy, settings.send_policy)
        _apply_section("monitor", MonitorConfig, settings.monitor_config)
        _apply_section("theme", ThemeConfig, settings.theme_config)
        _apply_section("validation", ValidationConfig, settings.validation_config)

        logger.info(f"配置文件加载与校验流程结束[{CONFIG_PATH}]。")
