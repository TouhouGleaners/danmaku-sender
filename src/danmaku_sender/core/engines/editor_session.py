import copy
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, TypedDict

from ..state import AppState

from ..models.danmaku import Danmaku
from ..services.danmaku_validator import validate_danmaku_list


class EditorField(Enum):
    """编辑器可改动的字段枚举"""
    MSG = "msg"
    COLOR = "color"
    FONT_SIZE = "fontsize"
    MODE = "mode"
    PROGRESS = "progress"
    IS_DELETED = "is_deleted"  # 逻辑删除标记

    def get_value(self, dm: Danmaku) -> Any:
        """获取 Danmaku 实例中对应的属性值，集中管理映射关系"""
        return getattr(dm, self.value)

    def set_value(self, dm: Danmaku, val: Any) -> None:
        """设置 Danmaku 实例中对应的属性值"""
        setattr(dm, self.value, val)


@dataclass(frozen=True)
class AtomicChange:
    """原子变更记录：描述单条弹幕单次属性的变化"""
    source_index: int     # 暂存区索引
    field: EditorField    # 修改字段
    previous_value: Any   # 该变化发生前的原始值


class ViewItem(TypedDict):
    """视图"""
    source_index: int
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
        self.logger = logging.getLogger("EditorSession")
        
        self.staged_danmakus: list[Danmaku] = []         # Workspace / Staging Area (暂存区真值)
        self.staged_deletions: set[int] = set()          # Staged for deletion (待删除索引集)
        self.head_errors: set[int] = set()               # Snapshot of errors at checkout (HEAD)
        
        self.validation_map: dict[int, str] = {}        # 实时校验映射表
        self.undo_stack: list[list[AtomicChange]] = []  # 操作记录

    @property
    def is_dirty(self) -> bool:
        return self.state.editor_is_dirty
    
    @property
    def has_active_session(self) -> bool:
        """暂存区是否有已检出的数据"""
        return bool(self.staged_danmakus)

    @property
    def active_error_count(self) -> int:
        """获取当前可见（未标记删除）的错误总数"""
        return sum(1 for idx in self.validation_map if idx not in self.staged_deletions)

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

        # 检出并排序
        self.staged_danmakus = copy.deepcopy(source)
        self.staged_danmakus.sort(key=lambda x: x.progress)

        # 清理会话状态
        self.staged_deletions.clear()
        self.undo_stack.clear()

        # 初始校验并记录 HEAD 错误
        self.refresh_validation()
        self.head_errors = set(self.validation_map.keys())

        self.set_dirty(False)
        return bool(self.validation_map)

    def commit_to_state(self) -> tuple[int, int, int]:
        """将暂存区的改动正式提交到全局状态，并计算。

        Returns:
            tuple[int, int, int]: (总数, 修复数, 删除数)
        """
        if not self.staged_danmakus:
            return 0, 0, 0

        head_errs = self.head_errors                    # checkout 时的错误索引 (HEAD)
        current_errs = set(self.validation_map.keys())  # 现在的错误索引 (Current)
        deleted_indices = self.staged_deletions         # 被标记删除的索引 (Deleted)

        # 计算修好的数量
        # 逻辑：在 HEAD 错误中，排除掉“现在还错的”和“被删掉的”
        fixed_indices = head_errs - current_errs - deleted_indices
        fixed_count = len(fixed_indices)

        # 准备提交名单 (过滤掉标记删除的)
        final_list = [
            dm for i, dm in enumerate(self.staged_danmakus) 
            if i not in self.staged_deletions
        ]

        total = len(final_list)
        removed_count = len(self.staged_danmakus) - total

        # 写回全局状态
        self.state.video_state.loaded_danmakus = final_list

        # 清理暂存区
        self._reset_session()

        return total, fixed_count, removed_count

    def _reset_session(self):
        """重置编辑器所有内部状态"""
        self.staged_danmakus = []
        self.staged_deletions = set()
        self.head_errors = set()
        self.validation_map = {}
        self.undo_stack = []
        self.set_dirty(False)

    def refresh_validation(self):
        """运行校验算法并更新 validation_map 查找表"""
        duration_ms = self.state.video_state.selected_part_duration_ms
        raw_issues = validate_danmaku_list(self.staged_danmakus, duration_ms, self.state.validation_config)
        
        # 转换为 O(1) 查找字典：{ 原始索引: 理由 }
        self.validation_map = {issue['original_index']: issue['reason'] for issue in raw_issues}

    def generate_view_model(self, show_all: bool = False) -> list[ViewItem]:
        """生成渲染视图"""
        view_data: list[ViewItem] = []
        
        for i, dm in enumerate(self.staged_danmakus):
            if i in self.staged_deletions:
                continue
                
            error_msg = self.validation_map.get(i, "")
            
            # 过滤：如果不是预览模式且没有错误，跳过
            if not show_all and not error_msg:
                continue
                
            view_data.append({
                "source_index": i,
                "time_ms": dm.progress,
                "content": dm.msg,
                "error_msg": error_msg or "正常",  # 正常的显示为“正常”
                "is_valid": not bool(error_msg)
            })
        return view_data

    def _push_undo_record(self, changes: list[AtomicChange]):
        """将一组变更记录推入撤销栈"""
        if changes:
            self.undo_stack.append(changes)
            self.set_dirty(True)

    def undo(self) -> bool:
        """撤销上一次暂存区的修改

        Returns:
            bool: 是否成功撤销
        """
        if not self.undo_stack:
            return False
        
        last_changes = self.undo_stack.pop()

        for change in last_changes:
            idx = change.source_index
            field = change.field
            if field == EditorField.IS_DELETED:
                # 恢复删除状态
                self.staged_deletions.discard(idx) if change.previous_value is False else self.staged_deletions.add(idx)
            else:
                if 0 <= idx < len(self.staged_danmakus):
                    field.set_value(self.staged_danmakus[idx], change.previous_value)

        # 撤销后重新校验
        self.refresh_validation()
        self.set_dirty(bool(self.undo_stack))
        return True

    def delete_item(self, original_index: int):
        """标记删除单条弹幕"""
        if 0 <= original_index < len(self.staged_danmakus):
            if original_index not in self.staged_deletions:
                self._push_undo_record([AtomicChange(original_index, EditorField.IS_DELETED, False)])
                self.staged_deletions.add(original_index)
                self.refresh_validation()

    def update_item_content(self, original_index: int, new_content: str):
        """更新暂存区单条弹幕内容"""
        if 0 <= original_index < len(self.staged_danmakus):
            dm = self.staged_danmakus[original_index]
            if dm.msg != new_content:
                # 记录撤销
                self._push_undo_record([AtomicChange(original_index, EditorField.MSG, dm.msg)])
                dm.msg = new_content
                self.refresh_validation()

    def update_item_properties(self, original_index: int, new_props: dict[EditorField, Any]) -> bool:
        """
        批量更新暂存区单条弹幕的多个属性。
        如果发生变化，将所有变化打包为一个原子撤销记录。
        """
        if 0 <= original_index < len(self.staged_danmakus):
            dm = self.staged_danmakus[original_index]
            changes = []

            for field, new_val in new_props.items():
                old_val = field.get_value(dm)
                if old_val != new_val:
                    changes.append(AtomicChange(original_index, field, old_val))
                    field.set_value(dm, new_val)

            if changes:
                self._push_undo_record(changes)
                self.refresh_validation()
                return True

        return False

    def _execute_batch_transform(self, op_name: str, transform_fn: Callable[[Danmaku], bool]) -> tuple[int, int]:
        """通用批量操作引擎

        Args:
            op_name (str): 操作名称，用于日志记录
            transform_fn (Callable[[Danmaku], bool]): 业务逻辑函数。接收 Danmaku 对象，
                                                      返回 True 表示发生了修改。

        Returns:
            tuple[int, int]: (修改数, 删除数)
        """
        current_step_changes: list[AtomicChange] = []
        modified_count = 0
        deleted_count = 0

        for i, dm in enumerate(self.staged_danmakus):
            # 基础过滤: 跳过已经删除的
            if i in self.staged_deletions:
                continue

            # 记录初态快照
            snap_msg, snap_progress = dm.msg, dm.progress

            if transform_fn(dm):
                # 记录属性变化
                if dm.msg != snap_msg:
                    current_step_changes.append(AtomicChange(i, EditorField.MSG, snap_msg))
                if dm.progress != snap_progress:
                    current_step_changes.append(AtomicChange(i, EditorField.PROGRESS, snap_progress))

                # 业务逻辑：改空即删除
                if not dm.msg.strip():
                    self.staged_deletions.add(i)
                    current_step_changes.append(AtomicChange(i, EditorField.IS_DELETED, False))
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