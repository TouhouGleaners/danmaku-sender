import copy
import logging
import colorsys
from typing import Any, Callable

from ..state import ValidationConfig
from ..entities.danmaku import Danmaku
from ..types.editor_types import EditorItem, EditorField, AtomicChange, ViewItem, InsertPosition
from ..services.danmaku_validator import validate_danmaku_list


class EditorSession:
    """
    纯净的弹幕编辑器核心会话层 (Sandbox)。
    只负责暂存区的增删改查与撤销树维护，不主动干涉全局状态 (AppState)。
    """
    def __init__(self) -> None:
        self.logger = logging.getLogger("App.System.Editor.Session")
        self.items: dict[str, EditorItem] = {}          # 核心存储：UUID 映射表
        self.item_order: list[str] = []                 # 顺序表：维护弹幕在视频中的物理播放顺序
        self.undo_stack: list[list[AtomicChange]] = []  # 操作栈：撤销功能
        self._is_dirty: bool = False

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

    def set_dirty(self, dirty: bool):
        self._is_dirty = dirty

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

    # region Data I/O

    def load_data(self, danmakus: list[Danmaku]):
        """从外部数据加载到编辑器会话"""
        self.items.clear()
        self.item_order.clear()
        self.undo_stack.clear()
        self.set_dirty(False)

        sorted_source = sorted(danmakus, key=lambda x: x.progress)
        for dm in sorted_source:
            item = EditorItem(head=copy.deepcopy(dm), working=copy.deepcopy(dm))
            self.items[item.id] = item
            self.item_order.append(item.id)

    def get_committed_data(self) -> tuple[list[Danmaku], int, int]:
        """
        获取当前工作区的最终数据列表（不包含标记删除的项）

        Returns:
            (final_list, fixed_count, removed_count)
        """
        if not self.items:
            return [], 0, 0

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

        self.set_dirty(False)
        return final_list, fixed_count, removed_count

    # endregion
    # region Data Validation & View Rendering

    def validate(self, duration_ms: int, config: ValidationConfig):
        """对当前工作区数据进行校验，并回填错误信息"""
        self._reorder_items()

        active_uids = [uid for uid in self.item_order if not self.items[uid].is_deleted]
        working_list = [self.items[uid].working for uid in active_uids]

        raw_issues = validate_danmaku_list(working_list, duration_ms, config)

        # 重置所有节点的错误状态
        for item in self.items.values():
            item.error_msg = ""

        # 回填新的错误信息
        for issue in raw_issues:
            uid = active_uids[issue['original_index']]
            self.items[uid].error_msg = issue['reason']

    def mark_head_errors(self):
        """根据当前错误状态更新 HEAD 错误快照"""
        for item in self.items.values():
            item.head_had_error = bool(item.error_msg)

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

    # endregion
    # region Atomic Operations and Batch Modification Logic

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

        self.set_dirty(bool(self.undo_stack))
        return True

    def insert_item(self, reference_uid: str, position: InsertPosition = InsertPosition.BELOW) -> str | None:
        """在指定弹幕附近插入一条新弹幕"""
        ref_item = self.items.get(reference_uid)
        if not ref_item:
            return None

        offset = 500 if position == InsertPosition.BELOW else -500
        new_progress = max(0, ref_item.working.progress + offset)

        new_dm = Danmaku(
            msg="新建弹幕",
            color=ref_item.working.color,
            fontsize=ref_item.working.fontsize,
            mode=ref_item.working.mode,
            progress=new_progress
        )

        new_item = EditorItem(head=new_dm.clone(), working=new_dm.clone())
        new_uid = new_item.id

        self.items[new_uid] = new_item
        self.item_order.append(new_uid)

        self._push_undo_record([AtomicChange(new_uid, EditorField.IS_DELETED, True)])  # 新增记录为“从无到有”，撤销时即标记删除

        return new_uid

    def delete_items(self, uids: list[str]) -> bool:
        """批量标记删除弹幕"""
        if not uids:
            return False

        batch_changes = []
        for uid in uids:
            item = self.items.get(uid)
            if item and not item.is_deleted:
                batch_changes.append(AtomicChange(uid, EditorField.IS_DELETED, False))
                item.is_deleted = True

        if batch_changes:
            self._push_undo_record(batch_changes)
            return True
        return False

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
            return True
        return False

    def _execute_batch_transform(self, transform_fn: Callable[[Danmaku], bool], target_uids: list[str] | None = None) -> tuple[int, int]:
        """通用批量操作引擎

        Args:
            op_name (str): 操作名称，用于日志记录
            transform_fn (Callable[[Danmaku], bool]): 业务逻辑函数。接收 Danmaku 对象，返回 True 表示发生了修改。
            target_uids (list[str] | None): 可选的目标 UID 列表，如果为 None 则作用于所有未删除项。

        Returns:
            tuple[int, int]: (修改数, 删除数)
        """
        current_step_changes: list[AtomicChange] = []
        modified_count = 0
        deleted_count = 0

        # 如果传入了 target_uids，将其转为 set 提升查询性能
        target_set = set(target_uids) if target_uids is not None else None

        for uid in self.item_order:
            item = self.items[uid]
            if item.is_deleted:
                continue

            if target_set is not None and uid not in target_set:
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

        return self._execute_batch_transform(_rule)

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

        mod_count, _ = self._execute_batch_transform(_rule)
        return mod_count

    def shift_time_axis(self, offset_ms: int, target_uids: list[str] | None = None) -> int:
        """平移弹幕时间轴

        Args:
            offset_ms (int): 偏移毫秒数（整数向后推迟，负数向前提前）
            target_uids (list[str] | None): 可选的目标 UID 列表，如果为 None 则作用于所有未删除项.

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

        mod_count, _ = self._execute_batch_transform(_shift_rule, target_uids)
        return mod_count

    def _reorder_items(self):
        """
        根据工作区弹幕的最新时间重新排序。

        确保 items 字典的实际时间与 item_order 的索引顺序严格一致。
        """
        self.item_order.sort(key=lambda uid: self.items[uid].working.progress)

    # endregion

    def generate_danmaku_array(self, ref_uid: str, text: str, mode: Danmaku.Mode, count: int, color_strategy: str) -> list[str]:
        """生成同一时刻的弹幕阵列"""
        ref_item = self.items.get(ref_uid)
        if not ref_item:
            return []

        target_time = ref_item.working.progress

        # 准备颜色序列
        colors = []
        if color_strategy == "classic":
            std_colors = Danmaku.Standards.COLORS
            for i in range(count):
                hex_str = std_colors[i % len(std_colors)].lstrip('#')
                colors.append(int(hex_str, 16))
        else:  # rainbow
            for i in range(count):
                hue = i / max(1, count)
                r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                colors.append((int(r * 255) << 16) + (int(g * 255) << 8) + int(b * 255))

        # 批量创建入库
        new_uids = []
        batch_changes = []

        for color in colors:
            dm = Danmaku(
                msg=text,
                progress=target_time,
                mode=mode,
                fontsize=ref_item.working.fontsize,
                color=color
            )

            new_item = EditorItem(head=dm.clone(), working=dm.clone())
            uid = new_item.id

            self.items[uid] = new_item
            self.item_order.append(uid)
            new_uids.append(uid)

            # 记录新增事件以便撤销
            batch_changes.append(AtomicChange(uid, EditorField.IS_DELETED, True))

        if batch_changes:
            self._push_undo_record(batch_changes)
            self._reorder_items()

        return new_uids