"""EditorSession 单元测试 — 编辑器核心会话层"""
import pytest
from danmaku_sender.core.models.danmaku import Danmaku
from danmaku_sender.core.models.editor_types import EditorField, InsertPosition
from danmaku_sender.core.state import ValidationConfig
from danmaku_sender.core.engines.editor_session import EditorSession
from tests.conftest import make_danmaku as _dm


@pytest.fixture
def session() -> EditorSession:
    return EditorSession()


@pytest.fixture
def loaded_session(session: EditorSession) -> EditorSession:
    session.load_data([
        _dm("第一条", 1000),
        _dm("第二条", 3000),
        _dm("第三条", 5000),
    ])
    return session


# ============================================================
# 基础状态
# ============================================================

class TestInitialState:
    def test_empty_session(self, session: EditorSession):
        assert session.has_active_session is False
        assert session.is_dirty is False
        assert session.can_undo is False
        assert session.active_error_count == 0

    def test_set_dirty(self, session: EditorSession):
        session.set_dirty(True)
        assert session.is_dirty is True
        session.set_dirty(False)
        assert session.is_dirty is False


# ============================================================
# load_data / get_committed_data
# ============================================================

class TestLoadData:
    def test_load_populates_items(self, loaded_session: EditorSession):
        assert loaded_session.has_active_session is True
        assert len(loaded_session.items) == 3

    def test_load_sorts_by_progress(self, loaded_session: EditorSession):
        progresses = [loaded_session.items[uid].working.progress for uid in loaded_session.item_order]
        assert progresses == sorted(progresses)

    def test_load_clears_previous(self, loaded_session: EditorSession):
        loaded_session.load_data([_dm("新弹幕", 2000)])
        assert len(loaded_session.items) == 1

    def test_load_resets_dirty(self, loaded_session: EditorSession):
        loaded_session.set_dirty(True)
        loaded_session.load_data([_dm("新", 0)])
        assert loaded_session.is_dirty is False

    def test_head_and_working_are_deep_copies(self, loaded_session: EditorSession):
        item = list(loaded_session.items.values())[0]
        item.working.msg = "修改"
        assert item.head.msg != "修改"


class TestGetCommittedData:
    def test_returns_all_when_no_deletions(self, loaded_session: EditorSession):
        result, fixed, removed = loaded_session.get_committed_data()
        assert len(result) == 3
        assert removed == 0

    def test_excludes_deleted(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].is_deleted = True
        result, _, removed = loaded_session.get_committed_data()
        assert len(result) == 2
        assert removed == 1

    def test_counts_fixed(self, loaded_session: EditorSession):
        item = list(loaded_session.items.values())[0]
        item.head_had_error = True
        item.error_msg = ""  # 修复了
        _, fixed, _ = loaded_session.get_committed_data()
        assert fixed == 1

    def test_not_fixed_if_still_has_error(self, loaded_session: EditorSession):
        item = list(loaded_session.items.values())[0]
        item.head_had_error = True
        item.error_msg = "仍有错误"
        _, fixed, _ = loaded_session.get_committed_data()
        assert fixed == 0

    def test_empty_session(self, session: EditorSession):
        result, fixed, removed = session.get_committed_data()
        assert result == []
        assert fixed == 0
        assert removed == 0

    def test_resets_dirty(self, loaded_session: EditorSession):
        loaded_session.set_dirty(True)
        loaded_session.get_committed_data()
        assert loaded_session.is_dirty is False


# ============================================================
# validate
# ============================================================

class TestValidate:
    def test_valid_danmakus(self, loaded_session: EditorSession):
        loaded_session.validate(10000, ValidationConfig())
        for item in loaded_session.items.values():
            assert item.error_msg == ""

    def test_long_danmaku_flagged(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].working.msg = "a" * 101
        loaded_session.validate(10000, ValidationConfig())
        assert loaded_session.items[uid].error_msg != ""

    def test_skips_deleted_items(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].is_deleted = True
        loaded_session.items[uid].working.msg = "a" * 101
        loaded_session.validate(10000, ValidationConfig())
        # 已删除的不应被校验，其他应正常
        assert loaded_session.items[uid].error_msg == ""

    def test_resets_errors_before_validate(self, loaded_session: EditorSession):
        # 先设置一个旧错误
        loaded_session.items[loaded_session.item_order[0]].error_msg = "旧错误"
        loaded_session.validate(10000, ValidationConfig())
        # 校验通过后旧错误应被清除
        assert loaded_session.items[loaded_session.item_order[0]].error_msg == ""


class TestMarkHeadErrors:
    def test_marks_current_errors(self, loaded_session: EditorSession):
        loaded_session.items[loaded_session.item_order[0]].error_msg = "有错"
        loaded_session.mark_head_errors()
        assert loaded_session.items[loaded_session.item_order[0]].head_had_error is True

    def test_clears_when_no_error(self, loaded_session: EditorSession):
        loaded_session.items[loaded_session.item_order[0]].head_had_error = True
        loaded_session.mark_head_errors()
        assert loaded_session.items[loaded_session.item_order[0]].head_had_error is False


# ============================================================
# generate_view_model
# ============================================================

class TestGenerateViewModel:
    def test_show_all_returns_all(self, loaded_session: EditorSession):
        view = loaded_session.generate_view_model(show_all=True)
        assert len(view) == 3

    def test_default_only_errors(self, loaded_session: EditorSession):
        view = loaded_session.generate_view_model(show_all=False)
        assert len(view) == 0  # 无错误

    def test_with_error_visible(self, loaded_session: EditorSession):
        loaded_session.items[loaded_session.item_order[0]].error_msg = "有问题"
        view = loaded_session.generate_view_model(show_all=False)
        assert len(view) == 1
        assert view[0]['error_msg'] == "有问题"
        assert view[0]['is_valid'] is False

    def test_deleted_items_hidden(self, loaded_session: EditorSession):
        loaded_session.items[loaded_session.item_order[0]].is_deleted = True
        view = loaded_session.generate_view_model(show_all=True)
        assert len(view) == 2

    def test_view_item_fields(self, loaded_session: EditorSession):
        view = loaded_session.generate_view_model(show_all=True)
        item = view[0]
        assert 'id' in item
        assert 'time_ms' in item
        assert 'content' in item
        assert 'error_msg' in item
        assert 'is_valid' in item

    def test_valid_items_show_normal(self, loaded_session: EditorSession):
        view = loaded_session.generate_view_model(show_all=True)
        assert all(v['error_msg'] == "正常" for v in view)
        assert all(v['is_valid'] is True for v in view)


# ============================================================
# undo
# ============================================================

class TestUndo:
    def test_undo_returns_false_when_empty(self, loaded_session: EditorSession):
        assert loaded_session.undo() is False

    def test_undo_reverts_property_change(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.update_item_properties(uid, {EditorField.MSG: "新内容"})
        assert loaded_session.items[uid].working.msg == "新内容"
        assert loaded_session.undo() is True
        assert loaded_session.items[uid].working.msg == "第一条"

    def test_undo_reverts_delete(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.delete_items([uid])
        assert loaded_session.items[uid].is_deleted is True
        loaded_session.undo()
        assert loaded_session.items[uid].is_deleted is False

    def test_undo_reverts_insert(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        new_uid = loaded_session.insert_item(uid, InsertPosition.BELOW)
        assert isinstance(new_uid, str)
        assert loaded_session.items[new_uid].is_deleted is False
        loaded_session.undo()
        assert loaded_session.items[new_uid].is_deleted is True

    def test_multiple_undos(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.update_item_properties(uid, {EditorField.MSG: "改1"})
        loaded_session.update_item_properties(uid, {EditorField.MSG: "改2"})
        assert loaded_session.items[uid].working.msg == "改2"
        loaded_session.undo()
        assert loaded_session.items[uid].working.msg == "改1"
        loaded_session.undo()
        assert loaded_session.items[uid].working.msg == "第一条"

    def test_undo_updates_dirty(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.update_item_properties(uid, {EditorField.MSG: "新"})
        assert loaded_session.is_dirty is True
        loaded_session.undo()
        # 撤销后如果栈空则 dirty=False
        assert loaded_session.is_dirty is False


# ============================================================
# insert_item
# ============================================================

class TestInsertItem:
    def test_insert_below(self, loaded_session: EditorSession):
        ref_uid = loaded_session.item_order[0]  # progress=1000
        new_uid = loaded_session.insert_item(ref_uid, InsertPosition.BELOW)
        assert isinstance(new_uid, str)
        assert loaded_session.items[new_uid].working.progress == 1500  # 1000+500

    def test_insert_above(self, loaded_session: EditorSession):
        ref_uid = loaded_session.item_order[0]  # progress=1000
        new_uid = loaded_session.insert_item(ref_uid, InsertPosition.ABOVE)
        assert isinstance(new_uid, str)
        assert loaded_session.items[new_uid].working.progress == 500  # max(0, 1000-500)

    def test_insert_above_at_zero_clamped(self, loaded_session: EditorSession):
        # 将第一条设为 progress=200
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].working.progress = 200
        new_uid = loaded_session.insert_item(uid, InsertPosition.ABOVE)
        assert isinstance(new_uid, str)
        assert loaded_session.items[new_uid].working.progress == 0  # max(0, 200-500)

    def test_insert_invalid_uid(self, loaded_session: EditorSession):
        assert loaded_session.insert_item("nonexistent") is None

    def test_insert_marks_dirty(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.insert_item(uid)
        assert loaded_session.is_dirty is True

    def test_insert_default_message(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        new_uid = loaded_session.insert_item(uid)
        assert isinstance(new_uid, str)
        assert loaded_session.items[new_uid].working.msg == "新建弹幕"


# ============================================================
# delete_items
# ============================================================

class TestDeleteItems:
    def test_delete_marks_deleted(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        assert loaded_session.delete_items([uid]) is True
        assert loaded_session.items[uid].is_deleted is True

    def test_delete_multiple(self, loaded_session: EditorSession):
        uids = loaded_session.item_order[:2]
        assert loaded_session.delete_items(uids) is True
        assert all(loaded_session.items[u].is_deleted for u in uids)

    def test_delete_empty_list(self, loaded_session: EditorSession):
        assert loaded_session.delete_items([]) is False

    def test_delete_nonexistent_uid(self, loaded_session: EditorSession):
        assert loaded_session.delete_items(["nonexistent"]) is False

    def test_delete_already_deleted(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].is_deleted = True
        assert loaded_session.delete_items([uid]) is False

    def test_delete_marks_dirty(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.delete_items([uid])
        assert loaded_session.is_dirty is True


# ============================================================
# update_item_properties
# ============================================================

class TestUpdateItemProperties:
    def test_update_single_field(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        result = loaded_session.update_item_properties(uid, {EditorField.MSG: "修改后"})
        assert result is True
        assert loaded_session.items[uid].working.msg == "修改后"

    def test_update_multiple_fields(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        result = loaded_session.update_item_properties(uid, {
            EditorField.MSG: "新内容",
            EditorField.COLOR: 255,
            EditorField.FONT_SIZE: 36
        })
        assert result is True
        item = loaded_session.items[uid]
        assert item.working.msg == "新内容"
        assert item.working.color == 255
        assert item.working.fontsize == 36

    def test_update_no_change(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        original_msg = loaded_session.items[uid].working.msg
        result = loaded_session.update_item_properties(uid, {EditorField.MSG: original_msg})
        assert result is False

    def test_update_nonexistent(self, loaded_session: EditorSession):
        result = loaded_session.update_item_properties("nonexistent", {EditorField.MSG: "x"})
        assert result is False


# ============================================================
# batch_remove_newlines
# ============================================================

class TestBatchRemoveNewlines:
    def test_removes_literal_newline(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].working.msg = "hello\nworld"
        mod, del_ = loaded_session.batch_remove_newlines()
        assert loaded_session.items[uid].working.msg == "helloworld"
        assert mod == 1

    def test_removes_escaped_newline(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].working.msg = "hello\\nworld"
        loaded_session.batch_remove_newlines()
        assert loaded_session.items[uid].working.msg == "helloworld"

    def test_removes_slash_n(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].working.msg = "hello/nworld"
        loaded_session.batch_remove_newlines()
        assert loaded_session.items[uid].working.msg == "helloworld"

    def test_empty_after_removal_marks_deleted(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].working.msg = "\n"
        mod, del_ = loaded_session.batch_remove_newlines()
        assert loaded_session.items[uid].is_deleted is True
        assert del_ == 1

    def test_no_change_no_count(self, loaded_session: EditorSession):
        mod, del_ = loaded_session.batch_remove_newlines()
        assert mod == 0
        assert del_ == 0

    def test_skips_deleted(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].is_deleted = True
        loaded_session.items[uid].working.msg = "hello\nworld"
        mod, _ = loaded_session.batch_remove_newlines()
        assert mod == 0


# ============================================================
# batch_truncate_length
# ============================================================

class TestBatchTruncateLength:
    def test_truncates_long_content(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].working.msg = "a" * 150
        count = loaded_session.batch_truncate_length(100)
        assert loaded_session.items[uid].working.msg == "a" * 100
        assert count == 1

    def test_short_content_unchanged(self, loaded_session: EditorSession):
        count = loaded_session.batch_truncate_length(100)
        assert count == 0

    def test_custom_limit(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].working.msg = "abcde"
        count = loaded_session.batch_truncate_length(3)
        assert loaded_session.items[uid].working.msg == "abc"
        assert count == 1


# ============================================================
# shift_time_axis
# ============================================================

class TestShiftTimeAxis:
    def test_positive_shift(self, loaded_session: EditorSession):
        count = loaded_session.shift_time_axis(2000)
        assert count == 3
        for uid in loaded_session.item_order:
            # 原始值 +2000
            pass  # 下面直接检查
        assert loaded_session.items[loaded_session.item_order[0]].working.progress == 3000  # 1000+2000
        assert loaded_session.items[loaded_session.item_order[1]].working.progress == 5000

    def test_negative_shift(self, loaded_session: EditorSession):
        count = loaded_session.shift_time_axis(-500)
        assert count == 3
        assert loaded_session.items[loaded_session.item_order[0]].working.progress == 500  # 1000-500

    def test_negative_shift_clamped_to_zero(self, loaded_session: EditorSession):
        loaded_session.shift_time_axis(-99999)
        for uid in loaded_session.item_order:
            assert loaded_session.items[uid].working.progress >= 0

    def test_zero_offset_no_change(self, loaded_session: EditorSession):
        count = loaded_session.shift_time_axis(0)
        assert count == 0

    def test_target_uids(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        count = loaded_session.shift_time_axis(1000, target_uids=[uid])
        assert count == 1
        assert loaded_session.items[uid].working.progress == 2000
        # 其他不变
        assert loaded_session.items[loaded_session.item_order[1]].working.progress == 3000

    def test_empty_target_uids(self, loaded_session: EditorSession):
        count = loaded_session.shift_time_axis(1000, target_uids=[])
        assert count == 0

    def test_skips_deleted(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].is_deleted = True
        count = loaded_session.shift_time_axis(1000)
        assert count == 2


# ============================================================
# generate_danmaku_array
# ============================================================

class TestGenerateDanmakuArray:
    def test_classic_strategy(self, loaded_session: EditorSession):
        ref_uid = loaded_session.item_order[0]
        uids = loaded_session.generate_danmaku_array(ref_uid, "阵列弹幕", Danmaku.Mode.SCROLL, 3, "classic")
        assert len(uids) == 3
        for uid in uids:
            item = loaded_session.items[uid]
            assert item.working.msg == "阵列弹幕"
            assert item.working.progress == 1000  # same as ref

    def test_rainbow_strategy(self, loaded_session: EditorSession):
        ref_uid = loaded_session.item_order[0]
        uids = loaded_session.generate_danmaku_array(ref_uid, "彩虹", Danmaku.Mode.SCROLL, 5, "rainbow")
        assert len(uids) == 5
        colors = [loaded_session.items[u].working.color for u in uids]
        assert len(set(colors)) == 5  # all different

    def test_invalid_ref_uid(self, loaded_session: EditorSession):
        uids = loaded_session.generate_danmaku_array("nonexistent", "x", Danmaku.Mode.SCROLL, 3, "classic")
        assert uids == []

    def test_marks_dirty(self, loaded_session: EditorSession):
        ref_uid = loaded_session.item_order[0]
        loaded_session.generate_danmaku_array(ref_uid, "test", Danmaku.Mode.SCROLL, 2, "classic")
        assert loaded_session.is_dirty is True

    def test_can_undo_array(self, loaded_session: EditorSession):
        ref_uid = loaded_session.item_order[0]
        uids = loaded_session.generate_danmaku_array(ref_uid, "test", Danmaku.Mode.SCROLL, 2, "classic")
        original_count = len(loaded_session.items)
        loaded_session.undo()
        # 撤销后新增的条目应被标记删除
        for uid in uids:
            assert loaded_session.items[uid].is_deleted is True


# ============================================================
# active_error_count
# ============================================================

class TestActiveErrorCount:
    def test_no_errors(self, loaded_session: EditorSession):
        assert loaded_session.active_error_count == 0

    def test_counts_errors(self, loaded_session: EditorSession):
        loaded_session.items[loaded_session.item_order[0]].error_msg = "有问题"
        assert loaded_session.active_error_count == 1

    def test_excludes_deleted(self, loaded_session: EditorSession):
        uid = loaded_session.item_order[0]
        loaded_session.items[uid].error_msg = "有问题"
        loaded_session.items[uid].is_deleted = True
        assert loaded_session.active_error_count == 0
