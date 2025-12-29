import uuid
import logging
import xml.etree.ElementTree as ET
from enum import Enum
from xml.dom import minidom

from ..api.bili_api_client import BiliApiException


logger = logging.getLogger("BiliUtils")

class BiliDmErrorCode(Enum):
    """
    Bilibili弹幕发送错误码及其默认描述
    定义格式: (code, description, is_fatal)
    """
    # 成功
    SUCCESS = (0, "弹幕发送成功。", False)
    # B站API返回的错误码
    UNAUTHORIZED = (-101, "账号未登录或登录态失效！请检查SESSDATA和bili_jct。", True)
    ACCOUNT_BANNED = (-102, "账号被封停。", True)
    CSRF_FAILED = (-111, "CSRF 校验失败 (bili_jct 可能失效)，请检查登录凭证或尝试重新获取。", True)
    REQUEST_ERROR = (-400, "请求错误，参数不合法。", False)
    NOT_FOUND = (-404, "请求资源不存在。", True)
    
    SYSTEM_UPGRADING = (36700, "系统升级中，暂无法发送弹幕。", True)
    CONTENT_FORBIDDEN = (36701, "弹幕包含被禁止的内容，请修改后重试。", False)
    DANMAKU_TOO_LONG = (36702, "弹幕长度大于100字，请精简。", False)
    FREQ_LIMIT = (36703, "发送频率过快，请降低发送速度或稍后再试。", False)
    VIDEO_NOT_REVIEWED = (36704, "禁止向未审核的视频发送弹幕。", True)
    LEVEL_INSUFFICIENT_GENERAL = (36705, "您的等级不足，不能发送弹幕。", True)
    LEVEL_INSUFFICIENT_TOP = (36706, "您的等级不足，不能发送顶端弹幕。", False)
    LEVEL_INSUFFICIENT_BOTTOM = (36707, "您的等级不足，不能发送底端弹幕。", False)
    LEVEL_INSUFFICIENT_COLOR = (36708, "您的等级不足，不能发送彩色弹幕。", False)
    LEVEL_INSUFFICIENT_ADVANCED = (36709, "您的等级不足，不能发送高级弹幕。", False)
    PERMISSION_INSUFFICIENT_STYLE = (36710, "您的权限不足，不能发送这种样式的弹幕。", False)
    VIDEO_DANMAKU_FORBIDDEN = (36711, "该视频禁止发送弹幕，无法发送。", True)
    LENGTH_LIMIT_LEVEL1 = (36712, "Level 1用户发送弹幕的最大长度为20字。", False)
    VIDEO_NOT_PAID = (36713, "此稿件未付费，暂时无法发送弹幕。", True)
    INVALID_PROGRESS = (36714, "弹幕发送时间（progress）不合法。", False)
    DAILY_LIMIT_EXCEEDED = (36715, "当日操作数量超过上限。", False)
    NOT_PREMIUM_MEMBER = (36718, "目前您不是大会员，无法使用会员权益。", False)
    # 自定义错误码
    NETWORK_ERROR = (-9999, "发送弹幕时发生网络或请求异常。请检查您的网络连接。", True)
    UNKNOWN_ERROR = (-9998, "发送弹幕时发生未知异常，请联系开发者或稍后再试。", True)
    TIMEOUT_ERROR = (-9997, "发送弹幕请求超时，请检查网络或稍后再试。", True)
    CONNECTION_ERROR = (-9996, "发送弹幕时网络连接异常，请检查网络或稍后再试。", True)
    GENERIC_FAILURE = (-1, "操作失败，详见原始消息或尝试稍后再试。", False)  # 当B站返回code是-1或未识别的code时使用

    @property
    def code(self):
        """返回错误码的数值"""
        return self.value[0]

    @property
    def description_str(self):
        """返回错误码的描述"""
        return self.value[1]
    
    @property
    def is_fatal_error(self):
        """该错误是否是致命的（应中断任务）"""
        return self.value[2]
    
    @classmethod
    def from_code(cls, code: int) -> 'BiliDmErrorCode':
        """通过数字错误码反向查找对应的枚举成员"""
        return next((member for member in cls if member.code == code), None)
    
    @staticmethod
    def resolve_bili_error(code: int, raw_message: str) -> tuple[int, str]:
        """根据B站返回的code和原始信息，解析出最终的code和用于显示的友好消息"""
        enum_member = BiliDmErrorCode.from_code(code)
        if enum_member:
            return code, enum_member.description_str
        else:
            display_msg = raw_message or BiliDmErrorCode.GENERIC_FAILURE.description_str
            return code, display_msg
        
    @classmethod
    def from_api_exception(cls, e: 'BiliApiException') -> 'BiliDmErrorCode':
        """根据 BiliApiException 转换到合适的 BiliDmErrorCode"""
        if not e.is_network_error:
            # 如果不是网络错误，可能是一个未处理的API错误，返回通用失败
            return cls.GENERIC_FAILURE
        
        # -999 连接超时/错误
        if e.code == -999:
            return cls.CONNECTION_ERROR
        # -998 通用请求错误
        elif e.code == -998:
            return cls.NETWORK_ERROR
        # ...可以扩展其他网络错误码的映射
        else:
            return cls.NETWORK_ERROR # 默认返回通用网络错误
        

class DanmakuSendResult:
    """封装弹幕发送结果"""
    def __init__(self, code: int, success: bool, message: str, display_message: str = ""):
        self.code = code
        self.success = success
        self.raw_message = message if message else "无原始错误信息"  # B站返回的原始信息
        self.display_message = display_message if display_message else self.raw_message  # 用于显示给用户的信息

    def __str__(self):
        status = "成功" if self.success else "失败"
        if self.code == BiliDmErrorCode.SUCCESS.code:
            return f"[发送结果: {status}] {self.display_message}"
        else:
            return f"[发送结果: {status}] Code: {self.code}, 消息: \"{self.display_message}\" (原始: \"{self.raw_message}\")"


class DanmakuParser:
    """
    一个专门用于解析Bilibili弹幕XML内容，并返回标准化弹幕字典列表的类。
    唯一的弹幕解析来源，确保解析逻辑的一致性。
    """
    def __init__(self):
        # 获取一个独立的logger实例，用于该解析器类的日志
        self.logger = logging.getLogger("DanmakuParser")

    def parse_xml_content(self, xml_content: str, is_online_data: bool = False) -> list:
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

                    progress = int(float(p_attr[0]) * 1000)  # 转为毫秒
                    msg = text.strip()
                    danmaku = {
                        'progress': progress,
                        'msg': msg
                    }

                    if is_online_data:
                        if len(p_attr) > 7:
                            danmaku['id'] = p_attr[7]  # 在线弹幕的唯一ID
                        else:
                            danmaku['id'] = str(uuid.uuid4())  # 生成一个伪ID
                    else:
                        if len(p_attr) >= 4:
                            danmaku['mode'] = int(p_attr[1])
                            danmaku['fontsize'] = int(p_attr[2])
                            danmaku['color'] = int(p_attr[3])
                        else:
                            danmaku['mode'] = 1             # 默认值
                            danmaku['fontsize'] = 25        # 默认值
                            danmaku['color'] = 16777215     # 默认白色(#FFFFFF)

                    danmakus.append(danmaku)
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

def validate_danmaku_list(danmaku_list: list, video_duration_ms: int = -1) -> list:
    """
    校验弹幕列表，找出不符合B站发送规则的弹幕。
    Args:
        danmaku_list (list): 待校验的弹幕字典列表。添加'is_valid'键以标记是否有效。
        video_duration_ms (int): 视频总时长（毫秒）。如果为-1，则不检查时间戳是否超限。
    Returns:
        list: 一个包含问题弹幕信息的字典列表，每个字典包含：
              {'original_index': 原始索引, 'danmaku': 弹幕本身, 'reason': '问题描述'}
    """
    problems = []
    for i, dm in enumerate(danmaku_list):
        msg = dm.get('msg', '')
        progress = dm.get('progress', 0)
        
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
            dm['is_valid'] = False
            problems.append({
                'original_index': i,
                'danmaku': dm,
                'reason': ", ".join(reasons)
            })
        else:
            dm['is_valid'] = True
    
    return problems

def create_xml_from_danmakus(danmakus: list[dict], filepath: str) -> None:
    """
    将弹幕字典列表转换为B站XML格式并保存到文件。
    期望输入: [{'dm': dict, 'reason': str}, ...]
    """
    root = ET.Element('i')
    root.append(ET.Comment(' Generated by BiliDanmakuSender '))

    grouped_data: dict[str, list[dict]] = {}
    for item in danmakus:
        reason = str(item.get('reason', '未归类'))
        if reason not in grouped_data:
            grouped_data[reason] = []
        grouped_data[reason].append(item['dm'])

    # 写入 XML
    for reason, dms in grouped_data.items():
        root.append(ET.Comment(f' === 失败原因: {reason} (共 {len(dms)} 条) === '))
        
        # 组内按视频时间排序，方便用户后续查看/修改
        dms.sort(key=lambda x: x.get('progress', 0))
        
        for dm in dms:
            progress = dm.get('progress', 0)
            mode = dm.get('mode', 1)
            fontsize = dm.get('fontsize', 25)
            color = dm.get('color', 16777215)
            msg = dm.get('msg', '')

            p_attr = f"{progress/1000},{mode},{fontsize},{color},0,0,0,0,0"
            d_tag = ET.SubElement(root, 'd', {'p': p_attr})
            d_tag.text = msg

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