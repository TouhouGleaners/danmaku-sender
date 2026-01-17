import logging
import threading
from datetime import timedelta

from .exceptions import BiliApiException

from .bili_danmaku_utils import DanmakuParser
from .models.danmaku import Danmaku

from ..api.bili_api_client import BiliApiClient


class BiliDanmakuMonitor:
    """
    一个用于监视B站视频弹幕匹配情况的类。
    """
    def __init__(self, api_client: BiliApiClient, cid: int,
                 source_danmaku_filepath: str = None, loaded_danmakus: list = None,
                 interval: int = 60, time_tolerance: int = 500):
        """
        初始化监视器。

        Args:
            cid (int): 目标视频分P的CID。
            source_danmaku_filepath (str, optional): 本地弹幕XML文件的路径，如果提供了loaded_danmakus，则可省略。
            loaded_danmakus (list, optional): 已预先解析好的本地弹幕列表。如果提供了此项，将优先使用。
                                              格式为：[{'progress': 12345, 'msg': '内容', ...}]
            interval (int, optional): 每次轮询的间隔时间（秒）。默认为 60。
            time_tolerance (int, optional): 本地弹幕与在线弹幕的时间容差（毫秒）。默认为 500。
        """
        self.api_client = api_client
        self.cid = cid
        self.interval = interval
        self.time_tolerance = time_tolerance
        self.danmaku_parser = DanmakuParser()
        self.logger = logging.getLogger("DanmakuMonitor")
        self.source_danmaku_filepath = source_danmaku_filepath
        self.loaded_danmakus: list[Danmaku] = loaded_danmakus if loaded_danmakus is not None else []  
        self.total_danmakus = len(self.loaded_danmakus)
        self.matched_local_indices = set()
        self.unique_matched_online_ids = set()

    def _read_local_danmakus(self) -> bool:
        """
        如果 loaded_danmakus 在初始化时未被提供或为空，则尝试从 source_danmaku_filepath 读取并解析。
        """
        # 如果初始化时已经有了弹幕数据，或者解析成功，则直接使用
        if self.total_danmakus > 0:
            self.logger.info(f"监视器已接收 {self.total_danmakus} 条预加载的本地弹幕。")
            return True
        
        # 如果 self.loaded_danmakus 为空，但提供了 xml 文件路径，则尝试解析
        if self.total_danmakus == 0 and self.source_danmaku_filepath:
            self.logger.info(f"尝试从 '{self.source_danmaku_filepath}' 读取本地弹幕。")
            try:
                self.loaded_danmakus = self.danmaku_parser.parse_xml_file(self.source_danmaku_filepath)
                self.total_danmakus = len(self.loaded_danmakus)
                if self.total_danmakus > 0:
                    self.logger.info(f"成功从'{self.source_danmaku_filepath}'解析出 {self.total_danmakus} 条本地弹幕。")
                    return True
                else:
                    self.logger.warning(f"未能从'{self.source_danmaku_filepath}'解析出任何弹幕。")
                    return True # 成功读取文件，只是文件为空
            except Exception as e:
                self.logger.error(f"读取或解析本地文件 '{self.source_danmaku_filepath}' 时发生错误: {e}")
                self.total_danmakus = 0
                self.loaded_danmakus = [] # 确保在出错后重置为列表
                return False
        
        # 如果 loaded_danmakus 为空，也没有提供 XML 文件路径
        if self.total_danmakus == 0:
            self.logger.warning("未提供本地弹幕数据（预加载列表或文件路径）。监视任务将继续，但不会有任何本地弹幕可匹配。")
            return True  # 视为成功处理了输入，只是没有弹幕可匹配
        
        return False  # 理论上不应该到达这里

    def _fetch_online_danmakus(self) -> list[Danmaku]:
        """获取在线弹幕列表"""
        try:
            xml_content = self.api_client.get_danmaku_list_xml(self.cid)
            return self.danmaku_parser.parse_xml_content(xml_content, is_online_data=True)
        except BiliApiException as e:
            self.logger.warning(f"获取在线弹幕失败: {e.message}")
            return []
        except Exception as e:
            self.logger.error(f"解析在线弹幕内容时发生错误: {e}")
            return []

    def _format_time(self, ms: int) -> str:
        """将毫秒格式化为 hh:mm:ss.ms 字符串。"""
        ms = int(ms) 
        return str(timedelta(milliseconds=ms))[:-3]

    def run(self, stop_event: threading.Event, progress_callback):
        """
        启动监视循环任务。

        Args:
            stop_event (threading.Event): 用于外部控制停止的事件对象。
            progress_callback (function): 用于向GUI报告进度的回调函数。它应接受参数 (matched_count, total_count)。
        """
        # 如果 _read_local_danmakus 返回 False，表示存在一个无法恢复的输入错误，任务中断
        if not self._read_local_danmakus() and not self.loaded_danmakus:
            self.logger.error("本地弹幕数据初始化失败，监视任务无法启动。")
            progress_callback(0, 0)  # 报告初始状态
            return

        self.logger.info("弹幕监视器启动。")
        progress_callback(len(self.matched_local_indices), self.total_danmakus)

        if self.total_danmakus == 0:
            self.logger.info("本地无弹幕可供监视，任务提前结束。")
            progress_callback(0, 0)  # 再次确保报告最终状态
            return

        while not stop_event.is_set():
            online_danmakus = self._fetch_online_danmakus()
            if not online_danmakus:
                self.logger.info(f"在线弹幕获取为空或失败，等待 {self.interval} 秒后重试...")
                stop_event.wait(self.interval)
                continue
            
            new_matches_this_round = []
            
            for i, local_dm in enumerate(self.loaded_danmakus):
                if i in self.matched_local_indices:
                    continue

                l_time, l_text = local_dm.progress, local_dm.msg
                
                for online_dm in online_danmakus:
                    o_time, o_text = online_dm.progress, online_dm.msg
                    o_id = online_dm.dmid

                    if (l_text == o_text and 
                        abs(l_time - o_time) <= self.time_tolerance and
                        (not o_id or o_id not in self.unique_matched_online_ids)):
                        
                        new_matches_this_round.append((i, l_time, l_text))
                        self.matched_local_indices.add(i)
                        
                        if o_id:
                            self.unique_matched_online_ids.add(o_id)
                        
                        break
            
            if new_matches_this_round:
                report = [f"→ 时间: {self._format_time(t)} | 内容: {txt}" for _, t, txt in new_matches_this_round]
                self.logger.info(f"本次轮询新增匹配 {len(new_matches_this_round)} 条 (总匹配: {len(self.matched_local_indices)}/{self.total_danmakus}):\n" + "\n".join(report))
            else:
                self.logger.info("本次轮询未发现新匹配。")
            
            progress_callback(len(self.matched_local_indices), self.total_danmakus)
            
            if len(self.matched_local_indices) == self.total_danmakus:
                self.logger.info("所有本地弹幕均已匹配成功！监视任务结束。")
                break
            
            self.logger.info(f"等待 {self.interval} 秒后进行下一次轮询...")
            stop_event.wait(self.interval)

        if stop_event.is_set():
            self.logger.info("收到停止信号，监视任务已终止。")
        
        self.logger.info(f"最终匹配率: {len(self.matched_local_indices)} / {self.total_danmakus}")