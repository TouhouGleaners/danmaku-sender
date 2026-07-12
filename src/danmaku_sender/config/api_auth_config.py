from dataclasses import dataclass


@dataclass
class ApiAuthConfig:
    sessdata: str
    bili_jct: str
    use_system_proxy: bool
