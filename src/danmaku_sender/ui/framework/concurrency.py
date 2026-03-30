import logging
import threading
import traceback
from typing import Callable
from abc import abstractmethod

from PySide6.QtCore import QThread, QObject, Signal, QRunnable, Slot


logger = logging.getLogger("App.System.Concurrency")


class BaseWorker(QThread):
    """
    所有长驻/重型 Worker 线程的抽象基类。

    提供了线程管理、信号定义和日志记录等通用功能。
    """
    _keep_alive_registry = set()       # 静态注册表: 存放所有正在运行的任务，以防止被 GC
    _registry_lock = threading.Lock()  # 注册表线程锁

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger("App.System.Worker.Base")
        self.finished.connect(self._unregister)  # 线程彻底结束时，将自己从保活注册表中移除

    def start(self, *args, **kwargs):
        """重写 start 方法，在启动时将自身加入保活注册表"""
        with BaseWorker._registry_lock:
            BaseWorker._keep_alive_registry.add(self)
        super().start(*args, **kwargs)

    @Slot()
    def _unregister(self):
        """线程安全退出后释放 Python 引用"""
        with BaseWorker._registry_lock:
            BaseWorker._keep_alive_registry.discard(self)
        self.logger.debug(f"{self.__class__.__name__} 已从全局存活注册表中移除。")

    @abstractmethod
    def run(self):
        """抽象方法: 子类必须重写此方法以实现具体的业务逻辑"""
        raise NotImplementedError(f"继承 BaseWorker 的子类 {self.__class__.__name__} 必须实现 run() 方法")

    def report_error(self, title: str, exception: Exception):
        """统一的异常捕获与上报接口"""
        self.logger.error(f"{title}: {exception}", exc_info=True)


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
            self.signals.result.emit(result)
        except Exception as e:
            # 捕捉任何异常，打印完整堆栈，并把错误信息扔回主线程
            logger.error(f"后台任务执行异常: {e}\n{traceback.format_exc()}")
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()
            GenericTask._keep_alive_registry.discard(self)