"""平台相关服务 — Windows 桌面通知的派发与容错

win11toast 仅在 Windows 上安装，平台边界以替身注入，逻辑可在任意平台断言。
"""

from typing import ClassVar

import pytest

import danmaku_sender.runtime.infra.platform as platform_mod


class _RecordingToast:
    """记录 toast 调用参数的替身。"""

    def __init__(self, error: Exception | None = None):
        self.calls: list[dict] = []
        self._error = error

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error


class _RecordingThread:
    """不真正开线程，只记录构造参数。"""

    instances: ClassVar[list] = []

    def __init__(self, target=None, args=(), name=None, daemon=None):
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon
        self.started = False
        type(self).instances.append(self)

    def start(self):
        self.started = True

    @classmethod
    def reset(cls):
        cls.instances = []


@pytest.fixture
def recording_thread(monkeypatch):
    """拦截 threading.Thread，避免测试里出现真实线程。"""
    _RecordingThread.reset()
    monkeypatch.setattr(platform_mod.threading, "Thread", _RecordingThread)
    yield _RecordingThread
    _RecordingThread.reset()


@pytest.fixture
def windows_env(monkeypatch):
    """把平台边界换成可控替身：Windows 且 toast 可用。"""
    toast = _RecordingToast()
    monkeypatch.setattr(platform_mod, "IS_WINDOWS", True)
    monkeypatch.setattr(platform_mod, "toast", toast)
    return toast


class TestSendWindowsNotification:
    """通知的派发条件与线程承载"""

    def test_noop_when_toast_unavailable(self, monkeypatch, recording_thread):
        """依赖缺失时不建线程"""
        monkeypatch.setattr(platform_mod, "toast", None)
        platform_mod.send_windows_notification("标题", "内容")
        assert recording_thread.instances == []

    def test_noop_on_non_windows(self, monkeypatch, recording_thread):
        """非 Windows 平台不建线程"""
        monkeypatch.setattr(platform_mod, "IS_WINDOWS", False)
        monkeypatch.setattr(platform_mod, "toast", _RecordingToast())
        platform_mod.send_windows_notification("标题", "内容")
        assert recording_thread.instances == []

    def test_dispatches_on_daemon_thread(self, windows_env, recording_thread):
        platform_mod.send_windows_notification("标题", "内容")

        (thread,) = recording_thread.instances
        assert thread.started is True
        assert thread.daemon is True
        assert thread.name == "Notification"
        assert thread.target is platform_mod._send_notification_wrapper
        assert thread.args == ("标题", "内容")


class TestNotificationWrapper:
    """toast 调用参数与异常边界"""

    def test_forwards_arguments(self, windows_env):
        platform_mod._send_notification_wrapper("标题", "内容")

        assert windows_env.calls == [{
            "title": "标题",
            "body": "内容",
            "icon": platform_mod.ICON_PATH,
            "app_id": platform_mod.AppInfo.NAME,
        }]

    def test_swallows_toast_errors(self, monkeypatch, caplog):
        """通知失败只记日志，不得外泄到调用方"""
        monkeypatch.setattr(platform_mod, "toast", _RecordingToast(error=RuntimeError("boom")))
        with caplog.at_level("ERROR"):
            platform_mod._send_notification_wrapper("标题", "内容")
        assert any("发送通知" in record.message for record in caplog.records)
