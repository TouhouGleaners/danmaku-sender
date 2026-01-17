import logging
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import TypedDict

from .models.danmaku import Danmaku


logger = logging.getLogger("BiliUtils")

class UnsentDanmakusRecord(TypedDict):
    dm: Danmaku
    reason: str


class ValidationIssue(TypedDict):
    original_index: int
    danmaku: Danmaku
    reason: str


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


def format_ms_to_hhmmss(ms: int) -> str:
    """将毫秒格式化为 HH:MM:SS / MM:SS 字符串。"""
    if not isinstance(ms, (int, float)) or ms < 0:
        return "-:--:--"
    
    total_seconds = int(ms // 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"

FORBIDDEN_SYMBOLS = "☢⚠☣☠⚡💣⚔🔥"

def validate_danmaku_list(danmaku_list: list[Danmaku], video_duration_ms: int = -1) -> list[ValidationIssue]:
    """
    校验弹幕列表，找出不符合B站发送规则的弹幕。
    Args:
        danmaku_list (list): 待校验的弹幕字典列表。添加'is_valid'键以标记是否有效。
        video_duration_ms (int): 视频总时长（毫秒）。如果为-1，则不检查时间戳是否超限。
    Returns:
        list: 一个包含问题弹幕信息的字典列表，每个字典包含：
              {'original_index': 原始索引, 'danmaku': 弹幕本身, 'reason': '问题描述'}
    """
    problems: list[ValidationIssue] = []
    for i, dm in enumerate(danmaku_list):
        msg = dm.msg
        progress = dm.progress
        
        reasons = []

        # 换行符检查
        if '\\n' in msg or '/n' in msg:
            reasons.append('内容包含换行符')

        # 长度检查
        if len(msg) > 100:
            reasons.append('内容超过100个字符')

        # 时间戳检查
        if video_duration_ms > 0 and progress > video_duration_ms:
            reasons.append('时间戳超出视频总时长')

        # 特殊符号检查
        found_forbidden = [char for char in FORBIDDEN_SYMBOLS if char in msg]
        if found_forbidden:
            # 只报告第一个禁用符号，避免信息过长
            reasons.append(f"包含禁用符号'{found_forbidden[0]}'")
        
        # 问题汇总
        if reasons:
            dm.is_valid = False
            problems.append({
                'original_index': i,
                'danmaku': dm,
                'reason': ", ".join(reasons)
            })
        else:
            dm.is_valid = True
    
    return problems

def create_xml_from_danmakus(danmakus: list[UnsentDanmakusRecord], filepath: str) -> None:
    """
    将弹幕字典列表转换为B站XML格式并保存到文件。
    期望输入: [{'dm': dict, 'reason': str}, ...]
    """
    root = ET.Element('i')
    root.append(ET.Comment(' Generated by BiliDanmakuSender '))

    grouped_data: dict[str, list[Danmaku]] = {}
    for item in danmakus:
        reason = str(item.get('reason', '未归类'))
        if reason not in grouped_data:
            grouped_data[reason] = []
        grouped_data[reason].append(item['dm'])

    # 写入 XML
    for reason, dms in grouped_data.items():
        safe_reason = reason.replace('--', ' - ').strip('-')
        root.append(ET.Comment(f' === 失败原因: {safe_reason} (共 {len(dms)} 条) === '))
        
        # 组内按视频时间排序，方便用户后续查看/修改
        dms.sort(key=lambda x: x.progress)
        
        for dm in dms:
            p_attr = f"{dm.progress/1000},{dm.mode},{dm.fontsize},{dm.color},0,0,0,0,0"
            d_tag = ET.SubElement(root, 'd', {'p': p_attr})
            d_tag.text = dm.msg

    # 格式化并保存
    rough_string = ET.tostring(root, 'utf-8')
    reparsed_document = minidom.parseString(rough_string)
    pretty_xml = reparsed_document.toprettyxml(indent="  ", encoding="utf-8")
    try:
        with open(filepath, 'wb') as f:
            f.write(pretty_xml)
        logger.info(f"✅ 成功将 {len(danmakus)} 条弹幕及原因分类保存到 '{filepath}'。")
    except Exception as e:
        logger.error(f"❌ 保存未发送弹幕到XML文件失败: {e}", exc_info=True)