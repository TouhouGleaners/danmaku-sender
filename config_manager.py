import json
from pathlib import Path


CONFIG_FILE = Path('config.json')

DEFAULT_CONFIG = {
    'SESSDATA': '',
    'BILI_JCT': '',
    'BVID': '',
    'XML_FILE_PATH': '',
    'MIN_DELAY': 5.0,
    'MAX_DELAY': 10.0
}

def load_config():
    """
    从 config.json 加载配置。
    如果文件不存在或内容无效，则返回默认配置。
    """
    config = DEFAULT_CONFIG.copy()

    if not CONFIG_FILE.exists():
        return config
    
    try:
        config_text = CONFIG_FILE.read_text(encoding='utf-8')
        saved_credentials = json.loads(config_text)  # 加载文件中保存的凭证
        config.update(saved_credentials)  # 用加载的凭证更新默认配置，其他字段保持默认
        return config
    except (json.JSONDecodeError, TypeError):
        return DEFAULT_CONFIG.copy()  # 如果文件损坏或者格式不正确，则返回默认值
        
def save_config(data: dict):
    """将 cookies 写入 config.json 中"""
    config_to_save = {
        'SESSDATA': data.get('SESSDATA', ''),
        'BILI_JCT': data.get('BILI_JCT', ''),
    }

    try:
        json_string = json.dumps(config_to_save, ensure_ascii=False, indent=4)
        CONFIG_FILE.write_text(json_string, encoding='utf-8')
    except Exception as e:
        print(f"错误: 保存配置到 {CONFIG_FILE} 时失败: {e}")