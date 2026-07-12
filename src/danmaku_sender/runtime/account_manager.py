import os
import json
import logging
import keyring
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from platformdirs import user_data_dir

from ..config.app_meta import AppInfo
from ..types.models.account import AccountCredential
from .app_state import AppState


KEYRING_SERVICE_NAME = f"{AppInfo.NAME_EN}-CredentialsKey"
KEYRING_USERNAME = "default_user"
ACCOUNTS_FILE_NAME = "accounts.json"

logger = logging.getLogger("App.System.Auth")


class AccountManager:
    """凭据管理器"""

    def _get_encryption_key(self) -> tuple[bytes, bool]:
        """
        从系统密钥环获取加密密钥。
        如果不存在，则生成一个新的密钥并存储。

        Returns:
            (key, persisted): 密钥字节，以及密钥是否已持久化到密钥环。
        """
        try:
            key_str = keyring.get_password(KEYRING_SERVICE_NAME, KEYRING_USERNAME)
        except Exception as e:
            logger.warning(f"密钥环读取失败: {e}，将生成新密钥。")
            key_str = None

        if key_str:
            logger.debug("已从系统密钥环获取加密密钥。")
            return key_str.encode('utf-8'), True

        new_key = Fernet.generate_key()
        try:
            keyring.set_password(KEYRING_SERVICE_NAME, KEYRING_USERNAME, new_key.decode('utf-8'))
            logger.info("已生成新的加密密钥并存储在系统密钥环中。")
            return new_key, True
        except Exception as e:
            logger.warning(f"密钥环写入失败: {e}，密钥仅在本次会话有效，跳过凭据持久化。")
            return new_key, False

    def get_accounts_filepath(self) -> Path:
        """获取账号存储文件的完整路径"""
        data_dir = Path(user_data_dir(AppInfo.NAME_EN, AppInfo.AUTHOR, ensure_exists=True))
        return data_dir / ACCOUNTS_FILE_NAME

    def load_accounts(self) -> list[AccountCredential]:
        """
        从加密的 accounts.json 加载账号列表。
        如果文件不存在或解密失败，返回空列表。
        """
        accounts_file = self.get_accounts_filepath()

        if not accounts_file.exists():
            return []

        try:
            key, _ = self._get_encryption_key()
            fernet = Fernet(key)

            encrypted_data = accounts_file.read_bytes()
            decrypted_data = fernet.decrypt(encrypted_data)

            raw_list = json.loads(decrypted_data.decode('utf-8'))

            if not isinstance(raw_list, list):
                logger.warning("accounts.json 格式异常：顶层不是列表，已备份。")
                self._backup_corrupt_file(accounts_file)
                return []

            accounts = []
            for i, item in enumerate(raw_list):
                try:
                    accounts.append(AccountCredential.model_validate(item))
                except Exception as e:
                    logger.warning(f"跳过格式异常的账号条目 (index={i}): {e}")

            logger.info(f"已加载 {len(accounts)} 个保存的账号。")
            return accounts

        except InvalidToken:
            logger.warning("账号文件解密失败（密钥不匹配），文件已保留，修复密钥环后可恢复。")
            return []

        except json.JSONDecodeError as e:
            logger.warning(f"账号文件 JSON 解析失败（文件损坏）: {e}")
            self._backup_corrupt_file(accounts_file)
            return []

        except Exception as unexpected_e:
            logger.critical(f"加载账号数据时发生意外错误: {unexpected_e}", exc_info=True)
            raise

    def save_accounts(self, accounts: list[AccountCredential]) -> None:
        """将账号列表加密后写入 accounts.json。"""
        accounts_file = self.get_accounts_filepath()

        if not accounts:
            logger.info("账号列表为空，删除账号文件。")
            if accounts_file.exists():
                try:
                    os.remove(accounts_file)
                except OSError as e:
                    logger.error(f"删除账号文件失败: {e}", exc_info=True)
            return

        try:
            key, persisted = self._get_encryption_key()
            if not persisted:
                logger.warning("密钥未持久化，跳过凭据写盘以避免产生无法解密的文件。")
                return

            f = Fernet(key)

            raw_list = [acc.model_dump() for acc in accounts]
            json_bytes = json.dumps(raw_list, ensure_ascii=False).encode('utf-8')
            encrypted_bytes = f.encrypt(json_bytes)

            accounts_file.write_bytes(encrypted_bytes)
            logger.info(f"已保存 {len(accounts)} 个账号到 {accounts_file}")
        except Exception as e:
            logger.error(f"保存账号数据失败: {e}", exc_info=True)

    def load_credentials(self, state: AppState) -> None:
        """加载凭据并激活第一个账号。"""
        state.saved_accounts = self.load_accounts()
        if state.saved_accounts:
            first = state.saved_accounts[0]
            state.sessdata = first.sessdata
            state.bili_jct = first.bili_jct
            logger.info(f"已激活账号: {first.name or '(未命名)'}")

    @staticmethod
    def _backup_corrupt_file(path: Path) -> None:
        """将损坏的文件备份为 .corrupt 后缀。"""
        try:
            backup = path.with_suffix(".json.corrupt")
            path.rename(backup)
            logger.info(f"已将损坏的文件备份为: {backup}")
        except OSError as e:
            logger.error(f"无法备份损坏的文件: {e}")
