import logging
import xml.etree.ElementTree as ET

from danmaku_sender.types.models.danmaku import Danmaku


class DanmakuParser:
    """
    Bilibili 弹幕解析器

    用于解析Bilibili XML格式的弹幕数据，支持本地文件和在线内容的解析。
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse_xml_file(self, xml_path: str) -> list[Danmaku]:
        """
        从本地 XML 文件读取并解析弹幕。

        Args:
            xml_path: XML 文件路径

        Returns:
            解析成功的 Danmaku 对象列表。若文件不存在或解析失败则返回空列表。
        """
        try:
            with open(xml_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.logger.debug(f"已成功加载 XML 文件: {xml_path}")
            return self.parse_xml_content(content)

        except FileNotFoundError:
            self.logger.error(f"弹幕文件不存在: {xml_path}")
            raise

        except Exception as e:
            self.logger.error(f"文件读取失败: {xml_path}, error: {e}", exc_info=True)
            raise

    def parse_xml_content(self, xml_content: str) -> list[Danmaku]:
        """
        解析Bilibili的XML弹幕内容字符串，返回一个 Danmaku 对象列表。

        Args:
            xml_content (str): XML弹幕内容的字符串。

        Returns:
            list[Danmaku]: Danmaku 对象列表
        """
        if not xml_content or not xml_content.strip():
            self.logger.warning("接收到的 XML 内容为空")
            return []

        results = []
        for node in self._iter_nodes(xml_content):
            if dm := self._parse_node(node):
                results.append(dm)

        return results

    def parse_online_dmids(self, xml_content: str) -> list[str]:
        """解析在线弹幕 XML，只提取服务器身份 dmid（核销用）。

        在线数据的身份字段不进 Danmaku；载荷解析走 parse_xml_content。
        """
        if not xml_content or not xml_content.strip():
            return []

        dmids: list[str] = []
        for node in self._iter_nodes(xml_content):
            p_attr = node.get('p', '').split(',')
            if dmid := Danmaku.dmid_from_xml(p_attr):
                dmids.append(dmid)
        return dmids

    def _iter_nodes(self, xml_content: str):
        """解析 XML 并产出 <d> 节点"""
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            self.logger.error(f"XML 结构解析失败: {e}")
            raise ValueError(f"XML 结构解析失败: {e}") from e
        return root.findall('d')

    def _parse_node(self, node: ET.Element) -> Danmaku | None:
        """解析单个节点"""
        text = node.text
        p_attr = node.get('p', '').split(',')

        # 过滤空弹幕
        if not text or not text.strip():
            return

        # 检查属性完整性
        if len(p_attr) < 1:
            self.logger.warning(f"弹幕属性丢失，跳过此条: {p_attr}")
            return

        try:
            return Danmaku.from_xml(p_attr, text.strip())
        except Exception as e:
            self.logger.warning(
                "单条弹幕解析失败: %s | text=%r, p_attr=%r",
                e, text.strip(), node.get('p', ',')
            )
            return