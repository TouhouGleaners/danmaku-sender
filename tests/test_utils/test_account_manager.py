"""account_manager 单元测试 — 多账号存储"""
import json
import pytest
from pathlib import Path

from danmaku_sender.core.models.account import AccountCredential
from danmaku_sender.utils import account_manager


@pytest.fixture
def accounts_file(tmp_path: Path, monkeypatch):
    """将 accounts.json 路径重定向到临时目录"""
    fake_path = tmp_path / "accounts.json"
    monkeypatch.setattr(account_manager, "get_accounts_filepath", lambda: fake_path)
    return fake_path


@pytest.fixture
def mock_fernet(monkeypatch):
    """mock 掉 _get_encryption_key，使用临时 Fernet 密钥"""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    fernet = Fernet(key)
    monkeypatch.setattr(
        "danmaku_sender.utils.account_manager._get_encryption_key",
        lambda: key
    )
    return fernet


class TestAccountCredential:
    """AccountCredential 模型"""

    def test_create_minimal(self):
        acc = AccountCredential(sessdata="abc", bili_jct="def")
        assert acc.sessdata == "abc"
        assert acc.bili_jct == "def"
        assert acc.uid == 0
        assert acc.name == ""

    def test_create_full(self):
        acc = AccountCredential(uid=123, name="测试用户", sessdata="a", bili_jct="b")
        assert acc.uid == 123
        assert acc.name == "测试用户"

    def test_model_dump_roundtrip(self):
        acc = AccountCredential(uid=456, name="用户B", sessdata="s", bili_jct="j")
        d = acc.model_dump()
        restored = AccountCredential.model_validate(d)
        assert restored == acc


class TestLoadAccounts:
    """load_accounts"""

    def test_no_file_returns_empty(self, accounts_file, mock_fernet):
        assert account_manager.load_accounts() == []

    def test_save_then_load_roundtrip(self, accounts_file, mock_fernet):
        original = [
            AccountCredential(uid=1, name="A", sessdata="s1", bili_jct="j1"),
            AccountCredential(uid=2, name="B", sessdata="s2", bili_jct="j2"),
        ]
        account_manager.save_accounts(original)
        loaded = account_manager.load_accounts()
        assert loaded == original

    def test_corrupted_file_returns_empty(self, accounts_file, mock_fernet):
        """InvalidToken 路径: 非 Fernet 数据"""
        accounts_file.write_bytes(b"not-valid-fernet-data")
        assert account_manager.load_accounts() == []
        assert not accounts_file.exists()  # 损坏文件应被删除

    def test_decrypted_garbage_returns_empty(self, accounts_file, mock_fernet):
        """JSONDecodeError 路径: 解密成功但内容不是合法 JSON"""
        fernet = mock_fernet
        accounts_file.write_bytes(fernet.encrypt(b"not-json"))
        assert account_manager.load_accounts() == []
        assert not accounts_file.exists()

    def test_non_list_json_returns_empty(self, accounts_file, mock_fernet):
        """如果加密内容是 dict 而非 list"""
        fernet = mock_fernet
        encrypted = fernet.encrypt(json.dumps({"bad": "data"}).encode())
        accounts_file.write_bytes(encrypted)
        assert account_manager.load_accounts() == []
        assert not accounts_file.exists()

    def test_malformed_entry_skipped(self, accounts_file, mock_fernet):
        """列表中混入格式异常的条目应被跳过"""
        fernet = mock_fernet
        data = [
            {"sessdata": "ok", "bili_jct": "ok"},              # 合法
            {"bad_field": True},                                 # 缺少必填字段
            {"sessdata": "ok2", "bili_jct": "ok2", "uid": 3},   # 合法
        ]
        encrypted = fernet.encrypt(json.dumps(data).encode())
        accounts_file.write_bytes(encrypted)
        loaded = account_manager.load_accounts()
        assert len(loaded) == 2


class TestSaveAccounts:
    """save_accounts"""

    def test_empty_list_deletes_file(self, accounts_file, mock_fernet):
        accounts_file.write_bytes(b"dummy")
        account_manager.save_accounts([])
        assert not accounts_file.exists()

    def test_empty_list_no_file_no_error(self, accounts_file, mock_fernet):
        account_manager.save_accounts([])

    def test_save_creates_encrypted_file(self, accounts_file, mock_fernet):
        accounts = [AccountCredential(sessdata="s", bili_jct="j")]
        account_manager.save_accounts(accounts)
        assert accounts_file.exists()
        # 文件内容不应是明文
        raw = accounts_file.read_bytes()
        assert b"sessdata" not in raw
