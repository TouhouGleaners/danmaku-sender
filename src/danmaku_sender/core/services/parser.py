import logging
import xml.etree.ElementTree as ET

from ..models.danmaku import Danmaku


logger = logging.getLogger("BiliUtils")


class DanmakuParser:
    """
    解析Bilibili弹幕XML内容
    返回标准化弹幕字典列表的类。
    """
    def __init__(self):
        self.logger = logging.getLogger("DanmakuParser")

    def parse_xml_content(self, xml_content: str, is_online_data: bool = False) -> list[Danmaku]:
        """
        解析Bilibili的XML弹幕内容字符串，返回一个标准化的弹幕字典列表。
        
        Args:
            xml_content (str): XML弹幕内容的字符串。
            is_online_data (bool): 如果为True，表示解析的是在线实时弹幕数据，此时会尝试提取弹幕ID (p_attr[7])。
        
        Returns:
            list: 一个包含弹幕字典的列表，例如：
                  本地弹幕: [{'progress': 12345, 'msg': '内容', 'mode': 1, 'fontsize': 25, 'color': 16777215}]
                  在线弹幕: [{'progress': 12345, 'msg': '内容', 'id': '弹幕唯一ID'}] (mode, fontsize, color可以省略或给默认值)
        """
        danmakus = []
        try:
            root = ET.fromstring(xml_content)
            for d_tag in root.findall('d'):
                try:
                    p_attr_str = d_tag.get('p', '')
                    p_attr = p_attr_str.split(',')
                    text = d_tag.text

                    if not text or not text.strip():
                        self.logger.debug(f"ℹ️ 警告: 检测到空弹幕或纯空白弹幕，跳过此条. XML内容片段: '{ET.tostring(d_tag, encoding='unicode').strip()}'")
                        continue

                    if len(p_attr) < 1:
                        self.logger.warning(f"⚠️ 警告: 弹幕属性'p'不完整，跳过此条. 内容: '{text}', 属性: '{p_attr_str}'")
                        continue

                    msg = text.strip()
                    dm = Danmaku.from_xml(p_attr, msg, is_online_data)

                    danmakus.append(dm)
                except (ValueError, IndexError) as e:
                    self.logger.warning(f"⚠️ 警告: 解析单个弹幕失败, 跳过此条. 内容: '{d_tag.text}', 属性: '{p_attr_str}', 错误: {e}")
                except Exception as e:
                    self.logger.critical(f"❌ 错误: 解析单个弹幕时发生意外异常, 跳过此条. 内容: '{d_tag.text}', 属性: '{p_attr_str}', 错误: {e}", exc_info=True)
            return danmakus
        except ET.ParseError as e:
            self.logger.error(f"❌ 错误: 解析XML内容时发生错误: {e}", exc_info=True)
            return []
        except Exception as e:
            self.logger.critical(f"❌ 错误: 解析XML内容时发生意外异常: {e}", exc_info=True)
            return []
        
    def parse_xml_file(self, xml_path: str) -> list:
        """从XML文件读取内容并解析，返回一个标准化的弹幕字典列表。"""
        try:
            with open(xml_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.logger.info(f'📦 成功从 {xml_path} 读取内容。') 
            return self.parse_xml_content(content, is_online_data=False)
        except FileNotFoundError:
            self.logger.error(f"❌ 错误: 弹幕文件 '{xml_path}' 不存在。")
            return []
        except Exception as e:
            self.logger.critical(f"❌ 错误: 读取或解析本地弹幕文件 '{xml_path}' 时发生意外异常: {e}", exc_info=True)
            return []