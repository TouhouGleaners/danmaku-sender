"""列规格的装配期校验。"""
import pytest

from danmaku_sender.ui.framework.column_spec import ColumnSpec
from danmaku_sender.ui.framework.tree_model import TreeRowsModel


class TestColumnSpec:
    def test_to_qml_columns_converts(self, qapp):
        model = TreeRowsModel(("label", "sent"))
        specs = (
            ColumnSpec(role="label", title="名称", width=None),
            ColumnSpec(role="sent", title="已发", width=56, align="right", color_role="label"),
        )
        columns = ColumnSpec.to_qml_columns(model, specs)
        assert columns == [
            {"role": "label", "title": "名称", "width": None, "align": "left", "colorRole": None},
            {"role": "sent", "title": "已发", "width": 56, "align": "right", "colorRole": "label"},
        ]

    def test_missing_role_raises(self, qapp):
        model = TreeRowsModel(("label",))
        specs = (ColumnSpec(role="nope", width=10),)
        with pytest.raises(ValueError, match="nope"):
            ColumnSpec.to_qml_columns(model, specs)

    def test_missing_color_role_raises(self, qapp):
        model = TreeRowsModel(("label",))
        specs = (ColumnSpec(role="label", width=10, color_role="nope"),)
        with pytest.raises(ValueError, match="nope"):
            ColumnSpec.to_qml_columns(model, specs)

    def test_fill_column_must_be_first(self, qapp):
        model = TreeRowsModel(("label", "sent"))
        specs = (ColumnSpec(role="label", width=10), ColumnSpec(role="sent", width=None))
        with pytest.raises(ValueError, match="弹性列"):
            ColumnSpec.to_qml_columns(model, specs)

    def test_bad_align_raises(self, qapp):
        model = TreeRowsModel(("label",))
        specs = (ColumnSpec(role="label", width=10, align="middle"),)
        with pytest.raises(ValueError, match="align"):
            ColumnSpec.to_qml_columns(model, specs)
