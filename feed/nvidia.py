"""Shared NVIDIA credentials and JSON completion transport."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .settings import ROOT, file_setting, setting


NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"


def api_key(required: bool = True) -> str:
    key = setting("NVIDIA_API_KEY") or file_setting(ROOT.parent / "myAPIKEYs" / ".env", "NVIDIA_API_KEY")
    if not key and not required:
        return ""
    if not key or not key.isascii() or any(char.isspace() for char in key):
        raise ValueError("NVIDIA_API_KEY를 환경변수 또는 로컬 .env에 설정하세요.")
    return key


def request_nvidia(payload: dict, key: str) -> dict:
    request = Request(NVIDIA_URL, data=json.dumps(payload).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}",
    })
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as error:
        raise ValueError(f"NVIDIA API HTTP {error.code}") from None
    except URLError as error:
        raise ValueError(f"NVIDIA API 연결 실패 ({type(error.reason).__name__})") from None
    try:
        return json.loads(result["choices"][0]["message"]["content"])
    except (KeyError, TypeError, ValueError, IndexError):
        raise ValueError("NVIDIA API가 유효한 JSON 응답을 반환하지 않았습니다.") from None
