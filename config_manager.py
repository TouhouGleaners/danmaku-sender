import json
import os
import sys
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
import keyring
from platformdirs import user_data_dir


APP_NAME = "BiliDanmakuSender"
AUTHOR_NAME = "Miku_oso"
KEYRING_SERVICE_NAME = f"{APP_NAME}-CredentialsKey"
KEYRING_USERNAME = "default_user"
CONFIG_FILE_NAME = "config.json"


def get_config_filepath() -> Path:
    """获取应用程序配置文件的完整路径"""
    config_dir = Path(user_data_dir(APP_NAME, AUTHOR_NAME, ensure_exists=True))
    return config_dir / CONFIG_FILE_NAME

def _get_encryption_key() -> bytes:
    """
    从系统密钥环获取加密密钥。
    如果不存在，则生成一个新的密钥并存储。
    """
    key_str = keyring.get_password(KEYRING_SERVICE_NAME, KEYRING_USERNAME)
    if key_str:
        return key_str.encode('utf-8')
    else:
        new_key = Fernet.generate_key()
        keyring.set_password(KEYRING_SERVICE_NAME, KEYRING_USERNAME, new_key.decode('utf-8'))
        print(f"Info: Generated new encryption key and stored in system keyring.", file=sys.stderr)
        return new_key
    
def load_config() -> dict:
    """
    从加密的 config.json 加载凭证。
    如果文件不存在或解密失败，则返回空凭证。
    """
    config_file = get_config_filepath()
    default_credentials = {'SESSDATA': '', 'BILI_JCT': ''}
    
    if not config_file.exists():
        return default_credentials
    
    try:
        key = _get_encryption_key()
        fernet = Fernet(key)

        encrypted_data = config_file.read_bytes()
        decrypted_data = fernet.decrypt(encrypted_data)

        credentials = json.loads(decrypted_data.decode('utf-8'))
        print("Info: Credentials loaded and decrypted successfully.", file=sys.stderr)
        return credentials
    except (InvalidToken, json.JSONDecodeError, FileNotFoundError, Exception) as e:
        print(f"Warning: Could not load or decrypt credentials: {e}. Returning empty credentials.", file=sys.stderr)
        # 如果解密失败或文件损坏则删除它，以防下次出现同样问题
        if config_file.exists():
            try:
                os.remove(config_file)
                print(f"Info: Removed corrupted/unreadable config file at {config_file}", file=sys.stderr)
            except OSError as del_e:
                print(f"Error: Failed to remove corrupted config file: {del_e}", file=sys.stderr)
        return default_credentials
    
def save_config(data: dict):
    """将 SESSDATA 和 BILI_JCT 加密后写入 config.json 中。"""
    sessdata = data.get('SESSDATA', '').strip()
    bili_jct = data.get('BILI_JCT', '').strip()
    # 如果凭证为空，则不保存文件
    if not sessdata or not bili_jct:
        print("Info: Credentials are empty, not saving config file.", file=sys.stderr)
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
        
        config_file = get_config_filepath()
        config_file.write_bytes(encrypted_bytes)
        print(f"Info: Credentials saved securely to {config_file}", file=sys.stderr)
    except Exception as e:
        print(f"Error: Failed to save encrypted credentials: {e}", file=sys.stderr)