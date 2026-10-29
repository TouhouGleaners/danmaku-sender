"""通用树平铺行模型：展开/折叠的行插删与角色。"""
from danmaku_sender.ui.framework.tree_model import (
    ROLE_CONTENT_BASE,
    ROLE_DEPTH,
    ROLE_EXPANDABLE,
    ROLE_EXPANDED,
    TreeNode,
    TreeRowsModel,
)


def _model() -> TreeRowsModel:
    """构造一棵 年→月→任务 三层的行模型。"""
    model = TreeRowsModel(("label",))
    year = TreeNode(
        data={"label": "2026 年"},
        children=[
            TreeNode(
                data={"label": "10 月"},
                children=[
                    TreeNode(data={"label": "任务一"}, payload="t1"),
                    TreeNode(data={"label": "任务二"}, payload="t2"),
                ],
            )
        ],
    )
    model.set_roots([year])
    return model


class TestTreeRows:
    def test_collapsed_shows_roots_only(self, qapp):
        model = _model()
        assert model.rowCount() == 1
        assert model.data(model.index(0), ROLE_DEPTH) == 0
        assert model.data(model.index(0), ROLE_EXPANDABLE) is True
        assert model.data(model.index(0), ROLE_EXPANDED) is False

    def test_toggle_expands_and_collapses_rows(self, qapp):
        model = _model()
        model.toggle(0)
        assert model.rowCount() == 2
        assert model.data(model.index(1), ROLE_DEPTH) == 1

        model.toggle(1)
        assert model.rowCount() == 4
        assert [model.payload_at(row) for row in range(4)] == [None, None, "t1", "t2"]

        model.toggle(1)
        assert model.rowCount() == 2
        assert model.payload_at(1) is None

    def test_collapse_keeps_nested_expansion_state(self, qapp):
        """折叠再展开，子层的展开态保留。"""
        model = _model()
        model.toggle(0)
        model.toggle(1)
        assert model.rowCount() == 4

        model.toggle(0)
        assert model.rowCount() == 1
        model.toggle(0)
        assert model.rowCount() == 4

    def test_toggle_leaf_row_is_noop(self, qapp):
        model = _model()
        model.expand_all()
        rows = model.rowCount()
        model.toggle(2)
        assert model.rowCount() == rows

    def test_content_roles_read_node_data(self, qapp):
        model = _model()
        assert model.data(model.index(0), ROLE_CONTENT_BASE) == "2026 年"
        assert model.data(model.index(0), ROLE_EXPANDED) is False
        model.toggle(0)
        assert model.data(model.index(0), ROLE_EXPANDED) is True

    def test_payload_at_rejects_out_of_range(self, qapp):
        model = _model()
        assert model.payload_at(99) is None
