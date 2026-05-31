"""共享测试夹具"""
import pytest
from danmaku_sender.core.models.danmaku import Danmaku
from danmaku_sender.core.state import SenderConfig, ValidationConfig


@pytest.fixture
def sample_danmaku() -> Danmaku:
    """一条标准的滚动弹幕"""
    return Danmaku(
        msg="测试弹幕",
        progress=5000,
        mode=Danmaku.Mode.SCROLL,
        fontsize=25,
        color=16777215
    )


@pytest.fixture
def sample_danmaku_list() -> list[Danmaku]:
    """一组按时间排序的弹幕"""
    return [
        Danmaku(msg="第一条", progress=1000),
        Danmaku(msg="第二条", progress=3000),
        Danmaku(msg="第三条", progress=5000),
    ]


@pytest.fixture
def sender_config() -> SenderConfig:
    """默认发送配置"""
    return SenderConfig()


@pytest.fixture
def validation_config() -> ValidationConfig:
    """默认校验配置"""
    return ValidationConfig()
