# -*- coding: utf-8 -*-
"""
Notion <-> Goodreads (sadece Goodreads URL'inden) senk.
Sadece AŞAĞIDAKİ KOLON ADLARINA yazar:

- goodreadsURL (URL)
- Book Id (number)
- Title (rich_text)
- Cover URL (url)
- Author (rich_text)
- Additional Authors (rich_text)
- Publisher (rich_text)
- Year Published (number)
- Original Publication Year (number)
- Number of Pages (number)
- Language (rich_text veya select; ikisi de desteklenir)
- ISBN (rich_text)
- ISBN13 (rich_text)
- Average Rating (number)

Boş alanlara yazar. Hepsini ezmek için FORCE_UPDATE=true kullan.
"""

import os
from typing import Any, Dict

from notion_client import Client
from notion_client.helpers import iterate_paginated_api

from goodreads_scraper import fetch_goodreads

NOTION_TOKEN   = os.getenv("NOTION_TOKEN")
DATABASE_ID    = os.getenv("NOTION_DATABASE_ID")
FORCE_UPDATE   = os.getenv("FORCE_UPDATE", "false").lower() == "true"
USER_AGENT     = os.getenv("USER_AGENT", "")

c = Client(auth=NOTION_TOKEN)

# Notion sütun adları
COLS = [
    "goodreadsURL",
    "Book Id",
    "Title",
    "Cover URL",
    "Author",
    "Additional Authors",
    "Publisher",
    "Year Published",
    "Original Publication Year",
    "Number of Pages",
    "Language",
    "ISBN",
    "ISBN13",
    "Average Rating",
]

def _empty(prop: Dict[str, Any]) -> bool:
    if not prop:
        return True
    if "url" in prop:
        return not prop.get("url")
    if "number" in prop:
        return prop.get("number") is None
    if "select" in prop:
        return prop.get("select") is None
    if "title" in prop:
        return not "".join([t.get("plain_text","") for t in prop["title"]]).strip()
    if "rich_text" in prop:
        return not "".join([t.get("plain_text","") for t in prop["rich_text"]]).strip()
    return True

def _encode(schema: Dict[str, Any], value: Any) -> Dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        value = value.strip()
    if "title" in schema:
        return {"title": [{"type": "text", "text": {"content": str(value)}}]}
    if "rich_text" in schema:
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
    if "url" in schema:
        return {"url": str(value)}
    if "number" in schema:
        try: return {"number": float(value)}
        except Exception: return {}
    if "select" in schema:
        return {"select": {"name": str(value)}}
    return {}

def _updates(schema: Dict[str, Any], scraped: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    up: Dict[str, Any] = {}
    for col in COLS:
        if col not in schema:    # Notion’da yoksa atla
            continue
        if col not in scraped:   # Scraper üretmediyse atla
            continue
        if not (FORCE_UPDATE or _empty(current.get(col))):
            continue

        val = scraped[col]
        # Güvenlik: Publisher çok uzun olmasın
        if col == "Publisher" and isinstance(val, str):
            val = val[:200]
        if col == "Title" and isinstance(val, str):
            val = val[:1000]

        enc = _encode(schema[col], val)
        if enc:
            up[col] = enc
    return up

def _apply_cover(page: Dict[str, Any], scraped: Dict[str, Any]) -> Dict[str, Any]:
    url = scraped.get("coverURL")
    if not url or not isinstance(url, str) or not url.startswith(("http://","https://")):
        return {}
    # kapağı sadece boşsa ya da FORCE_UPDATE açıkken yaz
    if page.get("cover") is None or FORCE_UPDATE:
        return {"cover": {"type": "external", "external": {"url": url}}}
    return {}

def run_once() -> None:
    # sadece goodreadsURL dolu & /book/show/ içeren tüm sayfalar
    pages_iter = iterate_paginated_api(
        c.databases.query,
        database_id=DATABASE_ID,
        filter={
            "and":[
                {"property":"goodreadsURL","url":{"is_not_empty":True}},
                {"property":"goodreadsURL","url":{"contains":"/book/show/"}},
            ]
        },
        page_size=100,
    )

    for page in pages_iter:
        pid = page["id"]
        props = page["properties"]
        gr = props.get("goodreadsURL",{}).get("url")
        if not gr:
            continue

        # scrape
        try:
            data = fetch_goodreads(gr, ua=USER_AGENT) or {}
        except Exception as e:
            print(f"ERR fetch {gr}: {e}")
            continue

        # scraped anahtarlarını Notion kolonlarına aynı isimle bırakıyoruz
        # (goodreads_scraper zaten bu isimlerle döndürüyor)
        updates = _updates(props, data, props)
        cover   = _apply_cover(page, data)

        if updates or cover:
            try:
                c.pages.update(page_id=pid, properties=updates or {}, **cover)
                print(f"Updated {pid}")
            except Exception as e:
                print(f"ERR update {pid}: {e}")

if __name__ == "__main__":
    if not NOTION_TOKEN or not DATABASE_ID:
        raise SystemExit("NOTION_TOKEN / NOTION_DATABASE_ID eksik.")
    run_once()
