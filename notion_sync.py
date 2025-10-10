# -*- coding: utf-8 -*-
"""
Notion ile senkron: Goodreads verisini ilgili sütunlara yazar.
- Only Goodreads: goodreadsURL dolu ve (Title/Author boş) satırları hedefler.
- FORCE_UPDATE=true ise: goodreadsURL dolu TÜM satırları günceller (üzerine yazar).
- 'coverURL' veya 'Cover URL' alanlarından biri varsa doldurur ve sayfa kapağını ayarlar.
"""
import os
from datetime import datetime, timezone
from typing import Any, Dict

from notion_client import Client

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
FORCE_UPDATE = os.getenv("FORCE_UPDATE", "false").lower() == "true"
OVERWRITE = FORCE_UPDATE  # eski isimle uyum

# ------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def client() -> Client:
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_TOKEN is missing")
    return Client(auth=NOTION_TOKEN)

def _prop_empty(prop: Dict[str, Any]) -> bool:
    if not prop:
        return True
    if "title" in prop:
        return len(prop.get("title", [])) == 0
    if "rich_text" in prop:
        return len(prop.get("rich_text", [])) == 0
    if "number" in prop:
        return prop.get("number") is None
    if "url" in prop:
        return not prop.get("url")
    if "select" in prop:
        return prop.get("select") is None
    if "date" in prop:
        return prop.get("date") is None
    return True

def _enc(schema: Dict[str, Any], value: Any) -> Dict[str, Any]:
    if value in (None, ""):
        return {}
    # güvenlik: metin değerlerini makul uzunlukta tut
    if isinstance(value, str):
        value = value.strip()
    if "title" in schema:
        return {"title": [{"type": "text", "text": {"content": str(value)}}]}
    if "rich_text" in schema:
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
    if "number" in schema:
        try:
            return {"number": float(value)}
        except Exception:
            return {}
    if "url" in schema:
        return {"url": str(value)}
    if "select" in schema:
        return {"select": {"name": str(value)}}
    if "date" in schema:
        return {"date": {"start": str(value)}}
    return {}

# yazım sırası (varsa bu sırayla dener)
ORDER = [
    "Title",
    "Author",
    "Publisher",
    "Language",
    "Description",
    "Number of Pages",
    "Year Published",
    "ISBN13",
    "coverURL",
    "Cover URL",
    "goodreadsURL",
]

def build_updates(schema: Dict[str, Any], scraped: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    for key in ORDER:
        if key not in schema:
            continue

        # FORCE_UPDATE/OVERWRITE true ise hep yaz; değilse sadece boş olanlara yaz
        can_write = OVERWRITE or _prop_empty(current.get(key))
        if not can_write:
            continue

        value = scraped.get(key)

        # Notion rich_text/text limitlerine uy: genel koruma
        if isinstance(value, str):
            max_len = 1900
            if key == "Publisher":
                max_len = 200
            elif key == "Title":
                max_len = 1000
            value = value[:max_len]

        enc = _enc(schema[key], value)
        if enc:
            updates[key] = enc

    # senkron tarihi
    if "LastSynced" in schema:
        updates["LastSynced"] = {"date": {"start": now_iso()}}
    return updates

# ------------------------------------

def query_targets() -> Dict[str, Any]:
    """
    Varsayılan: goodreadsURL dolu, URL kitap linki ve Title/Author boş olanları getir.
    FORCE_UPDATE=true ise: goodreadsURL dolu ve URL kitap linki olan TÜM sayfaları getirir.
    """
    c = client()
    filters = [
        {"property": "goodreadsURL", "url": {"is_not_empty": True}},
        {"property": "goodreadsURL", "url": {"contains": "/book/show/"}},
    ]
    if not FORCE_UPDATE:
        filters.append(
            {
                "or": [
                    {"property": "Title", "title": {"is_empty": True}},
                    {"property": "Author", "rich_text": {"is_empty": True}},
                ]
            }
        )
    return c.databases.query(
        database_id=DATABASE_ID, filter={"and": filters}, page_size=100
    )

def update_page(page_id: str, scraped: Dict[str, Any]) -> None:
    """
    scraped dict'ini uygun property'lere yazar, cover varsa sayfa kapağını set eder.
    """
    c = client()
    page = c.pages.retrieve(page_id=page_id)
    schema = page["properties"]

    updates = build_updates(schema, scraped, current=schema)

    # kapak url (coverURL veya Cover URL anahtarından)
    cover_url = scraped.get("Cover URL") or scraped.get("coverURL")
    cover_payload = {}
    if cover_url:
        # sadece kapak yoksa ya da FORCE_UPDATE etkinse kapağı güncelle
        if page.get("cover") is None or OVERWRITE:
            cover_payload = {"cover": {"type": "external", "external": {"url": str(cover_url)}}}

    if updates or cover_payload:
        c.pages.update(page_id=page_id, properties=updates or {}, **cover_payload)
