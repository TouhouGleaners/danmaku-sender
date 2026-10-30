"""通用树视图的平铺行模型。

节点树只在内部持有，行列表只含当前展开可见的节点。
展开 = 在行间插入子行，折叠 = 移除子行，供 QML 行列表的插入/位移过渡画出展开动效。

角色契约（TreeRowsModel.roleNames）：
结构角色 ``depth`` / ``expandable`` / ``expanded`` 由本模型固定提供，
内容角色由构造时登记的角色名提供，取值来自节点 data 的同名键。
"""
from collections.abc import Sequence
from enum import IntEnum
from typing import Any

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Qt, Slot


class TreeRowRole(IntEnum):
    """平铺行角色的取值区间起点：结构角色在前，内容角色随后。"""

    STRUCT_BASE = Qt.ItemDataRole.UserRole + 1


ROLE_DEPTH = int(TreeRowRole.STRUCT_BASE)
ROLE_EXPANDABLE = ROLE_DEPTH + 1
ROLE_EXPANDED = ROLE_DEPTH + 2
ROLE_CONTENT_BASE = ROLE_DEPTH + 3


class TreeNode:
    """通用树节点。

    Attributes:
        data (dict[str, Any]): 内容角色取值，键与模型登记的角色名对应。
        payload (Any): 业务负载，不进角色，供调用方按行取回。
        children (list[TreeNode]): 子节点。
        expanded (bool): 是否处于展开态。
        parent (TreeNode | None): 父节点，根为 None。
    """

    data: dict[str, Any]
    payload: Any
    children: list["TreeNode"]
    expanded: bool
    parent: "TreeNode | None"

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        payload: Any = None,
        children: list["TreeNode"] | None = None,
        parent: "TreeNode | None" = None,
    ) -> None:
        self.data = data if data is not None else {}
        self.payload = payload
        self.children = children or []
        self.expanded = False
        self.parent = parent
        for child in self.children:
            child.parent = self

    def add_child(self, child: "TreeNode") -> None:
        """挂载子节点并同步父子指针。

        Args:
            child (TreeNode): 待挂载的子节点。
        """
        child.parent = self
        self.children.append(child)

    @property
    def depth(self) -> int:
        """本节点的层深，顶层节点为 0。"""
        node = self
        depth = 0
        while node.parent is not None:
            depth += 1
            node = node.parent
        return depth

    @property
    def expandable(self) -> bool:
        """是否含子节点。"""
        return bool(self.children)


class TreeRowsModel(QAbstractListModel):
    """通用树的平铺可见行模型。

    Args:
        content_roles (Sequence[str]): 内容角色名序列，取值来自节点 data 的同名键。
        parent (QObject | None): 父对象。
    """

    # 结构角色名：roleNames 的前三项，也是内容角色的保留字
    STRUCTURAL_ROLE_NAMES = ("depth", "expandable", "expanded")

    def __init__(self, content_roles: Sequence[str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        roles = tuple(content_roles)
        reserved = set(self.STRUCTURAL_ROLE_NAMES)
        if len(set(roles)) != len(roles) or not reserved.isdisjoint(roles):
            raise ValueError("content_roles 不得重复，也不得占用结构角色名 depth/expandable/expanded")
        self._content_roles = roles
        self._roots: list[TreeNode] = []
        self._visible: list[TreeNode] = []

    def set_roots(self, roots: list[TreeNode]) -> None:
        """重建行列表，可见行回到折叠态的顶层节点。

        Args:
            roots (list[TreeNode]): 顶层节点列表，按显示序。
        """
        self.beginResetModel()
        self._roots = list(roots)
        for root in self._roots:
            root.parent = None
        self._set_expanded(self._roots, False)
        self._visible = list(self._roots)
        self.endResetModel()

    def payload_at(self, row: int) -> Any:
        """取行对应的业务负载。

        Args:
            row (int): 行号。

        Returns:
            Any: 节点的 payload；非法行返回 None。
        """
        if 0 <= row < len(self._visible):
            return self._visible[row].payload
        return None

    @Slot(int)
    def toggle(self, row: int) -> None:
        """切换行的展开态。

        叶子行无动作。展开插入其可见子行，折叠移除其下全部可见行。

        Args:
            row (int): 行号。
        """
        node = self._node_at(row)
        if not node.children:
            return
        if node.expanded:
            self._collapse(node, row)
        else:
            self._expand(node, row)

    @Slot(int, result=bool)
    def expand(self, row: int) -> bool:
        """展开指定行。

        Args:
            row (int): 行号。

        Returns:
            bool: 是否发生展开；已展开或无子行时为 False。
        """
        node = self._node_at(row)
        if node.expanded or not node.children:
            return False
        self._expand(node, row)
        return True

    @Slot(int, result=bool)
    def collapse(self, row: int) -> bool:
        """收起指定行。

        Args:
            row (int): 行号。

        Returns:
            bool: 是否发生收起；已收起或无子行时为 False。
        """
        node = self._node_at(row)
        if not node.expanded:
            return False
        self._collapse(node, row)
        return True

    @Slot(int, result=object)
    def first_child_row(self, row: int) -> int | None:
        """取首个可见子行的行号。

        Args:
            row (int): 行号。

        Returns:
            int | None: 子行行号；无可见子行时为 None。
        """
        node = self._node_at(row)
        if not node.expanded or not node.children:
            return None
        return self._visible.index(node.children[0])

    @Slot(int, result=object)
    def parent_row(self, row: int) -> int | None:
        """取父行的行号。

        Args:
            row (int): 行号。

        Returns:
            int | None: 父行行号；顶层行或非法行为 None。
        """
        node = self._node_at(row)
        if node.parent is None:
            return None
        return self._visible.index(node.parent)

    def expand_all(self) -> None:
        """展开全部分组节点。"""
        self.beginResetModel()
        self._set_expanded(self._roots, True)
        self._visible = self._flatten_roots()
        self.endResetModel()

    def _expand(self, node: TreeNode, row: int) -> None:
        """插入节点的可见子行。"""
        node.expanded = True
        rows = self._flatten(node)
        if rows:
            self.beginInsertRows(QModelIndex(), row + 1, row + len(rows))
            self._visible[row + 1:row + 1] = rows
            self.endInsertRows()
        self._emit_expanded(row)

    def _collapse(self, node: TreeNode, row: int) -> None:
        """移除节点之下的全部可见行。"""
        node.expanded = False
        end = row + 1
        while end < len(self._visible) and self._visible[end].depth > node.depth:
            end += 1
        if end > row + 1:
            self.beginRemoveRows(QModelIndex(), row + 1, end - 1)
            del self._visible[row + 1:end]
            self.endRemoveRows()
        self._emit_expanded(row)

    def _emit_expanded(self, row: int) -> None:
        self.dataChanged.emit(self.index(row), self.index(row), [ROLE_EXPANDED])

    def _node_at(self, row: int) -> TreeNode:
        if 0 <= row < len(self._visible):
            return self._visible[row]
        return TreeNode()

    def _flatten_roots(self) -> list[TreeNode]:
        rows: list[TreeNode] = []
        for root in self._roots:
            rows.append(root)
            if root.expanded:
                rows.extend(self._flatten(root))
        return rows

    def _flatten(self, node: TreeNode) -> list[TreeNode]:
        """按显示序展开节点的可见子树：自身子行 + 各子节点展开中的子树。"""
        rows: list[TreeNode] = []
        for child in node.children:
            rows.append(child)
            if child.expanded:
                rows.extend(self._flatten(child))
        return rows

    @classmethod
    def _set_expanded(cls, nodes: list[TreeNode], expanded: bool) -> None:
        """递归设置分组节点的展开态。"""
        for node in nodes:
            if node.children:
                node.expanded = expanded
                cls._set_expanded(node.children, expanded)

    # --- Qt 模型接口 ---

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._visible)

    def roleNames(self) -> dict[int, bytes]:
        roles: dict[int, bytes] = {}
        for offset, name in enumerate(self.STRUCTURAL_ROLE_NAMES):
            roles[ROLE_DEPTH + offset] = name.encode()
        for offset, name in enumerate(self._content_roles):
            roles[ROLE_CONTENT_BASE + offset] = name.encode()
        return roles

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        node = self._visible[index.row()]
        if role == ROLE_DEPTH:
            return node.depth
        if role == ROLE_EXPANDABLE:
            return node.expandable
        if role == ROLE_EXPANDED:
            return node.expanded
        offset = role - ROLE_CONTENT_BASE
        if 0 <= offset < len(self._content_roles):
            return node.data.get(self._content_roles[offset])
        return None
