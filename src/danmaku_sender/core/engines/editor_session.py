import copy
import uuid
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Callable, TypedDict

from ..state import AppState
from ..models.danmaku import Danmaku
from ..services.danmaku_validator import validate_danmaku_list


@dataclass
class EditorItem:
    """
    弹幕节点容器

    内聚了单条弹幕在编辑周期内的所有状态
    """
    head: Danmaku        # HEAD 快照：检出时的不可变状态
    working: Danmaku     # 工作区：当前正在编辑的状态
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    is_deleted: bool = False      # 逻辑删除标记
    error_msg: str = ""           # 校验错误信息
    head_had_error: bool = False  # 检出时是否携带有错误 (用于计算修复量)


class EditorField(Enum):
    """编辑器可改动的字段枚举"""
    MSG = "msg"
    COLOR = "color"
    FONT_SIZE = "fontsize"
    MODE = "mode"
    PROGRESS = "progress"
    IS_DELETED = "is_deleted"  # 逻辑删除标记

    def get_value(self, item: EditorItem) -> Any:
        """获取 Danmaku 实例中对应的属性值，集中管理映射关系"""
        if self == EditorField.IS_DELETED:
            return item.is_deleted
        return getattr(item.working, self.value)

    def set_value(self, item: EditorItem, val: Any) -> None:
        """设置 Danmaku 实例中对应的属性值"""
        if self == EditorField.IS_DELETED:
            item.is_deleted = val
        else:
            setattr(item.working, self.value, val)


@dataclass(frozen=True)
class AtomicChange:
    """原子变更记录：描述单条弹幕单次属性的变化"""
    item_id: str          # 暂存区索引
    field: EditorField    # 修改字段
    previous_value: Any   # 该变化发生前的原始值


class ViewItem(TypedDict):
    """传递给 UI 表格的视图数据字典"""
    id: str
    time_ms: int
    content: str
    error_msg: str
    is_valid: bool


class EditorSession:
    """
    弹幕编辑器逻辑会话层。
    管理暂存区的数据检出、编辑、校验与提交。
    """
    def __init__(self, state: AppState):
        self.state = state
        self.logger = logging.getLogger("App.System.Editor")


        self.items: dict[str, EditorItem] = {}          # 核心存储：UUID 映射表
        self.item_order: list[str] = []                 # 顺序表：维护弹幕在视频中的物理播放顺序
        self.undo_stack: list[list[AtomicChange]] = []  # 操作栈：撤销功能

    @property
    def is_dirty(self) -> bool:
        return self.state.editor_is_dirty

    @property
    def has_active_session(self) -> bool:
        """工作区是否有数据"""
        return bool(self.items)

    @property
    def active_error_count(self) -> int:
        """当前可见（未标记删除）的错误总数"""
        return sum(1 for item in self.items.values() if not item.is_deleted and item.error_msg)

    @property
    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def set_dirty(self, dirty: bool):
        self.state.editor_is_dirty = dirty

    def checkout_from_state(self) -> bool:
        """从全局状态检出数据到暂存区，并记录 HEAD 错误快照。"""
        source = self.state.video_state.loaded_danmakus
        if not source:
            return False

        self._reset_session()

        # 排序并包装入容器
        sorted_source = sorted(source, key=lambda x: x.progress)
        for dm in sorted_source:
            item = EditorItem(
                head=copy.deepcopy(dm),
                working=copy.deepcopy(dm)
            )
            self.items[item.id] = item
            self.item_order.append(item.id)

        # 执行初始校验，并记录 HEAD 错误快照
        self.refresh_validation()
        for item in self.items.values():
            item.head_had_error = bool(item.error_msg)

        self.set_dirty(False)
        return self.active_error_count > 0

    def commit_to_state(self) -> tuple[int, int, int]:
        """将暂存区的改动正式提交到全局状态，并计算。

        Returns:
            tuple[int, int, int]: (总数, 修复数, 删除数)
        """
        if not self.items:
            return 0, 0, 0

        final_list = []
        fixed_count = 0
        removed_count = 0

        for uid in self.item_order:
            item = self.items[uid]
            if item.is_deleted:
                removed_count += 1
            else:
                final_list.append(item.working)
                # 原本 HEAD 有错 + 现在没删 + 现在没错 = 修好了
                if item.head_had_error and not item.error_msg:
                    fixed_count += 1

        total = len(final_list)
        self.state.video_state.loaded_danmakus = final_list
        self._reset_session()  # 提交后重置编辑器状态

        return total, fixed_count, removed_count

    def _reset_session(self):
        """清空工作区"""
        self.items.clear()
        self.item_order.clear()
        self.undo_stack.clear()
        self.set_dirty(False)

    def refresh_validation(self):
        """重新验证工作区数据并回填错误信息"""
        self._reorder_items()

        duration_ms = self.state.video_state.selected_part_duration_ms
        config = self.state.validation_config

        # 提取当前正在编辑的弹幕实例传入校验器
        working_list = [self.items[uid].working for uid in self.item_order]
        raw_issues = validate_danmaku_list(working_list, duration_ms, config)

        # 重置所有节点的错误状态
        for item in self.items.values():
            item.error_msg = ""

        # 回填新的错误信息
        for issue in raw_issues:
            uid = self.item_order[issue['original_index']]
            self.items[uid].error_msg = issue['reason']

    def generate_view_model(self, show_all: bool = False) -> list[ViewItem]:
        """生成供 UI 渲染的视图模型"""
        view_data: list[ViewItem] = []

        for uid in self.item_order:
            item = self.items[uid]
            if item.is_deleted:
                continue

            # 过滤：如果不是预览模式且没有错误，跳过
            if not show_all and not item.error_msg:
                continue

            view_data.append({
                "id": uid,
                "time_ms": item.working.progress,
                "content": item.working.msg,
                "error_msg": item.error_msg or "正常",
                "is_valid": not bool(item.error_msg)
            })

        return view_data

    def _push_undo_record(self, changes: list[AtomicChange]):
        """将一组变更记录推入撤销栈"""
        if changes:
            self.undo_stack.append(changes)
            self.set_dirty(True)

    def undo(self) -> bool:
        """
        撤销上一次暂存区的修改 (Revert)

        Returns:
            bool: 是否成功撤销
        """
        if not self.undo_stack:
            return False

        last_changes = self.undo_stack.pop()
        for change in last_changes:
            if item := self.items.get(change.item_id):
                change.field.set_value(item, change.previous_value)

        # 撤销后重新校验
        self.refresh_validation()
        self.set_dirty(bool(self.undo_stack))
        return True

    def delete_items(self, uids: list[str]):
        """批量标记删除弹幕"""
        if not uids:
            return

        batch_changes = []
        for uid in uids:
            item = self.items.get(uid)
            if item and not item.is_deleted:
                batch_changes.append(AtomicChange(uid, EditorField.IS_DELETED, False))
                item.is_deleted = True

        if batch_changes:
            self._push_undo_record(batch_changes)
            self.refresh_validation()
            self.logger.info(f"已批量删除 {len(batch_changes)} 条弹幕。")

    def update_item_content(self, uid: str, new_content: str):
        """更新单条弹幕文本"""
        item = self.items.get(uid)
        if item and item.working.msg != new_content:
            self._push_undo_record([AtomicChange(uid, EditorField.MSG, item.working.msg)])
            item.working.msg = new_content
            self.refresh_validation()

    def update_item_properties(self, uid: str, new_props: dict[EditorField, Any]) -> bool:
        """
        批量更新暂存区单条弹幕的多个属性。
        如果发生变化，将所有变化打包为一个原子撤销记录。
        """
        item = self.items.get(uid)
        if not item:
            return False

        changes = []
        for field, new_val in new_props.items():
            old_val = field.get_value(item)
            if old_val != new_val:
                changes.append(AtomicChange(uid, field, old_val))
                field.set_value(item, new_val)

        if changes:
            self._push_undo_record(changes)
            self.refresh_validation()
            return True

        return False

    def _execute_batch_transform(self, op_name: str, transform_fn: Callable[[Danmaku], bool]) -> tuple[int, int]:
        """通用批量操作引擎

        Args:
            op_name (str): 操作名称，用于日志记录
            transform_fn (Callable[[Danmaku], bool]): 业务逻辑函数。接收 Danmaku 对象，返回 True 表示发生了修改。

        Returns:
            tuple[int, int]: (修改数, 删除数)
        """
        current_step_changes: list[AtomicChange] = []
        modified_count = 0
        deleted_count = 0

        for uid in self.item_order:
            item = self.items[uid]
            if item.is_deleted:
                continue

            # 记录初态快照
            snap_msg, snap_progress = item.working.msg, item.working.progress

            if transform_fn(item.working):
                # 记录属性变化
                if item.working.msg != snap_msg:
                    current_step_changes.append(AtomicChange(uid, EditorField.MSG, snap_msg))
                if item.working.progress != snap_progress:
                    current_step_changes.append(AtomicChange(uid, EditorField.PROGRESS, snap_progress))

                # 业务逻辑：改空即删除
                if not item.working.msg.strip():
                    item.is_deleted = True
                    current_step_changes.append(AtomicChange(uid, EditorField.IS_DELETED, False))
                    deleted_count += 1
                else:
                    modified_count += 1

        if current_step_changes:
            self._push_undo_record(current_step_changes)
            self.refresh_validation()
            self.logger.info(f"批量操作 [{op_name}]: 修改 {modified_count}, 删除 {deleted_count}")

        return modified_count, deleted_count

    def batch_remove_newlines(self) -> tuple[int, int]:
        """批量去除换行符

        Returns:
            tuple[int, int]: 修改数, 删除数
        """
        def _rule(dm: Danmaku) -> bool:
            original = dm.msg
            dm.msg = dm.msg.replace('\n', '').replace('\\n', '').replace('/n', '').strip()
            return dm.msg != original

        return self._execute_batch_transform("去除换行", _rule)

    def batch_truncate_length(self, limit: int = 100) -> int:
        """批量截断弹幕内容。

        Args:
            limit (int, optional): 弹幕内容最大长度. Defaults to 100.

        Returns:
            int: 修改数
        """
        def _rule(dm: Danmaku) -> bool:
            original = dm.msg
            dm.msg = dm.msg[:limit]
            return dm.msg != original

        mod_count, _ = self._execute_batch_transform("长度截断", _rule)
        return mod_count

    def shift_time_axis(self, offset_ms: int) -> int:
        """平移弹幕时间轴

        Args:
            offset_ms (int): 偏移毫秒数（整数向后推迟，负数向前提前）

        Returns:
            int: 修改的条数
        """
        if offset_ms == 0:
            return 0

        def _shift_rule(dm: Danmaku) -> bool:
            initial_progress = dm.progress
            target_progress = max(0, dm.progress + offset_ms)
            dm.progress = target_progress
            return target_progress != initial_progress

        mod_count, _ = self._execute_batch_transform("时间平移", _shift_rule)
        return mod_count

    def _reorder_items(self):
        """
        根据工作区弹幕的最新时间重新排序。

        确保 items 字典的实际时间与 item_order 的索引顺序严格一致。
        """
        self.item_order.sort(key=lambda uid: self.items[uid].working.progress)