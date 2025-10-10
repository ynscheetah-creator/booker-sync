import os
import re
from typing import Optional

def get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(name)
    return val if (val is not None and str(val).strip()) else default

def get_user_agent() -> str:
    # GitHub secret'tan gelsin; yoksa makul bir fallback verelim
    return get_env("USER_AGENT",
                   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

def truncate(txt: Optional[str], max_len: int = 2000) -> Optional[str]:
    if txt is None:
        return None
    return txt[:max_len]

def to_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        # sadece sayıyı çekip deneyelim
        m = re.search(r"(\d+)", str(value))
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None

# Notion tip yardımcıları (tek yerde güvenli güncelleyelim)
def as_title(value: Optional[str]):
    if not value:
        return None
    return {"title": [{"type": "text", "text": {"content": truncate(value)}}]}

def as_rich(value: Optional[str]):
    if not value:
        return None
    return {"rich_text": [{"type": "text", "text": {"content": truncate(value)}}]}

def as_url(value: Optional[str]):
    if not value:
        return None
    return {"url": value}

def as_number(value: Optional[str]):
    num = to_int(value) if not isinstance(value, (int, float)) else value
    if num is None:
        return None
    return {"number": num}
