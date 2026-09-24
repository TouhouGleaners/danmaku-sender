"""LiveFormBinder / DraftFormBinder 的行为测试。

覆盖两类表单的关键约定：
- 实时修改（LiveFormBinder）：控件变更写回模型；fill 刷新控件且不写回；
- 草稿修改（DraftFormBinder）：map 不碰模型；collect 校验并保留未展示字段。
另外覆盖 fill 不阻断用户信号槽（控件联动）、转换函数、重复绑定替换。
"""
import gc
import os
import weakref
from collections.abc import Callable

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from danmaku_sender.config import SenderConfig
from danmaku_sender.ui.framework.form_binder import (
    DraftFormBinder,
    LiveFormBinder,
    clear_invalid,
    mark_invalid,
)
from danmaku_sender.utils.string_utils import join_keywords, parse_keywords


@pytest.fixture(scope="module")
def qapp():
    """创建 QApplication。无头 CI 没有显示服务器，必须先切到 offscreen。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


class _Cfg(BaseModel):
    """测试用配置模型。

    字段故意覆盖多种形态：带约束的 int、带 default_factory 的 list、
    界面上不展示的 hidden（用于验证 collect 保留基准值）。
    """

    model_config = ConfigDict(validate_assignment=True)

    enabled: bool = True
    count: int = Field(default=3, ge=1, le=10)
    tags: list[str] = Field(default_factory=list)
    hidden: str = "keep-me"


# ── LiveFormBinder：实时修改 ──────────────────────────────


def test_bind_mounts_initial_value(qapp):
    """bind 时应把控件初始化为模型当前值。"""
    cfg = _Cfg(enabled=False, count=7)
    parent = QWidget()
    cb = QCheckBox(parent)
    spin = QSpinBox(parent)
    LiveFormBinder.bind(cb, cfg, "enabled")
    LiveFormBinder.bind(spin, cfg, "count")
    assert cb.isChecked() is False
    assert spin.value() == 7


def test_widget_write_updates_model_and_calls_after_write(qapp):
    """控件变更应写回模型，并触发 after_write 回调。"""
    cfg = _Cfg()
    parent = QWidget()
    spin = QSpinBox(parent)
    wrote: list[tuple[str, object]] = []
    LiveFormBinder.bind(spin, cfg, "count", after_write=lambda f, v: wrote.append((f, v)))
    spin.setValue(5)
    assert cfg.count == 5
    assert wrote == [("count", 5)]


def test_invalid_write_flags_widget_and_keeps_model(qapp):
    """违反字段约束的写入应标红控件，且不改变模型。"""
    cfg = _Cfg()
    parent = QWidget()
    spin = QSpinBox(parent)
    spin.setRange(0, 99)  # 控件允许 99，但 Field(le=10) 不允许
    LiveFormBinder.bind(spin, cfg, "count")
    spin.setValue(99)
    assert cfg.count == 3
    assert spin.property("invalid") is True


def test_fill_rereads_model_into_widget(qapp):
    """外部修改模型后，fill 应把新值刷进控件。"""
    cfg = _Cfg()
    parent = QWidget()
    spin = QSpinBox(parent)
    LiveFormBinder.bind(spin, cfg, "count")
    cfg.count = 8  # 程序侧改模型，控件不会自动跟（无隐式订阅）
    assert spin.value() == 3
    LiveFormBinder.fill(parent)
    assert spin.value() == 8


def test_fill_keeps_user_linkage_alive(qapp):
    """fill 不得屏蔽控件信号，否则勾选框联动会失效、需要调用方手动重算。"""
    cfg = _Cfg()
    parent = QWidget()
    cb = QCheckBox(parent)
    linked: list[bool] = []
    # 典型联动：勾选框控制另一组控件的可用性
    cb.toggled.connect(lambda on: linked.append(on))
    LiveFormBinder.bind(cb, cfg, "enabled")

    cfg.enabled = False
    linked.clear()
    LiveFormBinder.fill(parent)

    assert linked == [False], "fill 后 toggled 必须照常触发用户联动"


def test_fill_triggers_linkage_even_when_value_unchanged(qapp):
    """值未变化时 Qt 不发信号，fill 必须补发，否则初始联动（如禁用子控件）不会跑。"""
    cfg = _Cfg(enabled=False)  # 与勾选框默认状态相同
    parent = QWidget()
    cb = QCheckBox(parent)  # 默认未勾选
    linked: list[bool] = []
    cb.toggled.connect(lambda on: linked.append(on))
    LiveFormBinder.bind(cb, cfg, "enabled")

    linked.clear()
    LiveFormBinder.fill(parent)
    assert linked == [False], "值未变化的 fill 也必须触发联动槽"


def test_fill_unchanged_checkbox_preserves_qt_check_state(qapp):
    """补发 stateChanged 时参数必须是 Qt.CheckState（0/2），不是 bool 的 0/1。"""
    from PySide6.QtCore import Qt

    parent = QWidget()
    cb = QCheckBox(parent)
    cb.setChecked(True)

    states: list[int] = []
    cb.stateChanged.connect(states.append)

    LiveFormBinder.bind(cb, _Cfg(enabled=True), "enabled")
    states.clear()
    LiveFormBinder.fill(parent)

    assert states == [Qt.CheckState.Checked.value], "checked 时应发 2，不是 1"


def test_fill_does_not_suppress_unrelated_bound_widget(qapp):
    """fill 表单 A 时，联动改动的表单 B 控件必须照常写回，不能被 A 的填充状态误伤。"""
    cfg_a = _Cfg(count=1)
    cfg_b = _Cfg(count=2)

    parent_a = QWidget()
    parent_b = QWidget()

    source = QCheckBox(parent_a)
    target = QSpinBox(parent_b)

    LiveFormBinder.bind(source, cfg_a, "enabled")
    LiveFormBinder.bind(target, cfg_b, "count")

    # 跨表单联动：A 的勾选框改动 B 的数值
    source.toggled.connect(lambda _: target.setValue(5))

    LiveFormBinder.fill(parent_a)

    assert target.value() == 5
    assert cfg_b.count == 5, "B 的写回不得被 A 的 fill 抑制"


def test_fill_line_edit_emits_text_changed_not_editing_finished(qapp):
    """QLineEdit 补发的是值变化信号 textChanged，不伪造用户交互信号 editingFinished。"""
    parent = QWidget()
    edit = QLineEdit(parent)
    edit.setText("same")

    changed: list[str] = []
    finished: list[None] = []
    edit.textChanged.connect(changed.append)
    edit.editingFinished.connect(lambda: finished.append(None))

    LiveFormBinder.bind(edit, _Cfg(tags=["same"]), "tags",
                        realtime=True, to_model=parse_keywords, to_widget=join_keywords)
    changed.clear()
    finished.clear()
    LiveFormBinder.fill(parent)

    assert changed == ["same"], "应补发 textChanged"
    assert finished == [], "不得伪造 editingFinished（那是用户交互语义）"


def test_clear_invalid_preserves_permanent_tooltip(qapp):
    """标红时存下常驻提示，清除无效态后还原；从未标红时不得碰 tooltip。"""
    parent = QWidget()
    cb = QCheckBox(parent)
    cb.setToolTip("这是永久帮助文本")

    clear_invalid(cb)  # 首次调用，控件从未标记过 invalid
    assert cb.toolTip() == "这是永久帮助文本", "从未标红就 clear，不许碰 tooltip"

    mark_invalid(cb, "坏了")
    assert "坏了" in cb.toolTip()
    mark_invalid(cb, "又坏了")  # 重复标红不得覆盖掉已存的常驻提示
    assert "又坏了" in cb.toolTip()

    clear_invalid(cb)
    assert cb.toolTip() == "这是永久帮助文本", "清除后应还原常驻提示"

    mark_invalid(cb, "再一次")
    clear_invalid(cb)
    assert cb.toolTip() == "这是永久帮助文本", "第二轮标红/清除后仍应还原"


def test_fill_does_not_write_back_or_call_after_write(qapp):
    """fill 只读模型，不得写回，也不得触发 after_write。"""
    cfg = _Cfg(count=4)
    parent = QWidget()
    spin = QSpinBox(parent)
    spin.setValue(9)  # 控件上的脏值，fill 后应被模型值覆盖
    wrote: list[tuple[str, object]] = []
    LiveFormBinder.bind(spin, cfg, "count", after_write=lambda f, v: wrote.append((f, v)))
    wrote.clear()
    LiveFormBinder.fill(parent)
    assert cfg.count == 4
    assert wrote == []


def test_converters_translate_widget_and_model(qapp):
    """to_model / to_widget 应支持非同构类型（list[str] ↔ str）。"""
    cfg = _Cfg(tags=["a", "b"])
    parent = QWidget()
    edit = QLineEdit(parent)
    LiveFormBinder.bind(
        edit, cfg, "tags", realtime=True, to_model=parse_keywords, to_widget=join_keywords
    )
    assert edit.text() == "a, b"

    edit.setText("x, y")
    assert cfg.tags == ["x", "y"]

    cfg.tags = ["p"]
    LiveFormBinder.fill(parent)
    assert edit.text() == "p"


def test_rebind_same_widget_replaces_old_connection(qapp):
    """同一控件重复 bind 应替换旧连接，避免幽灵写回。"""
    cfg_a = _Cfg(count=1)
    cfg_b = _Cfg(count=2)
    parent = QWidget()
    spin = QSpinBox(parent)
    LiveFormBinder.bind(spin, cfg_a, "count")
    LiveFormBinder.bind(spin, cfg_b, "count")

    spin.setValue(6)
    assert cfg_a.count == 1, "旧连接必须已断开"
    assert cfg_b.count == 6


def test_rebind_disconnects_old_after_write(qapp):
    """重绑后旧 after_write 不得被调用，旧写回闭包应随 disconnect 释放。"""
    parent = QWidget()
    spin = QSpinBox(parent)
    old_cfg = _Cfg(count=1)
    new_cfg = _Cfg(count=2)
    old_calls: list[object] = []
    new_calls: list[object] = []

    LiveFormBinder.bind(spin, old_cfg, "count",
                        after_write=lambda f, v: old_calls.append(v))
    old_slot_ref = LiveFormBinder._bindings[spin].slot_ref
    assert old_slot_ref() is not None, "bind 后旧 slot 应存活（由 Qt 连接持有）"

    LiveFormBinder.bind(spin, new_cfg, "count",
                        after_write=lambda f, v: new_calls.append(v))

    spin.setValue(6)
    assert old_calls == [], "旧 after_write 不得触发"
    assert new_calls == [6], "新 after_write 应正常触发"

    gc.collect()
    assert old_slot_ref() is None, "旧写回闭包应随 disconnect 被释放"


def test_rebind_during_initial_fill_does_not_leave_old_slot(qapp):
    """初始化灌值触发的联动里重绑同一控件，旧闭包不得被重新 connect 回去。"""
    parent = QWidget()
    spin = QSpinBox(parent)
    cfg_a = _Cfg(count=1)
    cfg_b = _Cfg(count=2)
    old_calls: list[object] = []
    new_calls: list[object] = []
    captured: list[weakref.ReferenceType[Callable[..., None]]] = []
    rebound = False

    def rebind_on_change(_v: int) -> None:
        nonlocal rebound
        if rebound:
            return
        rebound = True
        # 在 A 的初始灌值期间重绑到 B，并记下 A 的 slot 弱引用
        meta = LiveFormBinder._bindings.get(spin)
        if meta is not None:
            captured.append(meta.slot_ref)
        LiveFormBinder.bind(spin, cfg_b, "count",
                            after_write=lambda f, v: new_calls.append(v))

    spin.valueChanged.connect(rebind_on_change)
    LiveFormBinder.bind(spin, cfg_a, "count",
                        after_write=lambda f, v: old_calls.append(v))

    spin.setValue(7)
    assert old_calls == [], "旧 after_write 不得触发"
    assert new_calls == [7], "新 after_write 应正常触发"
    assert cfg_a.count == 1, "旧模型不得被写入"
    assert cfg_b.count == 7

    # 关键断言：A 的闭包若被重新 connect 回去，会继续被 Qt 强引用、无法回收
    gc.collect()
    assert captured and captured[0]() is None, "旧闭包应已随 disconnect 释放"


def test_bind_failure_leaves_no_orphan_metadata(qapp):
    """初始灌值失败不得留下「有元数据、无连接」的伪绑定。"""

    def _bad_to_widget(v: object) -> str:
        raise RuntimeError("转换炸了")

    parent = QWidget()
    spin = QSpinBox(parent)
    before = len(LiveFormBinder._bindings)

    with pytest.raises(RuntimeError):
        LiveFormBinder.bind(spin, _Cfg(count=3), "count", to_widget=_bad_to_widget)

    assert spin not in LiveFormBinder._bindings, "失败的 bind 不得留下元数据"
    assert len(LiveFormBinder._bindings) == before


def test_bindings_released_when_widget_destroyed(qapp):
    """控件销毁后注册表条目必须可回收（value 不得强引用 key）。"""
    cfg = _Cfg()
    parent = QWidget()
    spin = QSpinBox(parent)
    LiveFormBinder.bind(spin, cfg, "count")
    ref = weakref.ref(spin)

    # 只删父控件：Qt 销毁子控件，Python 侧不应再有强引用残留
    del spin
    del parent
    gc.collect()

    assert ref() is None, "控件应被回收"
    assert len(LiveFormBinder._bindings) == 0


def test_registry_value_does_not_reference_key(qapp):
    """注册表 value 不得强引用 key 或其父窗口。

    回归：早期实现把写回闭包存进类级注册表，而 after_write 常写成
    ``lambda: self.xxx`` 捕获窗口，形成「注册表 → 闭包 → 窗口 → 控件」
    的强引用链。WeakKeyDictionary 的 value 一旦能到达 key，条目就永生。

    这里直接断言不变量，不依赖 Qt 对象的具体回收时机。
    """
    cfg = _Cfg()
    parent = QWidget()
    spin = QSpinBox(parent)

    def _after(_f: str, _v: object) -> None:
        parent.setToolTip("x")  # 故意捕获父窗口

    LiveFormBinder.bind(spin, cfg, "count", after_write=_after)
    value = LiveFormBinder._bindings.get(spin)
    assert value is not None

    for item in value:
        assert item is not spin, "value 不得持有控件本身"
        assert item is not parent, "value 不得持有控件的父窗口"
        assert item is not _after, "value 不得持有 after_write 回调"


def test_collect_converts_to_model_error_to_validation_error(qapp):
    """to_model 抛出的异常应转为 ValidationError，调用方不必分叉捕获。"""
    def _bad_parse(text: str) -> list[str]:
        raise RuntimeError("解析失败")

    parent = QWidget()
    edit = QLineEdit(parent)
    edit.setText("x")
    DraftFormBinder.map(edit, "tags", to_model=_bad_parse)

    with pytest.raises(ValidationError) as exc:
        DraftFormBinder.collect(parent, _Cfg)
    assert "解析失败" in str(exc.value)
    assert edit.property("invalid") is True


# ── DraftFormBinder：草稿修改 ─────────────────────────────


def test_map_does_not_touch_model(qapp):
    """map 只登记对应关系，控件变更不得写入模型。"""
    cfg = _Cfg(count=3)
    parent = QWidget()
    spin = QSpinBox(parent)
    DraftFormBinder.map(spin, "count")
    spin.setValue(8)
    assert cfg.count == 3


def test_fill_then_collect_roundtrip(qapp):
    """fill 填充初始值，修改控件后 collect 得到新值；未展示字段按基准保留。"""
    cfg = _Cfg(count=7, hidden="keep-me", tags=["t1"])
    parent = QWidget()
    spin = QSpinBox(parent)
    edit = QLineEdit(parent)
    DraftFormBinder.map(spin, "count")
    DraftFormBinder.map(edit, "tags", to_model=parse_keywords, to_widget=join_keywords)

    DraftFormBinder.fill(parent, cfg)
    assert spin.value() == 7
    assert edit.text() == "t1"

    spin.setValue(9)
    edit.setText("t2, t3")
    collected = DraftFormBinder.collect(parent, _Cfg)
    assert collected.count == 9
    assert collected.tags == ["t2", "t3"]
    assert collected.hidden == "keep-me", "对话框未展示的字段应保持基准值"


def test_collect_validation_error_marks_widget(qapp):
    """字段级校验失败应抛 ValidationError，并由 show_errors 标红对应控件。"""
    parent = QWidget()
    spin = QSpinBox(parent)
    spin.setRange(0, 99)  # 控件允许 50，但 Field(le=10) 不允许
    DraftFormBinder.map(spin, "count")
    DraftFormBinder.fill(parent, _Cfg(count=3))
    spin.setValue(50)

    with pytest.raises(ValidationError) as exc:
        DraftFormBinder.collect(parent, _Cfg)
    rest = DraftFormBinder.show_errors(parent, exc.value)
    assert spin.property("invalid") is True
    assert rest == [], "字段级错误应能定位到控件"


def test_collect_field_constraint_error_marks_widget(qapp):
    """loc 含字段名的约束错误应标红对应控件，不产生未映射消息。"""

    class _Lo(BaseModel):
        lo: int = Field(ge=5)

    parent = QWidget()
    spin = QSpinBox(parent)
    spin.setRange(0, 99)
    DraftFormBinder.map(spin, "lo")
    spin.setValue(1)

    with pytest.raises(ValidationError) as exc:
        DraftFormBinder.collect(parent, _Lo)
    rest = DraftFormBinder.show_errors(parent, exc.value)
    assert spin.property("invalid") is True
    assert rest == []


def test_show_errors_returns_unmapped_messages(qapp):
    """跨字段校验无法定位到单个控件，消息应返回给调用方处理。"""
    parent = QWidget()
    lo = QSpinBox(parent)
    hi = QSpinBox(parent)
    lo.setRange(0, 99)
    hi.setRange(0, 99)
    DraftFormBinder.map(lo, "min_delay")
    DraftFormBinder.map(hi, "max_delay")
    DraftFormBinder.fill(parent, SenderConfig())
    # min_delay > max_delay 触发 SenderConfig.check_logic（模型级校验）
    lo.setValue(20)
    hi.setValue(5)

    with pytest.raises(ValidationError) as exc:
        DraftFormBinder.collect(parent, SenderConfig)
    rest = DraftFormBinder.show_errors(parent, exc.value)
    assert rest, "模型级错误应作为未映射消息返回"
    assert any("延迟" in msg for msg in rest)


def test_fill_clears_invalid_marks(qapp):
    """fill 应清除此前的无效标记，避免残留上一次的错误状态。"""
    parent = QWidget()
    spin = QSpinBox(parent)
    DraftFormBinder.map(spin, "count")
    mark_invalid(spin, "bad")
    assert spin.property("invalid") is True
    DraftFormBinder.fill(parent, _Cfg(count=3))
    assert spin.property("invalid") is False


def test_cross_field_assignment_keeps_model_clean(qapp):
    """跨字段校验失败时模型不得被写脏。

    回归：validate_assignment 的赋值不原子——字段级校验失败会拒绝写入，
    但 model_validator(mode='after') 在赋值后运行、失败不回滚。
    SenderConfig.__setattr__ 先整模型试算来堵住这个洞。
    """
    cfg = SenderConfig()  # min=8.0, max=8.5
    with pytest.raises(ValidationError):
        cfg.min_delay = 10.0
    assert cfg.min_delay == 8.0, "校验失败不得留下脏值"
    assert cfg.max_delay == 8.5
    # 写脏后落盘会让下次启动整段校验失败、回退默认值
    assert SenderConfig.model_validate(cfg.model_dump()) is not None


def test_cross_field_assignment_via_binder_keeps_model_clean(qapp):
    """经 LiveFormBinder 写回同样不得写脏模型。"""
    cfg = SenderConfig()
    parent = QWidget()
    lo = QDoubleSpinBox(parent)
    lo.setRange(0.1, 60.0)
    LiveFormBinder.bind(lo, cfg, "min_delay")

    lo.setValue(10.0)  # > max_delay=8.5
    assert lo.property("invalid") is True
    assert cfg.min_delay == 8.0
    assert cfg.max_delay == 8.5


def test_fill_rounding_to_same_value_still_emits_linkage(qapp):
    """Qt setter 按精度舍入后实际值未变时，fill 仍须补发值变化信号。

    回归：_apply_val 曾拿「期望值」判断是否变化，舍入/截断成相同值时会漏发，
    依赖该控件的联动槽不执行。
    """

    class _R(BaseModel):
        model_config = ConfigDict(validate_assignment=True)

        v: float = 1.23

    parent = QWidget()
    spin = QDoubleSpinBox(parent)
    spin.setDecimals(2)
    spin.setValue(1.23)

    fired: list[float] = []
    spin.valueChanged.connect(fired.append)

    cfg = _R(v=1.23)
    LiveFormBinder.bind(spin, cfg, "v")
    fired.clear()

    cfg.v = 1.234  # 舍入后仍为 1.23，实际值没变
    LiveFormBinder.fill(parent)
    assert fired == [1.23], "实际值未变时仍须补发值变化信号，联动槽才跑得到"
