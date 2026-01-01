import copy
import logging
from typing import Any, TypedDict

from ..config.shared_data import SharedDataModel
from ..core.bili_danmaku_utils import validate_danmaku_list

class ChangedRecord(TypedDict):
    original_index: int
    field: str
    old_value: Any


class ValidatorSession:
    """
    校验器逻辑会话层。
    负责管理数据快照、执行修改逻辑、维护脏状态及撤销栈。
    """
    def __init__(self, model: SharedDataModel):
        self.model = model
        self.logger = logging.getLogger("ValidatorSession")
        
        self.original_snapshot: list[dict] = []          # 原始数据的深拷贝
        self.current_issues: list[dict[str, Any]] = []   # 当前的问题列表

        self.undo_stack: list[list[ChangedRecord]] = []  # 撤销栈: 一次操作产生的一组变更记录

    @property
    def is_dirty(self) -> bool:
        return self.model.validator_is_dirty
    
    @property
    def has_active_session(self) -> bool:
        return bool(self.original_snapshot)
    
    @property
    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def set_dirty(self, dirty: bool):
        self.model.validator_is_dirty = dirty

    def load_and_validate(self, duration_ms: int) -> bool:
        """加载数据并执行校验。

        Args:
            duration_ms (int): 视频分P时长

        Returns:
            bool: 是否发现问题 (True/False)
        """
        if not self.model.loaded_danmakus:
            return False

        # 创建快照
        self.original_snapshot = copy.deepcopy(self.model.loaded_danmakus)
        self.logger.info(f"启动校验会话... 原始弹幕总数: {len(self.original_snapshot)}")
        
        # 执行校验
        raw_issues = validate_danmaku_list(self.original_snapshot, duration_ms)
        
        # 转换结构
        self.current_issues = []
        for issue in raw_issues:
            self.current_issues.append({
                'original_index': issue['original_index'],
                'time_ms': issue['danmaku'].get('progress', 0),
                'reason': issue['reason'],
                'current_content': issue['danmaku']['msg'],
                'is_deleted': False
            })

        self.logger.info(f"校验完成: 发现 {len(self.current_issues)} 个问题。")

        self.undo_stack.clear()    
        self.set_dirty(False)
        return len(self.current_issues) > 0

    def get_display_items(self):
        """获取用于 UI 显示的列表 (排除已标记删除的项)"""
        return [item for item in self.current_issues if not item['is_deleted']]
    
    def _push_undo_record(self, changes: list[ChangedRecord]):
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
            target_idx = change['original_index']
            target_field = change['field']
            old_val = change['old_value']

            for item in self.current_issues:
                if item['original_index'] == target_idx:
                    item[target_field] = old_val
                    break

        # 如果撤销栈已空，则已回至初始状态
        if not self.undo_stack:
            self.set_dirty(False)
        else:
            self.set_dirty(True)

        return True

    def update_item_content(self, original_index: int, new_content: str):
        """更新单条内容"""
        for item in self.current_issues:
            if item['original_index'] == original_index:
                if item['current_content'] != new_content:
                    change: ChangedRecord = {
                        'original_index': original_index,
                        'field': 'current_content',
                        'old_value': item['current_content']
                    }
                    self._push_undo_record([change])

                    item['current_content'] = new_content
                break

    def delete_item(self, original_index: int):
        """标记删除单条"""
        for item in self.current_issues:
            if item['original_index'] == original_index:
                if not item['is_deleted']:
                    change: ChangedRecord = {
                        'original_index': original_index,
                        'field': 'is_deleted',
                        'old_value': item['is_deleted']
                    }
                    self._push_undo_record([change])

                    item['is_deleted'] = True
                break

    def batch_remove_newlines(self) -> tuple[int, int]:
        """批量去除换行符

        Returns:
            tuple[int, int]: 修改数, 删除数
        """
        modified_count = 0
        deleted_count = 0
        current_changes: list[ChangedRecord] = []  # 本次批量操作的变更记录
        
        for item in self.current_issues:
            if item['is_deleted']:
                continue
            
            content = item['current_content']
            if '\n' in content or '\\n' in content or '/n' in content:
                new_content = content.replace('\n', '').replace('\\n', '').replace('/n', '')

                current_changes.append({
                    'original_index': item['original_index'],
                    'field': 'current_content',
                    'old_value': item['current_content']
                })
                
                if not new_content.strip():
                    current_changes.append({
                        'original_index': item['original_index'],
                        'field': 'is_deleted',
                        'old_value': item['is_deleted']
                    })
                    item['is_deleted'] = True
                    deleted_count += 1
                else:
                    item['current_content'] = new_content
                    modified_count += 1
        
        if current_changes:
            self._push_undo_record(current_changes)
            
        return modified_count, deleted_count

    def batch_truncate_length(self, limit=100) -> int:
        """批量截断弹幕内容。

        Args:
            limit (int, optional): 弹幕内容最大长度. Defaults to 100.

        Returns:
            int: 修改数
        """
        count = 0
        current_changes: list[ChangedRecord] = []  # 本次批量操作的变更记录

        for item in self.current_issues:
            if item['is_deleted']:
                continue
            
            if len(item['current_content']) > limit:
                current_changes.append({
                    'original_index': item['original_index'],
                    'field': 'current_content',
                    'old_value': item['current_content']
                })

                item['current_content'] = item['current_content'][:limit]
                count += 1
                
        if current_changes:
            self._push_undo_record(current_changes)

        return count

    def apply_changes(self) -> tuple[int, int, int]:
        """应用修改回 SharedDataModel。

        Returns:
            tuple[int, int, int]: 最终剩余总数, 修复数量, 删除数量
        """
        if not self.original_snapshot:
            return 0, 0, 0

        # 构建查找表：Key: original_index, Value: issue_record
        changes_map = {item['original_index']: item for item in self.current_issues}
        
        new_list = []       # 最终名单
        fixed_count = 0     # 统计：修好了多少个
        deleted_count = 0   # 统计：删掉了多少个
        kept_count = 0      # 统计：原本就是好的，直接保留的

        for i, dm in enumerate(self.original_snapshot):
            # 弹幕原本就是好的
            if dm.get('is_valid', False):
                new_list.append(dm)
                kept_count += 1
                continue
            
            # 弹幕原本有问题的，检查 changes_map
            if i in changes_map:
                issue_record = changes_map[i]

                if issue_record['is_deleted']:
                    deleted_count += 1
                else:
                    # 应用修改
                    dm['msg'] = issue_record['current_content']
                    dm['is_valid'] = True # 视为已修复
                    new_list.append(dm)
                    fixed_count += 1
            else:
                # 理论不可达
                # 弹幕原本有问题，但 changes_map 里找不到它
                self.logger.error(
                    f"数据一致性严重错误: 索引 {i} 的弹幕被标记为无效(is_valid=False)，"
                    f"但在修改记录中丢失。已强制保留原条目以避免数据丢失。"
                )
                new_list.append(dm)
                kept_count += 1  # 算作保留

        self.logger.info(
            f"应用修改结果汇总: 原总数={len(self.original_snapshot)} | "
            f"保留(Kept)={kept_count}, 修复(Fixed)={fixed_count}, 删除(Deleted)={deleted_count} | "
            f"现总数={len(new_list)}"
        )

        self.model.loaded_danmakus = new_list
        self.undo_stack.clear()
        self.set_dirty(False)
        
        self.original_snapshot = []
        self.current_issues = []
        
        return len(new_list), fixed_count, deleted_count