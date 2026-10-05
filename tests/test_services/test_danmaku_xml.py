"""DanmakuXml 单元测试"""
from pathlib import Path

import pytest

from danmaku_sender.config import SenderConfig
from danmaku_sender.service.danmaku_xml import DanmakuXml
from danmaku_sender.types.models.common import UnsentDanmakusRecord, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskStatus

VALID_XML = """<?xml version="1.0" encoding="UTF-8"?>
<i>
  <d p="1.5,1,25,16777215,0,0,0,0">第一条</d>
  <d p="2.0,1,25,16777215,0,0,0,0">第二条</d>
</i>
"""

EMPTY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<i>
</i>
"""


def write_xml(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestParseFile:
    def test_reads_danmakus(self, tmp_path):
        path = write_xml(tmp_path, "ok.xml", VALID_XML)
        danmakus = DanmakuXml.parse_file(path)
        assert [d.msg for d in danmakus] == ["第一条", "第二条"]
        assert danmakus[0].progress == 1500

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            DanmakuXml.parse_file(tmp_path / "nope.xml")

    def test_malformed_xml_raises(self, tmp_path):
        path = write_xml(tmp_path, "bad.xml", "<i><d>没关上")
        with pytest.raises(ValueError):
            DanmakuXml.parse_file(path)

    def test_no_danmakus_yields_empty_list(self, tmp_path):
        path = write_xml(tmp_path, "empty.xml", EMPTY_XML)
        assert DanmakuXml.parse_file(path) == []


class TestParseOnlineDmids:
    def test_extracts_identity_field(self):
        xml = '<i><d p="1.0,1,25,16777215,0,0,0,12345,67890">x</d></i>'
        assert DanmakuXml.parse_online_dmids(xml) == ["12345"]

    def test_empty_document_yields_empty_list(self):
        assert DanmakuXml.parse_online_dmids("") == []


class TestLoadTask:
    def test_builds_task_without_target(self, tmp_path):
        path = write_xml(tmp_path, "ok.xml", VALID_XML)
        config = SenderConfig().to_task_config()
        task = DanmakuXml.load_task(path, config)

        assert task is not None
        assert task.target == VideoTarget.unset()
        assert task.total == 2
        assert task.xml_path == path
        assert task.config_snapshot == config
        assert task.status is TaskStatus.UNCONFIGURED

    def test_broken_file_raises(self, tmp_path):
        path = write_xml(tmp_path, "bad.xml", "<i><d>没关上")
        with pytest.raises(ValueError):
            DanmakuXml.load_task(path, SenderConfig().to_task_config())

    def test_empty_file_raises(self, tmp_path):
        path = write_xml(tmp_path, "empty.xml", EMPTY_XML)
        with pytest.raises(ValueError, match="内容为空"):
            DanmakuXml.load_task(path, SenderConfig().to_task_config())

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            DanmakuXml.load_task(tmp_path / "nope.xml", SenderConfig().to_task_config())


class TestExport:
    def test_export_danmakus_round_trips(self, tmp_path):
        danmakus = [Danmaku(msg="第二条", progress=2000), Danmaku(msg="第一条", progress=1000)]
        out = tmp_path / "out.xml"
        DanmakuXml.export_danmakus(danmakus, out)

        reparsed = DanmakuXml.parse_file(out)
        assert [d.msg for d in reparsed] == ["第一条", "第二条"]
        assert [d.progress for d in reparsed] == [1000, 2000]

    def test_export_unsent_groups_by_reason(self, tmp_path):
        records: list[UnsentDanmakusRecord] = [
            {"dm": Danmaku(msg="a", progress=1000), "reason": "网络错误"},
            {"dm": Danmaku(msg="b", progress=2000), "reason": "网络错误"},
            {"dm": Danmaku(msg="c", progress=3000), "reason": "被拦截"},
        ]
        out = tmp_path / "unsent.xml"
        DanmakuXml.export_unsent(records, out)

        content = Path(out).read_text(encoding="utf-8")
        assert "失败原因: 网络错误 (共 2 条)" in content
        assert "失败原因: 被拦截 (共 1 条)" in content

        reparsed = DanmakuXml.parse_file(out)
        assert sorted(d.msg for d in reparsed) == ["a", "b", "c"]
