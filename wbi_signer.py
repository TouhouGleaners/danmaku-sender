from functools import reduce
from hashlib import md5
import urllib.parse
import time
import requests
from typing import Optional, Tuple


class WbiSigner:
    """WBI 签名类，用于对 B 站 API 请求参数进行签名 (来源BAC)"""
    mixin_key_enc_tab = [
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
        33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
        61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
        36, 20, 34, 44, 52
    ]

    # 类变量，用于在单次运行程序时缓存密钥
    _cached_keys: Optional[Tuple[str, str]] = None
    _cached_time: float = 0
    CACHE_DURATION = 24 * 60 * 60  # 缓存时长为24小时(实际情况下单次运行程序不会超过这个时间)

    @staticmethod
    def get_mixin_key(orig: str):
        """对 imgKey 和 subKey 进行字符顺序打乱编码"""
        return reduce(lambda s, i: s + orig[i], WbiSigner.mixin_key_enc_tab, '')[:32]

    @staticmethod
    def enc_wbi(params: dict, img_key: str, sub_key: str):
        """为请求参数进行 wbi 签名"""
        mixin_key = WbiSigner.get_mixin_key(img_key + sub_key)
        curr_time = round(time.time())

        params_for_sign = params.copy()
        params_for_sign['wts'] = curr_time                       # 添加 wts 字段
        params_for_sign = dict(sorted(params_for_sign.items()))  # 按照 key 重排参数
        # 过滤 value 中的 "!'()*" 字符
        params_for_sign_filtered = {
            k : ''.join(filter(lambda chr: chr not in "!'()*", str(v)))
            for k, v 
            in params_for_sign.items()
        }

        query = urllib.parse.urlencode(params_for_sign_filtered)    # 序列化参数
        wbi_sign = md5((query + mixin_key).encode()).hexdigest()    # 计算 w_rid

        params['w_rid'] = wbi_sign
        params['wts'] = curr_time

        return params

    @classmethod
    def get_wbi_keys(cls) -> tuple[str, str]:
        """获取最新的 img_key 和 sub_key，带缓存机制"""
        current_time = time.time()
        
        # 如果缓存存在且未过期，直接返回缓存的键值
        if (cls._cached_keys is not None and 
            current_time - cls._cached_time < cls.CACHE_DURATION):
            return cls._cached_keys

        # 获取新的键值
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0',
            'Referer': 'https://www.bilibili.com/'
        }
        resp = requests.get('https://api.bilibili.com/x/web-interface/nav', headers=headers)
        resp.raise_for_status()
        json_content = resp.json()
        img_url: str = json_content['data']['wbi_img']['img_url']
        sub_url: str = json_content['data']['wbi_img']['sub_url']
        img_key = img_url.rsplit('/', 1)[1].split('.')[0]
        sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]

        # 更新缓存
        cls._cached_keys = (img_key, sub_key)
        cls._cached_time = current_time
        
        return cls._cached_keys