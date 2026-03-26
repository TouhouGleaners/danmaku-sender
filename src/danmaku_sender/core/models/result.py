from dataclasses import dataclass

from .errors import BiliDmErrorCode


@dataclass
class DanmakuSendResult:
    """封装弹幕发送结果"""
    code: int
    is_success: bool
    msg: str            # B站原话
    hint: str           # UI提示
    dmid: str = ""      # data.dmid_str
    is_visible: bool = True


    @property
    def is_fatal(self) -> bool:
        """
        判断当前错误是否为致命错误。
        通过将错误码转换为 BiliDmErrorCode 枚举类型，检查其 is_fatal 属性
        来确定该错误是否为致命错误。
        致命错误通常表示无法恢复的严重问题，应该立即停止相关操作。

        Returns:
            bool: 如果是致命错误返回 True，否则返回 False。
        """
        return BiliDmErrorCode.from_code(self.code).is_fatal

    @classmethod
    def from_api_response(cls, response_json: dict) -> 'DanmakuSendResult':
        """从 API JSON 响应构建结果对象"""
        # 提取原始 code 和 message
        code = response_json.get('code', BiliDmErrorCode.RESPONSE_MALFORMED.code)
        msg = str(response_json.get('message', '')).strip()

        # 转换枚举
        err_enum = BiliDmErrorCode.from_code(code)

        # 如果我们定义了该错误，hint 用字典描述；否则 hint 透传 B站原话
        if err_enum != BiliDmErrorCode.BILI_UNKNOWN_ERROR:
            hint = err_enum.description
        else:
            hint = msg if msg else err_enum.description

        dmid, visible = "", True
        if code == BiliDmErrorCode.SUCCESS.code:
            data = response_json.get('data', {})
            if isinstance(data, dict):
                dmid = str(data.get('dmid_str', data.get('dmid', '')))
                visible = data.get('visible', True)

            return cls(code=code, is_success=True, msg=msg, hint=hint, dmid=dmid, is_visible=visible)

        return cls(code=code, is_success=False, msg=msg, hint=hint)