import logging
import traceback
from typing import Callable

from PySide6.QtCore import QObject, Signal, QRunnable


logger = logging.getLogger("TaskRunner")


class WorkerSignals(QObject):
    """通用任务信号载体"""
    result = Signal(object)  # 携带任意类型的返回值
    error = Signal(str)      # 携带错误信息
    finished = Signal()      # 无论成功失败，最后都会触发


class GenericTask(QRunnable):
    """
    工业级通用线程池任务包装器

    将任何普通的、阻塞的 Python 函数，
    包装成一个可以在 QThreadPool 中安全运行的异步任务，并自动桥接信号。
    """
    # 静态注册表: 存放所有正在运行的任务，以防止被 GC
    _keep_alive_registry = set()

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

        self.setAutoDelete(False)  # 对象生命周期管理: C++ -> Python GC

        GenericTask._keep_alive_registry.add(self)

    def run(self):
        """线程池分配 OS 线程后自动调用的入口"""
        try:
            # 执行传入的业务函数
            result = self.fn(*self.args, **self.kwargs)
            # 将返回值通过信号扔回主线程
            self.signals.result.connect(lambda: None)  # 防御性空连接防报错
            self.signals.result.emit(result)
        except Exception as e:
            # 捕捉任何异常，打印完整堆栈，并把错误信息扔回主线程
            logger.error(f"后台任务执行异常: {e}\n{traceback.format_exc()}")
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()
            GenericTask._keep_alive_registry.discard(self)