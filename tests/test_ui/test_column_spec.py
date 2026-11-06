"""列规格的装配期校验。"""
import pytest

from danmaku_sender.ui.framework.column_spec import ColumnSpec
from danmaku_sender.ui.framework.tree_model import TreeRowsModel


class TestColumnSpec:
    def test_to_qml_columns_converts(self, qapp):
        model = TreeRowsModel(("label", "sent"))
        specs = (
            ColumnSpec(role="label", title="名称", width=None, sub_role="sent"),
            ColumnSpec(role="sent", title="已发", width=56, align="right", tone_role="sent", tag=True),
        )
        columns = ColumnSpec.to_qml_columns(model, specs)
        assert columns == [
            {"role": "label", "subRole": "sent", "title": "名称", "width": None, "align": "left", "toneRole": None, "tag": False},
            {"role": "sent", "subRole": None, "title": "已发", "width": 56, "align": "right", "toneRole": "sent", "tag": True},
        ]

    def test_missing_role_raises(self, qapp):
        model = TreeRowsModel(("label",))
        specs = (ColumnSpec(role="nope", width=10),)
        with pytest.raises(ValueError, match="nope"):
            ColumnSpec.to_qml_columns(model, specs)

    def test_missing_tone_role_raises(self, qapp):
        model = TreeRowsModel(("label",))
        specs = (ColumnSpec(role="label", width=10, tone_role="nope", tag=True),)
        with pytest.raises(ValueError, match="nope"):
            ColumnSpec.to_qml_columns(model, specs)

    def test_tone_role_requires_tag(self, qapp):
        model = TreeRowsModel(("label", "sent"))
        specs = (ColumnSpec(role="label", width=None), ColumnSpec(role="sent", tone_role="sent"))
        with pytest.raises(ValueError, match="tone_role"):
            ColumnSpec.to_qml_columns(model, specs)

    def test_missing_sub_role_raises(self, qapp):
        model = TreeRowsModel(("label",))
        specs = (ColumnSpec(role="label", width=None, sub_role="nope"),)
        with pytest.raises(ValueError, match="nope"):
            ColumnSpec.to_qml_columns(model, specs)

    def test_sub_role_only_first_column(self, qapp):
        model = TreeRowsModel(("label", "sent"))
        specs = (ColumnSpec(role="label", width=None), ColumnSpec(role="sent", width=10, sub_role="sent"))
        with pytest.raises(ValueError, match="sub_role"):
            ColumnSpec.to_qml_columns(model, specs)

    def test_fill_column_in_middle_allowed_by_default(self, qapp):
        model = TreeRowsModel(("label", "sent"))
        specs = (ColumnSpec(role="label", width=10), ColumnSpec(role="sent", width=None))
        columns = ColumnSpec.to_qml_columns(model, specs)
        assert columns[1]["width"] is None

    def test_fill_column_must_be_first_when_required(self, qapp):
        model = TreeRowsModel(("label", "sent"))
        specs = (ColumnSpec(role="label", width=10), ColumnSpec(role="sent", width=None))
        with pytest.raises(ValueError, match="弹性列"):
            ColumnSpec.to_qml_columns(model, specs, require_fill_first=True)

    def test_tag_without_width_is_not_fill(self, qapp):
        """标签列自适应内容，不计弹性列。"""
        model = TreeRowsModel(("label", "sent"))
        specs = (ColumnSpec(role="label", width=None), ColumnSpec(role="sent", tag=True))
        columns = ColumnSpec.to_qml_columns(model, specs, require_fill_first=True)
        assert columns[1]["width"] is None

    def test_trailing_tags_ok(self, qapp):
        model = TreeRowsModel(("label", "sent"))
        specs = (ColumnSpec(role="label", width=None), ColumnSpec(role="sent", tag=True))
        columns = ColumnSpec.to_qml_columns(model, specs, require_trailing_tags=True)
        assert columns[1]["tag"] is True

    def test_tag_must_be_trailing_when_required(self, qapp):
        model = TreeRowsModel(("label", "sent"))
        specs = (ColumnSpec(role="label", width=None, tag=True), ColumnSpec(role="sent", width=10))
        with pytest.raises(ValueError, match="标签列"):
            ColumnSpec.to_qml_columns(model, specs, require_trailing_tags=True)

    def test_bad_align_raises(self, qapp):
        model = TreeRowsModel(("label",))
        specs = (ColumnSpec(role="label", width=10, align="middle"),)
        with pytest.raises(ValueError, match="align"):
            ColumnSpec.to_qml_columns(model, specs)

    def test_reserved_role_raises(self, qapp):
        model = TreeRowsModel(("label",))
        specs = (ColumnSpec(role="index", width=10),)
        with pytest.raises(ValueError, match=r"委托保留名: \['index'\]"):
            ColumnSpec.to_qml_columns(model, specs)

    def test_negative_width_raises(self, qapp):
        model = TreeRowsModel(("label",))
        specs = (ColumnSpec(role="label", width=-1),)
        with pytest.raises(ValueError, match="width 为负"):
            ColumnSpec.to_qml_columns(model, specs)
