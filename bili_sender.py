import time
import random
import requests
import xml.etree.ElementTree as ET
import logging
from threading import Event
from requests.exceptions import Timeout, ConnectionError, RequestException

from wbi_signer import WbiSigner
from bili_danmaku_utils import BiliDmErrorCode, DanmakuSendResult, DanmakuParser


class BiliDanmakuSender:
    """B站弹幕发送器"""
    def __init__(self, sessdata: str, bili_jct: str, bvid: str):
        if not all([sessdata, bili_jct, bvid]):
            raise ValueError("错误: SESSDATA, BILI_JCT 和 BVID 不能为空")
        self.bvid = bvid
        self.bili_jct = bili_jct
        self.session = self._create_session(sessdata, bili_jct)
        self.danmaku_parser = DanmakuParser()
        self.logger = logging.getLogger(self.__class__.__name__)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
        self.wbi_keys = WbiSigner.get_wbi_keys()

    def _create_session(self, sessdata: str, bili_jct: str) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': f'https://www.bilibili.com/video/{self.bvid}'
        })
        session.cookies.update({
            'SESSDATA': sessdata,
            'bili_jct': bili_jct
        })

        return session
        
    def get_video_info(self) -> dict:
        """根据BVID获取视频详细信息，包括所有分P的CID和标题"""
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {'bvid': self.bvid}
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if data['code'] == 0:
                video_data = data['data']
                pages_info = [
                    {
                        'cid': p['cid'],
                        'page': p['page'],
                        'part': p['part']
                    }
                    for p in video_data.get('pages', [])
                ]

                info = {
                    'title': video_data.get('title', '未知标题'),
                    'pages': pages_info
                }
                
                self.logger.info(f"成功获取到视频《{info['title']}》的信息，共 {len(info['pages'])} 个分P")
                return info
            else:
                # 获取视频信息失败，尝试从错误枚举中查找或使用B站原始消息
                error_code = data.get('code', BiliDmErrorCode.GENERIC_FAILURE.code)
                raw_message = data.get('message', '未知错误')
                _, display_message = BiliDmErrorCode.resolve_bili_error(error_code, raw_message)
                self.logger.error(f"错误: 获取视频信息失败, Code: {error_code}, 信息: {display_message} (原始: {raw_message})")
                raise RuntimeError(f"错误: 获取视频信息失败, Code: {error_code}, 信息: {display_message} (原始: {raw_message})")
        except RequestException as req_e:
            self.logger.error(f"错误: 请求视频信息时发生网络异常: {req_e}", exc_info=True)
            raise RuntimeError(f"错误: 请求视频信息时发生网络异常: {req_e}") from req_e
        except Exception as e:
            self.logger.critical(f"错误: 请求视频信息时发生意外异常: {e}", exc_info=True)
            raise RuntimeError(f"错误: 请求视频信息时发生意外异常: {e}") from e
    
    def _handle_send_exception(self, danmaku: dict, e: Exception, error_code: BiliDmErrorCode) -> DanmakuSendResult:
        """
        处理发送弹幕时发生的各种异常，记录日志并返回统一的 DanmakuSendResult。
        """
        # 构建详细的日志消息
        log_message = f"❌ 发送异常! 内容: '{danmaku.get('msg', 'N/A')}', 错误: {error_code.description_str} ({e.__class__.__name__}: {e})"
        self.logger.error(log_message, exc_info=False)  # exc_info=False 用于避免已知异常类型的冗余堆栈跟踪

        return DanmakuSendResult(
            code=error_code.code,
            success=False,
            message=str(e),  # 原始异常字符串，用于raw_message
            display_message=error_code.description_str  # 用户友好的描述
        )

    def _send_single_danmaku(self, cid: int, danmaku: dict) -> DanmakuSendResult:
        """发送单条弹幕"""
        url = "https://api.bilibili.com/x/v2/dm/post"
        img_key, sub_key = self.wbi_keys

        base_params = {
            'type': '1',
            'oid': cid,
            'msg': danmaku['msg'],
            'bvid': self.bvid,
            'progress': danmaku['progress'],
            'mode': danmaku['mode'],
            'fontsize': danmaku['fontsize'],
            'color': danmaku['color'],
            'pool': '0',
            'rnd': int(time.time()),
            'csrf': self.bili_jct
        }

        signed_params = WbiSigner.enc_wbi(params=base_params, img_key=img_key, sub_key=sub_key)

        try:
            response = self.session.post(url, data=signed_params)
            response.raise_for_status()
            result_json = response.json()

            # 从B站API响应中获取错误码和原始消息
            code = result_json.get('code', BiliDmErrorCode.GENERIC_FAILURE.code) 
            raw_message = result_json.get('message', '无B站原始消息')

            # 尝试从枚举中获取友好提示
            _, display_msg = BiliDmErrorCode.resolve_bili_error(code, raw_message)

            if code == BiliDmErrorCode.SUCCESS.code:
                self.logger.info(f"✅ 成功发送: '{danmaku['msg']}'")
                return DanmakuSendResult(code=code, success=True, message=raw_message, display_message=BiliDmErrorCode.SUCCESS.description_str)
            else:
                # 特殊处理发送频率过快的错误
                if code == BiliDmErrorCode.FREQ_LIMIT.code:
                    self.logger.warning(f"检测到弹幕发送过于频繁 (Code: {code}: {display_msg})，将额外等待10秒...")
                    time.sleep(10)  # 内部处理等待，但仍返回失败结果
                self.logger.warning(f"发送失败 (API响应)! 内容: '{danmaku['msg']}', Code: {code}, 消息: {display_msg} (原始: {raw_message})")
                return DanmakuSendResult(code=code, success=False, message=raw_message, display_message=display_msg)
        except Timeout as e:
            return self._handle_send_exception(danmaku, e, BiliDmErrorCode.TIMEOUT_ERROR)
        except ConnectionError as e:
            return self._handle_send_exception(danmaku, e, BiliDmErrorCode.CONNECTION_ERROR)
        except RequestException as e:
            return self._handle_send_exception(danmaku, e, BiliDmErrorCode.NETWORK_ERROR)
        except Exception as e:
            return self._handle_send_exception(danmaku, e, BiliDmErrorCode.UNKNOWN_ERROR)

    def _process_single_danmaku(self, cid: int, dm: dict, total: int, i: int, stop_event: Event) -> tuple[bool, bool]:
        """
        处理单条弹幕的发送逻辑，包括日志、发送请求和致命错误判断。
        返回 (是否成功发送, 是否遇到致命错误)
        """
        if stop_event.is_set():
            self.logger.info("任务被用户手动停止。")
            return False, True # 停止即视为遇到致命错误，中断循环
        
        self.logger.info(f"[{i+1}/{total}] 准备发送: {dm.get('msg', 'N/A')}")
        result = self._send_single_danmaku(cid, dm)
        self.logger.info(str(result))  # 打印发送结果

        if not result.success:
            error_enum = BiliDmErrorCode.from_code(result.code)
            if error_enum is None:
                # 如果是未知的错误码，将其统一视为 UNKNOWN_ERROR，它本身就是致命的
                error_enum = BiliDmErrorCode.UNKNOWN_ERROR
                self.logger.warning(f"⚠️ 遇到未识别错误码 (Code: {result.code})，将其视为未知致命错误。消息: '{result.display_message}'")
            if error_enum.is_fatal_error:
                self.logger.critical(f"❌ 遭遇致命错误 (Code: {result.code}: {result.display_message})，任务将中断。")
                return False, True  # 遇到致命错误
            return False, False  # 失败但不是致命错误
        return True, False  # 成功发送

    def _handle_delay_and_stop(self, min_delay: float, max_delay: float, stop_event: Event) -> bool:
        """
        处理发送间隔等待和停止事件。
        返回是否需要中断任务（True表示需要中断，False表示继续）。
        """
        if stop_event.is_set():
            self.logger.info("任务被用户手动停止。")
            return True  # 需要中断任务

        delay = random.uniform(min_delay, max_delay)
        self.logger.info(f"等待 {delay:.2f} 秒...")
        if stop_event.wait(timeout=delay):
            self.logger.info("在等待期间接收到停止信号，立即终止。")
            return True  # 需要中断任务
        return False  # 不需要中断，继续任务

    def _log_send_summary(self, total: int, attempted_count: int, success_count: int, stop_event: Event, fatal_error_occurred: bool):
        """记录弹幕发送任务的总结信息。"""
        self.logger.info("--- 发送任务结束 ---")
        if stop_event.is_set():
            self.logger.info("原因：任务被用户手动停止。")
        elif fatal_error_occurred:
            self.logger.critical("原因：任务因致命错误中断。请检查配置或网络！")
        elif total == 0:
            self.logger.info("原因：没有弹幕可发送。")
        else:
            self.logger.info("原因：所有弹幕已发送完毕。")
        self.logger.info(f"弹幕总数: {total} 条")
        self.logger.info(f"尝试发送: {attempted_count} 条")
        self.logger.info(f"发送成功: {success_count} 条")
        self.logger.info(f"发送失败: {attempted_count - success_count} 条")

    def send_danmaku_from_xml(self, cid: int, xml_path: str, min_delay: float, max_delay: float, stop_event: Event):
        """从XML文件中读取弹幕并发送至指定的CID，并响应停止事件"""
        self.logger.info(f"开始从 XML 文件 '{xml_path}' 发送弹幕到 CID: {cid}")
        danmakus = self.parse_danmaku_xml(xml_path)
        if not danmakus:
            self._log_send_summary(0, 0, 0, stop_event, False)  # 如果没有弹幕，也打印总结
            return
        
        total = len(danmakus)
        success_count = 0
        attempted_count = 0
        fatal_error_occurred = False

        for i, dm in enumerate(danmakus):
            # 核心检查：在每次循环开始时，检查是否需要停止
            if stop_event.is_set():
                self.logger.info("任务被用户手动停止。")
                break

            attempted_count += 1
            sent_successfully, is_fatal = self._process_single_danmaku(cid, dm, total, i, stop_event)

            if is_fatal:
                fatal_error_occurred = True
                break  # 遇到致命错误，中断任务

            if sent_successfully:
                success_count += 1

            # 再次检查，如果发送非常耗时，用户可能在此期间点击了停止
            if stop_event.is_set():
                self.logger.info("任务被用户手动停止。")
                break 

            if i < total - 1:  # 如果不是最后一条弹幕，则等待
                if self._handle_delay_and_stop(min_delay, max_delay, stop_event):
                    break

        # 任务结束，打印总结
        self._log_send_summary(total, attempted_count, success_count, stop_event, fatal_error_occurred)

    def send_danmaku_from_list(self, cid: int, danmakus: list, min_delay: float, max_delay: float, stop_event: Event):
        """从一个弹幕字典列表发送弹幕，并响应停止事件"""
        self.logger.info(f"开始从内存列表发送弹幕到 CID: {cid}")
        if not danmakus:
            self._log_send_summary(0, 0, 0, stop_event, False)
            return
        
        total = len(danmakus)
        success_count = 0
        attempted_count = 0
        fatal_error_occurred = False
        for i, dm in enumerate(danmakus):
            if stop_event.is_set():
                self.logger.info("任务被用户手动停止。")
                break
            attempted_count += 1
            sent_successfully, is_fatal = self._process_single_danmaku(cid, dm, total, i, stop_event)
            if is_fatal:
                fatal_error_occurred = True
                break
            if sent_successfully:
                success_count += 1
            
            if stop_event.is_set():
                self.logger.info("任务被用户手动停止。")
                break
            if i < total - 1:
                if self._handle_delay_and_stop(min_delay, max_delay, stop_event):
                    break
        self._log_send_summary(total, attempted_count, success_count, stop_event, fatal_error_occurred)

    def parse_danmaku_xml(self, xml_path: str) -> list:
        """解析XML文件"""
        danmakus = []
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()

            # 寻找根节点下所有 <d> 标签
            for d_tag in root.findall('d'):
                try:
                    # 获取 p 属性并用逗号分割成列表
                    p_attr = d_tag.attrib['p'].split(',')
                    text = d_tag.text
                    # 检查弹幕是否为空或只包含空白字符
                    if not text or not text.strip():
                        self.logger.warning(f"⚠️ 警告: 检测到空弹幕或纯空白弹幕，跳过此条. XML内容片段: '{ET.tostring(d_tag, encoding='unicode').strip()}'")
                        continue
                    
                    # 从 p_attr 提取所需的参数
                    # 确保在访问索引前p_attr有足够的元素
                    if len(p_attr) < 4:
                        self.logger.warning(f"⚠️ 警告: 弹幕属性'p'不完整，跳过此条. 内容: '{text}', 属性: '{d_tag.attrib['p']}'")
                        continue

                    danmaku = {
                        'progress': int(float(p_attr[0]) * 1000),
                        'mode': int(p_attr[1]),
                        'fontsize': int(p_attr[2]),
                        'color': int(p_attr[3]),
                        'msg': text.strip()
                    }
                    danmakus.append(danmaku)
                except (IndexError, ValueError) as e:
                    self.logger.warning(f"⚠️ 警告: 解析弹幕失败, 跳过此条. 内容: '{d_tag.text}', 错误: {e}")
                except Exception as e:
                    self.logger.error(f"❌ 错误: 解析单个弹幕时发生意外异常, 跳过此条. 内容: '{d_tag.text}', 错误: {e}", exc_info=True)
            self.logger.info(f'📦 成功从 {xml_path} 解析出 {len(danmakus)} 条弹幕')
            return danmakus
        except FileNotFoundError:
            self.logger.error(f"❌ 错误: 文件 '{xml_path}' 不存在")
            return []
        except ET.ParseError as e:
            self.logger.error(f"❌ 错误: 解析XML文件 '{xml_path}' 时发生错误: {e}", exc_info=True)
            return []
        except Exception as e:
            self.logger.critical(f"❌ 错误: 解析XML文件 '{xml_path}' 时发生意外异常: {e}", exc_info=True)
            return []
        
    def get_online_danmaku_list(self, cid: int) -> list:
        """获取指定CID的线上实时弹幕列表。
        
        Args:
            cid: 目标视频分P的CID。
        Returns:
            一个包含弹幕字典的列表，例如 [{'progress': 12345, 'msg': '弹幕内容'}]。
            如果失败则返回空列表。
        """
        url = f"https://api.bilibili.com/x/v1/dm/list.so?oid={cid}"
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            return self.danmaku_parser.parse_xml_content(response.text, is_online_data=True)
        except RequestException as e:
            self.logger.error(f"获取CID {cid} 的在线弹幕列表时发生网络错误: {e}")
            return []
        except Exception as e:
            self.logger.error(f"获取或解析在线弹幕时发生未知错误: {e}")
            return []