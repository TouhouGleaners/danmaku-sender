import os
import json
import logging
import keyring
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from platformdirs import user_data_dir

from app_config import AppInfo


KEYRING_SERVICE_NAME = f"{AppInfo.NAME_EN}-CredentialsKey"
KEYRING_USERNAME = "default_user"
CREDENTIALS_FILE_NAME = "credentials.json"

logger = logging.getLogger("CredentialManager")


def get_credentials_filepath() -> Path:
    """获取应用程序配置文件的完整路径"""
    credentials_dir = Path(user_data_dir(AppInfo.NAME_EN, AppInfo.AUTHOR, ensure_exists=True))
    return credentials_dir / CREDENTIALS_FILE_NAME

def _get_encryption_key() -> bytes:
    """
    从系统密钥环获取加密密钥。
    如果不存在，则生成一个新的密钥并存储。
    """
    key_str = keyring.get_password(KEYRING_SERVICE_NAME, KEYRING_USERNAME)
    if key_str:
        logger.debug("已从系统密钥环获取加密密钥。")
        return key_str.encode('utf-8')
    else:
        new_key = Fernet.generate_key()
        keyring.set_password(KEYRING_SERVICE_NAME, KEYRING_USERNAME, new_key.decode('utf-8'))
        logger.info("已生成新的加密密钥并存储在系统密钥环中。")
        return new_key
    
def load_credentials() -> dict:
    """
    从加密的 credentials.json 加载凭证。
    如果文件不存在或解密失败，则返回空凭证。
    """
    credentials_file = get_credentials_filepath()
    default_credentials = {'SESSDATA': '', 'BILI_JCT': ''}
    
    if not credentials_file.exists():
        return default_credentials
    
    try:
        key = _get_encryption_key()
        fernet = Fernet(key)

        encrypted_data = credentials_file.read_bytes()
        decrypted_data = fernet.decrypt(encrypted_data)

        credentials = json.loads(decrypted_data.decode('utf-8'))
        logger.info("凭证已成功加载和解密。")
        return credentials
    except (InvalidToken, json.JSONDecodeError, FileNotFoundError) as e:
        logger.warning(f"无法加载或解密凭证: {e}，返回空凭证。")
        # 如果解密失败或文件损坏则删除它，以防下次出现同样问题
        if credentials_file.exists():
            try:
                os.remove(credentials_file)
                logger.info(f"已删除损坏/无法读取的凭证文件: {credentials_file}")
            except OSError as del_e:
                logger.error(f"无法删除损坏的凭证文件: {del_e}")
        return default_credentials
    
    # 捕获所有其他未知错误，记录后立即失败
    except Exception as unexpected_e:
        logger.critical(f"加载凭证时发生意外错误: {unexpected_e}", exc_info=True)
        raise
    
def save_credentials(data: dict):
    """将 SESSDATA 和 BILI_JCT 加密后写入 credentials.json 中。"""
    sessdata = data.get('SESSDATA', '').strip()
    bili_jct = data.get('BILI_JCT', '').strip()
    # 如果凭证为空，则不保存文件
    if not sessdata or not bili_jct:
        logger.info("凭证为空，不保存凭证文件。")
        return
    credentials_to_save = {
        'SESSDATA': sessdata,
        'BILI_JCT': bili_jct,
    }
    try:
        key = _get_encryption_key()
        f = Fernet(key)
        
        json_bytes = json.dumps(credentials_to_save, ensure_ascii=False).encode('utf-8')
        encrypted_bytes = f.encrypt(json_bytes)
        
        credentials_file = get_credentials_filepath()
        credentials_file.write_bytes(encrypted_bytes)
        logger.info(f"凭证已安全保存到 {credentials_file}")
    except Exception as e:
        logger.error(f"保存加密凭证失败: {e}", exc_info=True)