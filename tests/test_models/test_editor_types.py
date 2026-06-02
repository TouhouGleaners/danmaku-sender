"""editor_types 模型单元测试 — EditorField, EditorItem"""
import pytest
from danmaku_sender.core.models.danmaku import Danmaku
from danmaku_sender.core.models.editor_types import EditorItem, EditorField


@pytest.fixture
def editor_item() -> EditorItem:
    dm = Danmaku(msg="测试弹幕", progress=5000, color=255, fontsize=36, mode=Danmaku.Mode.BOTTOM)
    return EditorItem(head=dm.clone(), working=dm.clone())


class TestEditorFieldGetValue:
    """EditorField.get_value 映射"""

    def test_get_msg(self, editor_item: EditorItem):
        assert EditorField.MSG.get_value(editor_item) == "测试弹幕"

    def test_get_color(self, editor_item: EditorItem):
        assert EditorField.COLOR.get_value(editor_item) == 255

    def test_get_fontsize(self, editor_item: EditorItem):
        assert EditorField.FONT_SIZE.get_value(editor_item) == 36

    def test_get_mode(self, editor_item: EditorItem):
        assert EditorField.MODE.get_value(editor_item) == Danmaku.Mode.BOTTOM

    def test_get_progress(self, editor_item: EditorItem):
        assert EditorField.PROGRESS.get_value(editor_item) == 5000

    def test_get_is_deleted(self, editor_item: EditorItem):
        assert EditorField.IS_DELETED.get_value(editor_item) is False


class TestEditorFieldSetValue:
    """EditorField.set_value 映射"""

    def test_set_msg(self, editor_item: EditorItem):
        EditorField.MSG.set_value(editor_item, "新内容")
        assert editor_item.working.msg == "新内容"

    def test_set_color(self, editor_item: EditorItem):
        EditorField.COLOR.set_value(editor_item, 16777215)
        assert editor_item.working.color == 16777215

    def test_set_is_deleted(self, editor_item: EditorItem):
        EditorField.IS_DELETED.set_value(editor_item, True)
        assert editor_item.is_deleted is True

    def test_set_progress(self, editor_item: EditorItem):
        EditorField.PROGRESS.set_value(editor_item, 8000)
        assert editor_item.working.progress == 8000


class TestEditorItem:
    def test_initial_state(self, editor_item: EditorItem):
        assert editor_item.is_deleted is False
        assert editor_item.error_msg == ""
        assert editor_item.head_had_error is False
        assert editor_item.id  # UUID 非空

    def test_head_and_working_are_independent(self, editor_item: EditorItem):
        editor_item.working.msg = "修改后"
        assert editor_item.head.msg == "测试弹幕"

    def test_unique_ids(self):
        dm = Danmaku(msg="t", progress=0)
        item1 = EditorItem(head=dm.clone(), working=dm.clone())
        item2 = EditorItem(head=dm.clone(), working=dm.clone())
        assert item1.id != item2.id
