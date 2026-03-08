import copy
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, TypedDict

from .services.danmaku_validator import validate_danmaku_list
from .models.danmaku import Danmaku
from .state import AppState


class EditorField(Enum):
    """编辑器可改动的字段枚举"""
    MSG = "msg"
    COLOR = "color"
    FONT_SIZE = "fontsize"
    MODE = "mode"
    PROGRESS = "progress"
    IS_DELETED = "is_deleted"  # 逻辑删除标记


@dataclass(frozen=True)
class AtomicChange:
    """原子变更记录：描述单条弹幕单次属性的变化"""
    source_index: int     # 弹幕索引
    field: EditorField    # 修改了什么（强类型枚举）
    old_value: Any        # 以前的值


class ViewItem(TypedDict):
    """视图"""
    source_index: int
    time_ms: int
    content: str
    error_msg: str
    is_valid: bool


class EditorSession:
    """
    校验器逻辑会话层。
    管理全量暂存副本、执行校验、撤销以及排序逻辑。
    """
    def __init__(self, state: AppState):
        self.state = state
        self.logger = logging.getLogger("EditorSession")
        
        self.staged_danmakus: list[Danmaku] = []         # 当前编辑器里全量的弹幕副本
        self.validation_map: dict[int, str] = {}         # 记录错误索引：{ 原始索引: 错误原因 }
        self.deleted_indices: set[int] = set()           # 记录被标记删除的索引 (软删除)
        self.undo_stack: list[list[AtomicChange]] = []   # 撤销栈: 一次操作产生的一组变更记录

    @property
    def is_dirty(self) -> bool:
        return self.state.editor_is_dirty
    
    @property
    def has_active_session(self) -> bool:
        return bool(self.staged_danmakus)
    
    @property
    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def set_dirty(self, dirty: bool):
        self.state.editor_is_dirty = dirty

    def load_and_validate(self) -> bool:
        """加载数据并执行校验"""
        danmakus = self.state.video_state.loaded_danmakus
        if not danmakus:
            return False

        # 复制数据
        self.staged_danmakus = copy.deepcopy(danmakus)  # 存入暂存区

        # 按视频时间排序
        self.staged_danmakus.sort(key=lambda x: x.progress)

        # 清理 校验
        self.deleted_indices.clear()
        self.undo_stack.clear()

        self.refresh_validation()  # 执行校验并填充 validation_map

        self.set_dirty(False)
        return len(self.validation_map) > 0
    
    def refresh_validation(self):
        """运行校验算法并更新 validation_map 查找表"""
        duration_ms = self.state.video_state.selected_part_duration_ms
        raw_issues = validate_danmaku_list(self.staged_danmakus, duration_ms, self.state.validation_config)
        
        # 转换为 O(1) 查找字典：{ 原始索引: 理由 }
        self.validation_map = {issue['original_index']: issue['reason'] for issue in raw_issues}

    def generate_view_model(self, show_all: bool = False) -> list[ViewItem]:
        """生成渲染数据"""
        view_data: list[ViewItem] = []
        
        for i, dm in enumerate(self.staged_danmakus):
            if i in self.deleted_indices:
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
        """撤销上一次修改。

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
                if change.old_value is False:  # 撤销删除 = 恢复
                    self.deleted_indices.discard(idx)
                else:
                    self.deleted_indices.add(idx)

            # 通用逻辑处理：属性回滚
            else:
                if 0 <= idx < len(self.staged_danmakus):
                    setattr(self.staged_danmakus[idx], field.value, change.old_value)

        # 撤销后重新校验
        self.refresh_validation()
        self.set_dirty(bool(self.undo_stack))
        return True

    def update_item_content(self, original_index: int, new_content: str):
        """更新暂存区单条弹幕内容"""
        if 0 <= original_index < len(self.staged_danmakus):
            dm = self.staged_danmakus[original_index]
            if dm.msg != new_content:
                # 记录撤销
                self._push_undo_record([
                    AtomicChange(
                        source_index=original_index,
                        field=EditorField.MSG,
                        old_value=dm.msg
                    )
                ])

                dm.msg = new_content

                # 修改后重新计算校验状态
                self.refresh_validation()
                self.set_dirty(True)

    def delete_item(self, original_index: int):
        """标记删除单条"""
        if 0 <= original_index < len(self.staged_danmakus):
            if original_index not in self.deleted_indices:
                self._push_undo_record([
                    AtomicChange(
                        source_index=original_index,
                        field=EditorField.IS_DELETED,
                        old_value=False
                    )
                ])
                
                self.deleted_indices.add(original_index)
                self.refresh_validation()
                self.set_dirty(True)

    def _execute_batch_transform(self, op_name: str, transform_fn: Callable[[Danmaku], bool]) -> tuple[int, int]:
        """通用批量操作引擎

        Args:
            op_name (str): 操作名称，用于日志记录
            transform_fn (Callable[[Danmaku], bool]): 业务逻辑函数。接收 Danmaku 对象，
                                                      返回 True 表示发生了修改。

        Returns:
            tuple[int, int]: (修改数, 删除数)
        """
        current_changes: list[AtomicChange] = []
        modified_count = 0
        deleted_count = 0

        for i, dm in enumerate(self.staged_danmakus):
            # 基础过滤: 跳过已经删除的
            if i in self.deleted_indices:
                continue

            # 记录修改前的快照
            old_msg = dm.msg
            old_progress = dm.progress

            # 执行变换
            is_modified = transform_fn(dm)

            if is_modified:
                # 字段级的差异对比，自动记录到撤销栈
                if dm.msg != old_msg:
                    current_changes.append(AtomicChange(i, EditorField.MSG, old_msg))
                if dm.progress != old_progress:
                    current_changes.append(AtomicChange(i, EditorField.PROGRESS, old_progress))

                # 执行“删除逻辑”检查
                if not dm.msg.strip():
                    self.deleted_indices.add(i)
                    current_changes.append(AtomicChange(i, EditorField.IS_DELETED, False))
                    deleted_count += 1
                else:
                    modified_count += 1

        if current_changes:
            self._push_undo_record(current_changes)
            self.refresh_validation()
            self.set_dirty(True)
            self.logger.info(f"批量操作 [{op_name}] 完成: 修改 {modified_count}, 删除 {deleted_count}")

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

    def apply_changes(self) -> tuple[int, int, int]:
        """应用修改回 AppState。

        Returns:
            tuple[int, int, int]: 最终剩余总数, 修复数量, 删除数量
        """
        if not self.staged_danmakus:
            return 0, 0, 0

        # 只保留有效的弹幕
        final_list = [
            dm for i, dm in enumerate(self.staged_danmakus) 
            if i not in self.deleted_indices
        ]

        total = len(final_list)
        removed_count = len(self.staged_danmakus) - total

        # 写回全局状态
        self.state.video_state.loaded_danmakus = final_list

        # 清理状态
        self.staged_danmakus = []
        self.deleted_indices.clear()
        self.validation_map = {}
        self.undo_stack.clear()
        self.set_dirty(False)

        return total, 0, removed_count