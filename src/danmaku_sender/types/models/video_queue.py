from danmaku_sender.runtime.state.video_state import VideoState
"""视频队列的运行时状态，封装成列表"""
class VideoQueue(list[VideoState]):
    def __init__(self):
        super().__init__()
        self.append(VideoState())  # 初始化时至少有一个视频状态对象
        self.current_index = 0
        self.active_item_index = 0 # 发射前正在编辑的活动视频索引

    @property
    def current_video(self) -> VideoState: #当前正在发射弹幕的视频
        if self.current_index >= 0 and self.current_index < len(self):
            return self[self.current_index]
        return VideoState()

    @property
    def active_video(self) -> VideoState: #发射前正在编辑的活动视频
        if self.active_item_index >= 0 and self.active_item_index < len(self):
            return self[self.active_item_index]
        return VideoState()

    def swap(self, index1: int, index2: int) -> None:
        if index1 == index2\
        or index1 < 0 or index1 >= len(self) or index2 < 0 or index2 >= len(self):
            return
        self[index1], self[index2] = self[index2], self[index1]

        # 更新 current_index
        if self.current_index == index1:
            self.current_index = index2
        elif self.current_index == index2:
            self.current_index = index1
        
        # 更新 active_item_index
        if self.active_item_index == index1:
            self.active_item_index = index2
        elif self.active_item_index == index2:
            self.active_item_index = index1

    def move_to(self, original_index: int, new_index: int) -> None:
            """将当前视频移动到指定索引"""
            if new_index < 0 or new_index >= len(self)\
            or original_index < 0 or original_index >= len(self):
                return
            
            elif original_index < new_index:
                # 向后移动
                for i in range(original_index, new_index):
                    self.swap(i, i + 1)
            elif original_index > new_index:
                # 向前移动
                for i in range(original_index, new_index, -1):
                    self.swap(i, i - 1)