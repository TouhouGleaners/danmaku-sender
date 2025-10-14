import time
import random
import requests
import xml.etree.ElementTree as ET
from threading import Event

from wbi_signer import WbiSigner
from bili_danmaku_utils import BiliDmErrorCode, DanmakuSendResult


class BiliDanmakuSender:
    """B站弹幕发送器"""
    def __init__(self, sessdata: str, bili_jct: str, bvid: str):
        if not all([sessdata, bili_jct, bvid]):
            raise ValueError("错误: SESSDATA, BILI_JCT 和 BVID 不能为空")
        self.bvid = bvid
        self.bili_jct = bili_jct
        self.session = self._create_session(sessdata, bili_jct)
        self.wbi_keys = WbiSigner.get_wbi_keys()
        self.log = print  # 默认属性为print，在无GUI时也能运行

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
        url = "http://api.bilibili.com/x/web-interface/view"
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
                    for p in video_data['pages']
                ]

                info = {
                    'title': video_data['title'],
                    'pages': pages_info
                }
                
                self.log(f"成功获取到视频《{info['title']}》的信息，共 {len(info['pages'])} 个分P")
                return info
            else:
                # 获取视频信息失败，尝试从错误枚举中查找或使用B站原始消息
                error_code = data.get('code', BiliDmErrorCode.GENERIC_FAILURE.value)
                raw_message = data.get('message', '未知错误')
                _, display_message = BiliDmErrorCode.resolve_bili_error(error_code, raw_message)
                raise RuntimeError(f"错误: 获取视频信息失败, Code: {error_code}, 信息: {display_message} (原始: {raw_message})")
        except requests.exceptions.RequestException as req_e:
            raise RuntimeError(f"错误: 请求视频信息时发生网络异常: {req_e}")
        except Exception as e:
            raise RuntimeError(f"错误: 请求视频信息时发生异常: {e}")
    
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

        singed_params = WbiSigner.enc_wbi(params=base_params, img_key=img_key, sub_key=sub_key)

        try:
            response = self.session.post(url, data=singed_params)
            response.raise_for_status()
            result_json = response.json()

            # 从B站API响应中获取错误码和原始消息
            code = result_json.get('code', BiliDmErrorCode.GENERIC_FAILURE.value) 
            raw_message = result_json.get('message', '无B站原始消息')

            # 尝试从枚举中获取友好提示
            _, display_msg = BiliDmErrorCode.resolve_bili_error(code, raw_message)

            if code == BiliDmErrorCode.SUCCESS.value:
                return DanmakuSendResult(code=code, success=True, message=raw_message, display_message=BiliDmErrorCode.SUCCESS.description)
            else:
                # 特殊处理发送频率过快的错误
                if code == BiliDmErrorCode.FREQ_LIMIT.value:
                    self.log(f"检测到弹幕发送过于频繁 (Code: {code}: {display_msg})，将额外等待10秒...")
                    time.sleep(10)  # 内部处理等待，但仍返回失败结果
                return DanmakuSendResult(code=code, success=False, message=raw_message, display_message=display_msg)
        except requests.exceptions.RequestException as e:
            # 网络或请求异常，HTTP 状态码非 2xx 或网络连接问题
            error_msg = f"发送弹幕时发生网络或请求异常: {e}"
            self.log(f"❌ 发送异常! 内容: '{danmaku['msg']}', 错误: {error_msg}")
            return DanmakuSendResult(code=BiliDmErrorCode.NETWORK_ERROR.value, success=False, message=str(e), display_message=error_msg)
        except Exception as e:
            # 其他未知异常
            error_msg = f"发送弹幕时发生未知异常: {e}"
            self.log(f"❌ 发送异常! 内容: '{danmaku['msg']}', 错误: {error_msg}")
            return DanmakuSendResult(code=BiliDmErrorCode.UNKNOWN_ERROR.value, success=False, message=str(e), display_message=error_msg)
        
    def send_danmaku_from_xml(self, cid: int, xml_path: str, min_delay: float, max_delay: float, stop_event: Event):
        """从XML文件中读取弹幕并发送至指定的CID，并响应停止事件"""
        danmakus = self.parse_danmaku_xml(xml_path)
        if not danmakus:
            return
        
        total = len(danmakus)
        success_count = 0
        attempted_count = 0
        fatal_error_occurred = False

        for i, dm in enumerate(danmakus):
            # 核心检查：在每次循环开始时，检查是否需要停止
            if stop_event.is_set():
                self.log("任务被用户手动停止。")
                break

            attempted_count += 1
            self.log(f"[{i+1}/{total}] 准备发送: {dm['msg']}")
            result = self._send_single_danmaku(cid, dm)
            self.log(str(result))  # 打印发送结果

            if result.success:
                success_count += 1
            else:
                # 使用 is_fatal 属性判断
                error_enum = BiliDmErrorCode.from_code(result.code)
                if error_enum and error_enum.is_fatal:
                    self.log(f"❌ 遭遇致命错误 (Code: {result.code}: {result.display_message})，任务将中断。")
                    fatal_error_occurred = True
                    break

            # 再次检查，如果发送非常耗时，用户可能在此期间点击了停止
            if stop_event.is_set():
                self.log("任务被用户手动停止。")
                break 

            if i < total - 1:  # 如果不是最后一条弹幕，则等待
                delay = random.uniform(min_delay, max_delay)
                self.log(f"等待 {delay:.2f} 秒...")
                if stop_event.wait(timeout=delay):
                    self.log("在等待期间接收到停止信号，立即终止。")
                    break

        # 任务结束，打印总结
        self.log("\n--- 发送任务结束 ---")
        if stop_event.is_set():
            self.log("原因：任务被用户手动停止。")
        elif fatal_error_occurred:
            self.log("原因：任务因致命错误中断。请检查配置或网络！")
        elif total == 0:
            self.log("原因：没有弹幕可发送。")
        else:
            self.log("原因：所有弹幕已发送完毕。")

        self.log(f"弹幕总数: {total} 条")
        self.log(f"尝试发送: {attempted_count} 条")
        self.log(f"发送成功: {success_count} 条")
        self.log(f"发送失败: {attempted_count - success_count} 条")

    def parse_danmaku_xml(self,xml_path: str) -> list:
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
                    # 检查弹幕是否为空
                    if not text or not text.strip():
                        continue
                    
                    # 从 p_attr 提取所需的参数
                    danmaku = {
                        'progress': int(float(p_attr[0]) * 1000),
                        'mode': int(p_attr[1]),
                        'fontsize': int(p_attr[2]),
                        'color': int(p_attr[3]),
                        'msg': text.strip()
                    }
                    danmakus.append(danmaku)
                except (IndexError, ValueError) as e:
                    self.log(f"⚠️ 警告: 解析弹幕失败, 跳过此条. 内容: '{d_tag.text}', 错误: {e}")
            self.log(f'📦 成功从 {xml_path} 解析出 {len(danmakus)} 条弹幕')
            return danmakus
        except FileNotFoundError:
            self.log(f"❌ 错误: 文件 '{xml_path}' 不存在")
            return []
        except ET.ParseError as e:
            self.log(f"❌ 错误: 解析XML文件时发生错误: {e}")
            return []