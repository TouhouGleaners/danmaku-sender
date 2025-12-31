import copy
import logging
from typing import Any

from ..config.shared_data import SharedDataModel
from ..core.bili_danmaku_utils import validate_danmaku_list


class ValidatorSession:
    """
    校验器逻辑会话层。
    负责管理数据快照、执行修改逻辑、维护脏状态。
    """
    def __init__(self, model: SharedDataModel):
        self.model = model
        self.logger = logging.getLogger("ValidatorSession")
        
        self.original_snapshot: list[dict] = []         # 原始数据的深拷贝
        self.current_issues: list[dict[str, Any]] = []  # 当前的问题列表

    @property
    def is_dirty(self) -> bool:
        return self.model.validator_is_dirty

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
            
        self.set_dirty(False)
        return len(self.current_issues) > 0

    def get_display_items(self):
        """获取用于 UI 显示的列表 (排除已标记删除的项)"""
        return [item for item in self.current_issues if not item['is_deleted']]

    def update_item_content(self, original_index: int, new_content: str):
        """更新单条内容"""
        for item in self.current_issues:
            if item['original_index'] == original_index:
                if item['current_content'] != new_content:
                    item['current_content'] = new_content
                    self.set_dirty(True)
                break

    def delete_item(self, original_index: int):
        """标记删除单条"""
        for item in self.current_issues:
            if item['original_index'] == original_index:
                item['is_deleted'] = True
                self.set_dirty(True)
                break

    def batch_remove_newlines(self) -> tuple[int, int]:
        """批量去除换行符

        Returns:
            tuple[int, int]: 修改数, 删除数
        """
        modified_count = 0
        deleted_count = 0
        
        for item in self.current_issues:
            if item['is_deleted']: continue
            
            content = item['current_content']
            if '\n' in content or '\\n' in content or '/n' in content:
                new_content = content.replace('\n', '').replace('\\n', '').replace('/n', '')
                
                if not new_content.strip():
                    item['is_deleted'] = True
                    deleted_count += 1
                else:
                    item['current_content'] = new_content
                    modified_count += 1
        
        if modified_count > 0 or deleted_count > 0:
            self.set_dirty(True)
            
        return modified_count, deleted_count

    def batch_truncate_length(self, limit=100) -> int:
        """批量截断弹幕内容。

        Args:
            limit (int, optional): 弹幕内容最大长度. Defaults to 100.

        Returns:
            int: 修改数
        """
        count = 0
        for item in self.current_issues:
            if item['is_deleted']: continue
            
            if len(item['current_content']) > limit:
                item['current_content'] = item['current_content'][:limit]
                count += 1
                
        if count > 0:
            self.set_dirty(True)
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
                    f"严重错误: 索引 {i} 的弹幕被标记为无效(is_valid=False)，"
                    f"但在修改记录中丢失。已自动移除该条目以阻断风险。"
                )
                deleted_count += 1

        self.logger.info(
            f"应用修改结果汇总: 原总数={len(self.original_snapshot)} | "
            f"保留(Kept)={kept_count}, 修复(Fixed)={fixed_count}, 删除(Deleted)={deleted_count} | "
            f"现总数={len(new_list)}"
        )

        self.model.loaded_danmakus = new_list
        self.set_dirty(False)
        
        self.original_snapshot = []
        self.current_issues = []
        
        return len(new_list), fixed_count, deleted_count