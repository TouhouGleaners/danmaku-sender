"""AccountManager 单元测试 — 多账号加密存储"""
import json
import pytest
from cryptography.fernet import Fernet

from danmaku_sender.runtime.managers import account_manager
from danmaku_sender.runtime.managers.account_manager import AccountManager
from danmaku_sender.types.models.account import AccountCredential


@pytest.fixture
def accounts_path(tmp_path, monkeypatch):
    """将 ACCOUNTS_PATH 重定向到临时目录"""
    fake = tmp_path / "accounts.json"
    monkeypatch.setattr(account_manager, "ACCOUNTS_PATH", fake)
    return fake


class FakeKeyring:
    """内存版密钥环，可注入失败"""

    def __init__(self):
        self.store = {}
        self.fail_get = False
        self.fail_set = False

    def get_password(self, service, username):
        if self.fail_get:
            raise RuntimeError("密钥环读取失败")
        return self.store.get(username)

    def set_password(self, service, username, value):
        if self.fail_set:
            raise RuntimeError("密钥环写入失败")
        self.store[username] = value


@pytest.fixture
def keyring_fake(monkeypatch):
    kr = FakeKeyring()
    monkeypatch.setattr(account_manager, "keyring", kr)
    return kr


@pytest.fixture
def manager():
    return AccountManager()


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

    def test_no_file_returns_empty(self, accounts_path, keyring_fake, manager):
        assert manager.load_accounts() == []

    def test_save_then_load_roundtrip(self, accounts_path, keyring_fake, manager):
        original = [
            AccountCredential(uid=1, name="A", sessdata="s1", bili_jct="j1"),
            AccountCredential(uid=2, name="B", sessdata="s2", bili_jct="j2"),
        ]
        manager.save_accounts(original)
        assert manager.load_accounts() == original

    def test_key_not_persisted_save_skips_write(self, accounts_path, keyring_fake, manager):
        """密钥环写入失败（persisted=False）时，跳过写盘以避免产生无法解密的文件"""
        keyring_fake.fail_set = True
        manager.save_accounts([AccountCredential(sessdata="s", bili_jct="j")])
        assert not accounts_path.exists()

    def test_wrong_key_keeps_file(self, accounts_path, keyring_fake, manager):
        """InvalidToken 路径：密钥不匹配时文件保留，修复密钥环后可恢复"""
        manager.save_accounts([AccountCredential(sessdata="s", bili_jct="j")])
        keyring_fake.store["default_user"] = Fernet.generate_key().decode()  # 换掉密钥
        assert manager.load_accounts() == []
        assert accounts_path.exists()  # 文件不删除

    def test_keyring_unavailable_skips_disk_write(self, accounts_path, keyring_fake, manager):
        """密钥环完全不可用时：密钥仅会话内有效，跳过写盘以避免产生无法解密的文件"""
        keyring_fake.fail_get = True
        keyring_fake.fail_set = True
        manager.save_accounts([AccountCredential(sessdata="s", bili_jct="j")])
        assert not accounts_path.exists()

    def test_corrupted_json_backed_up(self, accounts_path, keyring_fake, manager):
        """JSONDecodeError 路径：文件损坏时备份为 .corrupt"""
        key, _ = manager._get_encryption_key()
        accounts_path.write_bytes(Fernet(key).encrypt(b"not-json"))
        assert manager.load_accounts() == []
        assert not accounts_path.exists()
        assert accounts_path.with_suffix(".json.corrupt").exists()

    def test_non_list_json_backed_up(self, accounts_path, keyring_fake, manager):
        """如果加密内容是 dict 而非 list"""
        key, _ = manager._get_encryption_key()
        accounts_path.write_bytes(Fernet(key).encrypt(json.dumps({"bad": "data"}).encode()))
        assert manager.load_accounts() == []
        assert accounts_path.with_suffix(".json.corrupt").exists()

    def test_malformed_entry_skipped(self, accounts_path, keyring_fake, manager):
        """列表中混入格式异常的条目应被跳过"""
        key, _ = manager._get_encryption_key()
        fernet = Fernet(key)
        data = [
            {"sessdata": "ok", "bili_jct": "ok"},              # 合法
            {"sessdata": 123, "bili_jct": 456},                                 # 字段类型错误（pydantic v2 不做 int→str 协变）
            {"sessdata": "ok2", "bili_jct": "ok2", "uid": 3},   # 合法
        ]
        accounts_path.write_bytes(fernet.encrypt(json.dumps(data).encode()))
        assert len(manager.load_accounts()) == 2


class TestSaveAccounts:
    """save_accounts"""

    def test_empty_list_deletes_file(self, accounts_path, keyring_fake, manager):
        accounts_path.write_bytes(b"dummy")
        manager.save_accounts([])
        assert not accounts_path.exists()

    def test_empty_list_no_file_no_error(self, accounts_path, keyring_fake, manager):
        manager.save_accounts([])

    def test_save_creates_encrypted_file(self, accounts_path, keyring_fake, manager):
        accounts = [AccountCredential(sessdata="s", bili_jct="j")]
        manager.save_accounts(accounts)
        assert accounts_path.exists()
        # 文件内容不应是明文
        raw = accounts_path.read_bytes()
        assert b"sessdata" not in raw
        # 密钥应已持久化到密钥环
        assert "default_user" in keyring_fake.store
