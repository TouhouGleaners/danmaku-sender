import logging
import xml.etree.ElementTree as ET

from ..models.danmaku import Danmaku


class DanmakuParser:
    """
    Bilibili 弹幕解析器

    用于解析Bilibili XML格式的弹幕数据，支持本地文件和在线内容的解析。
    """
    def __init__(self):
        self.logger = logging.getLogger("App.System.Parser")

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
            return self.parse_xml_content(content, is_online=False)

        except FileNotFoundError:
            self.logger.error(f"弹幕文件不存在: {xml_path}")
            return []

        except Exception as e:
            self.logger.error(f"文件读取失败: {xml_path}, error: {e}", exc_info=True)
            return []

    def parse_xml_content(self, xml_content: str, is_online: bool = False) -> list[Danmaku]:
        """
        解析Bilibili的XML弹幕内容字符串，返回一个 Danmaku 对象列表。

        Args:
            xml_content (str): XML弹幕内容的字符串。
            is_online (bool): 是否为在线实时数据 (为 True 时将尝试提取 dmid)。

        Returns:
            list[Danmaku]: Danmaku 对象列表
        """
        if not xml_content or not xml_content.strip():
            self.logger.warning("接收到的 XML 内容为空")
            return []

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            self.logger.error(f"XML 结构解析失败: {e}")
            return []

        results = []
        for node in root.findall('d'):
            if dm := self._parse_node(node, is_online):
                results.append(dm)

        return results

    def _parse_node(self, node: ET.Element, is_online: bool) -> Danmaku | None:
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
            return Danmaku.from_xml(p_attr, text.strip(), is_online)
        except Exception as e:
            self.logger.warning(f"单条弹幕解析失败: {e}")
            return