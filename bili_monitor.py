import requests
import xml.etree.ElementTree as ET
from datetime import timedelta
import logging


class BiliDanmakuMonitor:
    """
    一个用于监视B站视频弹幕匹配情况的类。
    """
    def __init__(self, cid: int, local_xml_path: str, interval: int = 60, time_tolerance: int = 500):
        """
        初始化监视器。

        Args:
            cid (int): 目标视频分P的CID。
            local_xml_path (str): 本地弹幕XML文件的路径。
            interval (int, optional): 每次轮询的间隔时间（秒）。默认为 60。
            time_tolerance (int, optional): 本地弹幕与在线弹幕的时间容差（毫秒）。默认为 500。
        """
        self.cid = cid
        self.local_xml_path = local_xml_path
        self.interval = interval
        self.time_tolerance = time_tolerance
        self.logger = logging.getLogger("monitor_tab")
        
        self.local_danmaku = []
        self.matched_indices = set()
        self.total_danmaku = 0

    def _parse_danmu_time(self, xml_content: str):
        """解析XML字符串，返回 (视频时间ms, 文本) 的元组列表。"""
        danmus = []
        try:
            root = ET.fromstring(xml_content)
            for d in root.findall('d'):
                attrs = d.get('p', '').split(',')
                if len(attrs) >= 1: # 只需要时间戳
                    video_sec = float(attrs[0])
                    danmus.append((int(video_sec * 1000), d.text.strip() if d.text else ""))
            return danmus
        except ET.ParseError as e:
            self.logger.error(f"XML解析错误: {e}")
            return []

    def _read_local_danmu(self):
        """读取并解析本地弹幕文件。"""
        try:
            with open(self.local_xml_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.local_danmaku = self._parse_danmu_time(content)
            self.total_danmaku = len(self.local_danmaku)
            if self.total_danmaku > 0:
                self.logger.info(f"成功从'{self.local_xml_path}'解析出 {self.total_danmaku} 条本地弹幕。")
                return True
            else:
                self.logger.warning(f"未能从'{self.local_xml_path}'解析出任何弹幕。")
                return False
        except FileNotFoundError:
            self.logger.error(f"本地弹幕文件未找到: {self.local_xml_path}")
            return False
        except Exception as e:
            self.logger.error(f"读取本地文件时发生错误: {e}")
            return False

    def _fetch_online_danmaku(self):
        """获取在线弹幕列表。"""
        url = f"https://api.bilibili.com/x/v1/dm/list.so?oid={self.cid}"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            return self._parse_danmu_time(resp.content.decode('utf-8', 'ignore'))
        except requests.RequestException as e:
            self.logger.warning(f"获取在线弹幕失败: {e}")
            return None

    def _format_time(self, ms):
        """将毫秒格式化为 hh:mm:ss.ms 字符串。"""
        return str(timedelta(milliseconds=ms))[:-3]

    def run(self, stop_event, progress_callback):
        """
        启动监视循环任务。

        Args:
            stop_event (threading.Event): 用于外部控制停止的事件对象。
            progress_callback (function): 用于向GUI报告进度的回调函数。它应接受参数 (matched_count, total_count)。
        """
        if not self._read_local_danmu():
            return # 初始化失败则直接退出

        self.logger.info("弹幕监视器启动。")
        progress_callback(0, self.total_danmaku) # 初始化进度

        while not stop_event.is_set():
            online_danmaku = self._fetch_online_danmaku()
            if online_danmaku is None:
                self.logger.info(f"等待 {self.interval} 秒后重试...")
                stop_event.wait(self.interval)  # 等待时可被中断
                continue

            # 开始匹配
            temp_online = online_danmaku.copy()
            new_matches = []
            
            # 遍历所有未匹配的本地弹幕
            for i in range(self.total_danmaku):
                if i in self.matched_indices:
                    continue # 跳过已匹配的

                l_time, l_text = self.local_danmaku[i]
                
                # 在线弹幕中寻找匹配项
                for j, (o_time, o_text) in enumerate(temp_online):
                    if l_text == o_text and abs(l_time - o_time) <= self.time_tolerance:
                        new_matches.append((i, l_time, l_text))
                        self.matched_indices.add(i)
                        del temp_online[j] # 从本次轮询的在线列表中移除，避免重复匹配
                        break
            
            # 报告结果
            if new_matches:
                report = [f"→ 时间: {self._format_time(t)} | 内容: {txt}" for _, t, txt in new_matches]
                self.logger.info(f"本次轮询新增匹配 {len(new_matches)} 条:\n" + "\n".join(report))
            else:
                self.logger.info("本次轮询未发现新匹配。")
            
            # 更新进度
            progress_callback(len(self.matched_indices), self.total_danmaku)
            
            if len(self.matched_indices) == self.total_danmaku:
                self.logger.info("所有本地弹幕均已匹配成功！监视任务结束。")
                break

            self.logger.info(f"等待 {self.interval} 秒后进行下一次轮询...")
            stop_event.wait(self.interval) # 等待时可被中断

        if stop_event.is_set():
            self.logger.info("收到停止信号，监视任务已终止。")
        
        self.logger.info(f"最终匹配率: {len(self.matched_indices)} / {self.total_danmaku}")

