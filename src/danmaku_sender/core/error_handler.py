from .exceptions import BiliApiException
from .models.errors import BiliDmErrorCode


def resolve_bili_error(code: int, raw_message: str) -> tuple[int, str]:
    """根据状态码获取描述"""
    enum_number = BiliDmErrorCode.from_code(code)

    if enum_number:
        return code, enum_number.description_str
    
    if raw_message and str(raw_message).strip():
        return code, str(raw_message)

    return code, BiliDmErrorCode.GENERIC_FAILURE.description_str

def normalize_exception(e: Exception) -> BiliDmErrorCode:
    """将任意异常转换为标准错误码"""
    if isinstance(e, BiliApiException):
        found = BiliDmErrorCode.from_code(e.code)
        if found:
            return found

        if e.is_network_error:
            return BiliDmErrorCode.NETWORK_ERROR

        return BiliDmErrorCode.GENERIC_FAILURE

    code = getattr(e, "code", None)
    if code is not None:
        found = BiliDmErrorCode.from_code(code)
        if found:
            return found

    return BiliDmErrorCode.UNKNOWN_ERROR