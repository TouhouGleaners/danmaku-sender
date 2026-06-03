import json
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from platformdirs import user_data_dir

from ..config.app_config import AppInfo
from ..core.models.account import AccountCredential
from . import credential_manager

logger = logging.getLogger("App.System.Account")

ACCOUNTS_FILE_NAME = "accounts.json"


def get_accounts_filepath() -> Path:
    """获取账号存储文件的完整路径"""
    credentials_dir = Path(user_data_dir(AppInfo.NAME_EN, AppInfo.AUTHOR, ensure_exists=True))
    return credentials_dir / ACCOUNTS_FILE_NAME


def load_accounts() -> list[AccountCredential]:
    """
    从加密的 accounts.json 加载账号列表。
    如果文件不存在或解密失败，返回空列表。
    """
    accounts_file = get_accounts_filepath()

    if not accounts_file.exists():
        return []

    try:
        key = credential_manager._get_encryption_key()
        fernet = Fernet(key)

        encrypted_data = accounts_file.read_bytes()
        decrypted_data = fernet.decrypt(encrypted_data)

        raw_list = json.loads(decrypted_data.decode('utf-8'))

        if not isinstance(raw_list, list):
            logger.warning("accounts.json 格式异常：顶层不是列表，返回空。")
            return []

        accounts = []
        for i, item in enumerate(raw_list):
            try:
                accounts.append(AccountCredential.model_validate(item))
            except Exception as e:
                logger.warning(f"跳过格式异常的账号条目 (index={i}): {e}")

        logger.info(f"已加载 {len(accounts)} 个保存的账号。")
        return accounts

    except (InvalidToken, json.JSONDecodeError) as e:
        logger.warning(f"无法加载或解密账号数据: {e}，返回空列表。")
        if accounts_file.exists():
            try:
                os.remove(accounts_file)
                logger.info("已删除损坏的账号文件。")
            except OSError as del_e:
                logger.error(f"无法删除损坏的账号文件: {del_e}")
        return []

    except Exception as unexpected_e:
        logger.critical(f"加载账号数据时发生意外错误: {unexpected_e}", exc_info=True)
        raise


def save_accounts(accounts: list[AccountCredential]):
    """将账号列表加密后写入 accounts.json。"""
    accounts_file = get_accounts_filepath()

    if not accounts:
        logger.info("账号列表为空，删除账号文件。")
        if accounts_file.exists():
            try:
                os.remove(accounts_file)
            except OSError as e:
                logger.error(f"删除账号文件失败: {e}", exc_info=True)
        return

    try:
        key = credential_manager._get_encryption_key()
        fernet = Fernet(key)

        raw_list = [acc.model_dump() for acc in accounts]
        json_bytes = json.dumps(raw_list, ensure_ascii=False).encode('utf-8')
        encrypted_bytes = fernet.encrypt(json_bytes)

        accounts_file.write_bytes(encrypted_bytes)
        logger.info(f"已保存 {len(accounts)} 个账号到 {accounts_file}")
    except Exception as e:
        logger.error(f"保存账号数据失败: {e}", exc_info=True)


def migrate_from_legacy() -> list[AccountCredential]:
    """
    从旧的单账号 credentials.json 迁移到多账号格式。
    迁移成功后删除旧文件。如果旧文件不存在则返回空列表。
    """
    legacy_creds = credential_manager.load_credentials()
    sessdata = legacy_creds.get('SESSDATA', '').strip()
    bili_jct = legacy_creds.get('BILI_JCT', '').strip()

    if not sessdata or not bili_jct:
        return []

    migrated = AccountCredential(uid=0, name="(已迁移)", sessdata=sessdata, bili_jct=bili_jct)
    logger.info("已从旧凭证文件迁移一个账号。")

    # 删除旧文件
    legacy_path = credential_manager.get_credentials_filepath()
    if legacy_path.exists():
        try:
            os.remove(legacy_path)
            logger.info("已删除旧的 credentials.json。")
        except OSError as e:
            logger.warning(f"删除旧凭证文件失败: {e}")

    return [migrated]
