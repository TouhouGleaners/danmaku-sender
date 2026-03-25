from enum import Enum


class BiliDmErrorCode(Enum):
    """B站弹幕错误码枚举"""
    # --- 0. 成功 ---
    SUCCESS = 0

    # --- 1. B站业务限制 ---
    # 鉴权类
    UNAUTHORIZED = -101
    ACCOUNT_BANNED = -102
    CSRF_FAILED = -111

    # 请求类
    REQUEST_ERROR = -400
    NOT_FOUND = -404

    # 业务限制类
    SYSTEM_UPGRADING = 36700
    CONTENT_FORBIDDEN = 36701
    DANMAKU_TOO_LONG = 36702
    FREQ_LIMIT = 36703
    VIDEO_NOT_REVIEWED = 36704
    LEVEL_INSUFFICIENT_GENERAL = 36705
    LEVEL_INSUFFICIENT_TOP = 36706
    LEVEL_INSUFFICIENT_BOTTOM = 36707
    LEVEL_INSUFFICIENT_COLOR = 36708
    LEVEL_INSUFFICIENT_ADVANCED = 36709
    PERMISSION_INSUFFICIENT_STYLE = 36710
    VIDEO_DANMAKU_FORBIDDEN = 36711
    LENGTH_LIMIT_LEVEL1 = 36712
    VIDEO_NOT_PAID = 36713
    INVALID_PROGRESS = 36714
    DAILY_LIMIT_EXCEEDED = 36715
    NOT_PREMIUM_MEMBER = 36718

    # --- 2. 外部系统/协议异常 ---
    BILI_SERVER_ERROR = -1       # B站服务器内部 500
    BILI_UNKNOWN_ERROR = -999    # B站返回了未知的错误
    NETWORK_ERROR = -9001        # 物理断网、超时
    PROTOCOL_ERROR = -9002       # HTTP 状态码非 200
    RESPONSE_MALFORMED = -9003   # 响应不是合法的 JSON 或格式不符

    # --- 3. 客户端自身异常 (代码 Bug 或未处理的 Exception) ---
    CLIENT_RUNTIME_ERROR = -9999


    @property
    def code(self) -> int:
        """返回错误码的数字值"""
        return self.value

    @property
    def description(self) -> str:
        """获取该错误码对应的中文描述"""
        return ERROR_METADATA.get(self, ("未知错误", True))[0]

    @property
    def is_fatal(self) -> bool:
        """判断该错误是否为致命错误（需中断任务）"""
        return ERROR_METADATA.get(self, ("未知错误", True))[1]

    @classmethod
    def from_code(cls, code: int) -> 'BiliDmErrorCode':
        try:
            return cls(code)
        except ValueError:
            return cls.BILI_UNKNOWN_ERROR


# 映射表
ERROR_METADATA = {
    BiliDmErrorCode.SUCCESS:                        ("弹幕发送成功。", False),

    BiliDmErrorCode.UNAUTHORIZED:                   ("账号未登录或登录态失效！请检查SESSDATA和bili_jct。", True),
    BiliDmErrorCode.ACCOUNT_BANNED:                 ("账号被封停。", True),
    BiliDmErrorCode.CSRF_FAILED:                    ("CSRF 校验失败 (bili_jct 可能失效)，请检查登录凭证或尝试重新获取。", True),

    BiliDmErrorCode.REQUEST_ERROR:                  ("请求错误，参数不合法。", False),
    BiliDmErrorCode.NOT_FOUND:                      ("请求资源不存在。", True),

    # 业务限制类
    BiliDmErrorCode.SYSTEM_UPGRADING:               ("系统升级中，暂无法发送弹幕。", True),
    BiliDmErrorCode.CONTENT_FORBIDDEN:              ("弹幕包含被禁止的内容，请修改后重试。", False),
    BiliDmErrorCode.DANMAKU_TOO_LONG:               ("弹幕长度大于100字，请精简。", False),
    BiliDmErrorCode.FREQ_LIMIT:                     ("发送频率过快，请稍后再试。", False),
    BiliDmErrorCode.VIDEO_NOT_REVIEWED:             ("禁止向未审核的视频发送弹幕。", True),
    BiliDmErrorCode.LEVEL_INSUFFICIENT_GENERAL:     ("您的等级不足，不能发送弹幕。", True),
    BiliDmErrorCode.LEVEL_INSUFFICIENT_TOP:         ("您的等级不足，不能发送顶端弹幕。", False),
    BiliDmErrorCode.LEVEL_INSUFFICIENT_BOTTOM:      ("您的等级不足，不能发送底端弹幕。", False),
    BiliDmErrorCode.LEVEL_INSUFFICIENT_COLOR:       ("您的等级不足，不能发送彩色弹幕。", False),
    BiliDmErrorCode.LEVEL_INSUFFICIENT_ADVANCED:    ("您的等级不足，不能发送高级弹幕。", False),
    BiliDmErrorCode.PERMISSION_INSUFFICIENT_STYLE:  ("您的权限不足，不能发送这种样式的弹幕。", False),
    BiliDmErrorCode.VIDEO_DANMAKU_FORBIDDEN:        ("该视频禁止发送弹幕，无法发送。", True),
    BiliDmErrorCode.LENGTH_LIMIT_LEVEL1:            ("Level 1用户发送弹幕的最大长度为20字。", False),
    BiliDmErrorCode.VIDEO_NOT_PAID:                 ("此稿件未付费，暂时无法发送弹幕。", True),
    BiliDmErrorCode.INVALID_PROGRESS:               ("弹幕发送时间（progress）不合法。", False),
    BiliDmErrorCode.DAILY_LIMIT_EXCEEDED:           ("当日操作数量超过上限。", False),
    BiliDmErrorCode.NOT_PREMIUM_MEMBER:             ("目前您不是大会员，无法使用会员权益。", False),

    # 内部自定义错误
    BiliDmErrorCode.BILI_SERVER_ERROR:              ("B站服务器繁忙或发生故障(Code -1)。", True),
    BiliDmErrorCode.BILI_UNKNOWN_ERROR:             ("B站返回了未定义的业务错误", True),
    BiliDmErrorCode.NETWORK_ERROR:                  ("网络连接失败，请检查网线或代理。", True),
    BiliDmErrorCode.PROTOCOL_ERROR:                 ("与B站通讯协议发生冲突。", True),
    BiliDmErrorCode.RESPONSE_MALFORMED:             ("收到非法的服务器响应数据。", True),
    BiliDmErrorCode.CLIENT_RUNTIME_ERROR:           ("程序内部发生未知错误。", True),
}