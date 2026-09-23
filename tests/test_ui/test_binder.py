"""UIBinder 单向写绑定与 refresh 刷新"""
import os

import pytest
from pydantic import BaseModel, ConfigDict, Field
from PySide6.QtWidgets import QApplication, QCheckBox, QSpinBox, QWidget


@pytest.fixture(scope="module")
def qapp():
    # 无头 CI 没有显示服务器，必须在创建 QApplication 前切到离屏，否则 Qt 直接 abort
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


class _Cfg(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    enabled: bool = True
    count: int = Field(default=3, ge=1, le=10)


def test_bind_mounts_initial_value(qapp):
    from danmaku_sender.ui.framework.binder import UIBinder

    cfg = _Cfg(enabled=False, count=7)
    parent = QWidget()
    cb = QCheckBox(parent)
    spin = QSpinBox(parent)
    UIBinder.bind(cb, cfg, "enabled")
    UIBinder.bind(spin, cfg, "count")
    assert cb.isChecked() is False
    assert spin.value() == 7


def test_widget_write_updates_model_and_calls_on_wrote(qapp):
    from danmaku_sender.ui.framework.binder import UIBinder

    cfg = _Cfg()
    parent = QWidget()
    spin = QSpinBox(parent)
    wrote: list[tuple[str, object]] = []
    UIBinder.bind(spin, cfg, "count", on_wrote=lambda f, v: wrote.append((f, v)))
    spin.setValue(5)
    assert cfg.count == 5
    assert wrote == [("count", 5)]


def test_invalid_write_flags_widget_and_keeps_model(qapp):
    from danmaku_sender.ui.framework.binder import UIBinder

    cfg = _Cfg()
    parent = QWidget()
    spin = QSpinBox(parent)
    spin.setRange(0, 99)
    UIBinder.bind(spin, cfg, "count")
    spin.setValue(99)  # 超出 Field(le=10)
    assert cfg.count == 3
    assert spin.property("invalid") is True


def test_refresh_rereads_model_into_widget(qapp):
    from danmaku_sender.ui.framework.binder import UIBinder

    cfg = _Cfg()
    parent = QWidget()
    spin = QSpinBox(parent)
    UIBinder.bind(spin, cfg, "count")
    cfg.count = 8  # 外部改模型，控件不会自动跟（无隐式订阅）
    assert spin.value() == 3
    UIBinder.refresh(spin)
    assert spin.value() == 8


def test_refresh_all_covers_descendants(qapp):
    from danmaku_sender.ui.framework.binder import UIBinder

    cfg = _Cfg(enabled=True, count=2)
    parent = QWidget()
    inner = QWidget(parent)
    cb = QCheckBox(inner)
    UIBinder.bind(cb, cfg, "enabled")
    cfg.enabled = False
    UIBinder.refresh_all(parent)
    assert cb.isChecked() is False
