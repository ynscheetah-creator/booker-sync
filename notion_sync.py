# -*- coding: utf-8 -*-
"""
Notion <-> Goodreads senkronizasyonu.

Çalışma mantığı:
- Notion veritabanında goodreadsURL sütunu dolu ve /book/show/ içeren
  TÜM sayfaları çeker (filtre sade). Hangi alanların yazılacağına
  _prop_empty() ve FORCE_UPDATE/OVERWRITE karar verir.
- Goodreads sayfasını kazır (goodreads_scraper.fetch_goodreads),
  dönen alanları Notion şemasına yazar.
- "Goodreads" / "Authors" gibi yer tutucu metinleri boş sayar.
- FORCE_UPDATE=true ise dolu alanlar da ezilir.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from notion_client import Client
from notion_client.helpers import iterate_paginated_api

from goodreads_scraper import fetch_goodreads


# --------------------------------------------------------------------
# Ortam değişkenleri
# --------------------------------------------------------------------
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Bir kereliğine her şeyi üzerine yazmak için:
FORCE_UPDATE = os.getenv("FORCE_UPDATE", "false").lower() == "true"
OVERWRITE = FORCE_UPDATE

USER_AGENT = os.getenv(
    "USER_AGENT",
    # makul bir UA
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Notion’daki sütun adları
# (Tablondaki adları birebir yazmalısın; farklıysa değiştir)
COLUMN_COVER = "Cover URL"
COLUMN_GR_URL = "goodreadsURL"


# --------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def client() -> Client:
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_TOKEN is missing")
    return Client(auth=NOTION_TOKEN)


def _prop_empty(prop: Dict[str, Any]) -> bool:
    """
    Notion property boş mu?
    ÖNEMLİ: Yer tutucu metinler de boş sayılır:
      - "Goodreads" (title ya da rich_text)
      - "Authors", "Author"
    """
    if not prop:
        return True

    placeholders = {"goodreads", "authors", "author", "good reads"}

    # Page title property
    if "title" in prop:
        texts = [t.get("plain_text", "") for t in prop.get("title", [])]
        text = "".join(texts).strip()
        if not text or text.lower() in placeholders:
            return True
        return False

    # Rich text property (ör: sende Title rich_text)
    if "rich_text" in prop:
        texts = [t.get("plain_text", "") for t in prop.get("rich_text", [])]
        text = "".join(texts).strip()
        if not text or text.lower() in placeholders:
            return True
        return False

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


# Notion’a yazma sırası (adlar Notion sütun adları)
ORDER: List[str] = [
    "Title",
    "Author",
    "Publisher",
    "Language",
    "Description",
    "Number of Pages",
    "Year Published",
    "ISBN13",
    COLUMN_COVER,     # Kapak sütununun adı
    COLUMN_GR_URL,    # GR linkini de (güncel URL) istersen yazdırır
]


def build_updates(schema: Dict[str, Any], scraped: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """
    scraped dict’inde gelen değerleri Notion şemasına encode eder.
    Korumalar:
      - Publisher <= 200 karakter
      - Description <= 1900 karakter
      - Title/Author <= 1000 karakter
      - Cover URL yazılacaksa mutlaka http(s) ile başlasın
    """
    updates: Dict[str, Any] = {}

    def _cap(key: str, val: str) -> str:
        if key == "Publisher":
            return val[:200]
        if key == "Description":
            return val[:1900]
        if key in ("Title", "Author"):
            return val[:1000]
        return val

    for key in ORDER:
        if key not in schema:
            continue

        # scraped'te yoksa yazma
        if key not in scraped:
            continue

        # mevcut doluysa ve OVERWRITE kapalıysa atla
        if not (OVERWRITE or _prop_empty(current.get(key))):
            continue

        value = scraped.get(key)
        if value in (None, ""):
            continue

        if key == COLUMN_COVER and isinstance(value, str):
            if not value.startswith(("http://", "https://")):
                continue

        if isinstance(value, str):
            value = _cap(key, value.strip())

        enc = _enc(schema[key], value)
        if enc:
            updates[key] = enc

    # Senkron zamanı
    if "LastSynced" in schema:
        updates["LastSynced"] = {"date": {"start": now_iso()}}
    return updates


# --------------------------------------------------------------------
# Notion sorgu & güncelleme
# --------------------------------------------------------------------
def query_targets() -> Dict[str, Any]:
    """
    Goodreads URL'i olan TÜM sayfaları getir.
    Hangi alanın yazılacağına _prop_empty ve OVERWRITE karar verir.
    """
    c = client()
    filters = [
        {"property": COLUMN_GR_URL, "url": {"is_not_empty": True}},
        {"property": COLUMN_GR_URL, "url": {"contains": "/book/show/"}},
    ]
    return c.databases.query(
        database_id=DATABASE_ID, filter={"and": filters}, page_size=100
    )


def update_page(page_id: str, scraped: Dict[str, Any]) -> None:
    c = client()
    page = c.pages.retrieve(page_id=page_id)
    schema = page["properties"]

    # scraped'ten "coverURL" geldiyse Notion sütun adını eşitle
    if "coverURL" in scraped and COLUMN_COVER not in scraped:
        scraped[COLUMN_COVER] = scraped["coverURL"]

    updates = build_updates(schema, scraped, current=schema)

    # Sayfa kapağını ayarla
    cover_url = scraped.get(COLUMN_COVER) or scraped.get("coverURL")
    cover_payload = {}
    if cover_url and isinstance(cover_url, str) and cover_url.startswith(("http://", "https://")):
        # cover boşsa ya da OVERWRITE açıksa kapağı güncelle
        if page.get("cover") is None or OVERWRITE:
            cover_payload = {"cover": {"type": "external", "external": {"url": cover_url}}}

    if updates or cover_payload:
        client().pages.update(page_id=page_id, properties=updates or {}, **cover_payload)


# --------------------------------------------------------------------
# İş akışı
# --------------------------------------------------------------------
def run_once() -> None:
    c = client()
    resp = query_targets()

    # iterate_paginated_api ile tüm sonuçları gez
    pages = list(iterate_paginated_api(c.databases.query, database_id=DATABASE_ID, filter=resp.get("filter")))

    if not pages:
        print("No rows to update.")
        return

    for page in pages:
        page_id = page["id"]
        props = page["properties"]

        # Goodreads URL'ini çek
        gr_url = None
        try:
            gr_url = props[COLUMN_GR_URL]["url"]
        except Exception:
            pass

        if not gr_url:
            print(f"Skip (no gr url): {page_id}")
            continue

        # Goodreads kazı
        try:
            scraped = fetch_goodreads(gr_url, ua=USER_AGENT) or {}
        except Exception as e:
            print(f"ERR fetch {gr_url}: {e}")
            continue

        if not scraped:
            print(f"WARN no data for: {gr_url}")
            continue

        # İstersen canonical/gr güncel URL'ini de yaz
        scraped[COLUMN_GR_URL] = gr_url

        # Güncelle
        try:
            update_page(page_id, scraped)
            print(f"Updated {page_id} ← Goodreads")
        except Exception as e:
            print(f"ERR update {page_id}: {e}")


# --------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------
if __name__ == "__main__":
    run_once()
