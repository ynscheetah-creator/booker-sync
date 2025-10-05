import re
import json
from datetime import datetime, timezone
from typing import Dict, Optional
from bs4 import BeautifulSoup

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def textclean(x: Optional[str]) -> Optional[str]:
    if not x:
        return x
    t = re.sub(r"\s+", " ", x).strip()
    t = re.sub(r"\s*\|\s*1000Kitap.*$", "", t, flags=re.I)
    t = re.sub(r"\s*\|\s*Goodreads.*$", "", t, flags=re.I)
    return t or None

def soup_from_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")

def extract_json_ld(soup: BeautifulSoup) -> Dict:
    data = {}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "{}")
            if isinstance(obj, list):
                for o in obj:
                    if isinstance(o, dict) and o.get("@type") in {"Book", "CreativeWork"}:
                        data.update(o)
            elif isinstance(obj, dict) and obj.get("@type") in {"Book", "CreativeWork"}:
                data.update(obj)
        except Exception:
            continue
    return data

def pick_first(*vals):
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None
