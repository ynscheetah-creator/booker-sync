# -*- coding: utf-8 -*-
"""
Notion sync for Goodreads rows:
- Queries pages where `goodreadsURL` is set
- Fills only empty/placeholder fields
- Updates page cover with external cover URL
- Handles property types dynamically
"""

from __future__ import annotations
import os
from typing import Dict, Any, Optional, List
from notion_client import Client
from notion_client.helpers import iterate_paginated_api
from goodreads_scraper import scrape_goodreads

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

client = Client(auth=NOTION_TOKEN)

# Kullanıcı "placeholder"ları – bunları görünce üzerine yazarız.
PLACEHOLDERS = {"goodreads", "authors", "author", "good reads", "title", "publisher"}

RICH_TEXT_LIMIT = 2000

# ---- Yardımcılar -----------------------------------------------------------

def _plain_from_title(prop: Dict[str, Any]) -> str:
    parts = prop.get("title", [])
    return "".join(p.get("plain_text", "") for p in parts).strip()

def _plain_from_rich(prop: Dict[str, Any]) -> str:
    parts = prop.get("rich_text", [])
    return "".join(p.get("plain_text", "") for p in parts).strip()

def _is_placeholder(txt: Optional[str]) -> bool:
    if not txt:
        return True
    t = txt.strip().lower()
    return t in PLACEHOLDERS

def _truncate(txt: Optional[str], limit: int = RICH_TEXT_LIMIT) -> Optional[str]:
    if not txt:
        return None
    if len(txt) <= limit:
        return txt
    return txt[: limit - 1] + "…"

def _set_prop(payload: Dict[str, Any], name: str, v: Any, ptype: str):
    """
    Şemadaki tipe göre property değerini hazırlar.
    """
    if v is None or v == "":
        return

    if ptype == "title":
        payload[name] = {"title": [{"type": "text", "text": {"content": str(v)}}]}
    elif ptype == "rich_text":
        payload[name] = {"rich_text": [{"type": "text", "text": {"content": _truncate(str(v))}}]}
    elif ptype == "url":
        payload[name] = {"url": str(v)}
    elif ptype == "number":
        try:
            payload[name] = {"number": float(v) if v is not None else None}
        except Exception:
            # metin gelirse dokunma
            pass
    elif ptype == "select":
        payload[name] = {"select": {"name": str(v)}}
    else:
        # diğer tipler (multi_select vs.) için basit rich_text fallback
        payload[name] = {"rich_text": [{"type": "text", "text": {"content": _truncate(str(v))}}]}

def _get_prop_type(db_schema: Dict[str, Any], name: str) -> Optional[str]:
    p = db_schema.get("properties", {}).get(name)
    return p.get("type") if p else None

def _current_text(page_prop: Dict[str, Any]) -> str:
    t = page_prop.get("type")
    if t == "title":
        return _plain_from_title(page_prop)
    if t == "rich_text":
        return _plain_from_rich(page_prop)
    if t == "url":
        return page_prop.get("url") or ""
    if t == "number":
        n = page_prop.get("number")
        return "" if n is None else str(n)
    return ""

def _should_update(current_text: str) -> bool:
    return (not current_text) or _is_placeholder(current_text)

# ---- Çek & Güncelle -------------------------------------------------------

def query_candidate_pages() -> List[Dict[str, Any]]:
    """
    goodreadsURL dolu olan tüm sayfaları getir.
    Filtreyi geniş bıraktık, alan bazlı karar sayfa üstünde veriliyor.
    """
    pages = []
    for page in iterate_paginated_api(
        client.databases.query, database_id=DATABASE_ID,
        filter={
            "property": "goodreadsURL",
            "url": {"is_not_empty": True}
        }
    ):
        pages.append(page)
    return pages

def build_updates(db_schema: Dict[str, Any], page: Dict[str, Any], scraped: Dict[str, Any]) -> Dict[str, Any]:
    props = page["properties"]
    out: Dict[str, Any] = {}

    # db’de olan property’lere bakıp tek tek karar veriyoruz:
    for k_notion, v in scraped.items():
        if k_notion not in props:
            continue  # veritabanında bu kolon yok
        ptype = _get_prop_type(db_schema, k_notion)
        cur = _current_text(props[k_notion])
        if _should_update(cur):
            _set_prop(out, k_notion, v, ptype)

    # Title kolonunun adı “Title” ve type=title ise özellikle doldur.
    if "Title" in props and "Title" in scraped:
        ptype = _get_prop_type(db_schema, "Title")
        cur = _current_text(props["Title"])
        if _should_update(cur):
            _set_prop(out, "Title", scraped["Title"], ptype)

    return out

def update_page_cover(page_id: str, cover_url: Optional[str]):
    if not cover_url:
        return
    try:
        client.pages.update(
            page_id=page_id,
            cover={"type": "external", "external": {"url": cover_url}}
        )
    except Exception:
        pass

def run_once():
    db_schema = client.databases.retrieve(database_id=DATABASE_ID)
    pages = query_candidate_pages()

    for pg in pages:
        page_id = pg["id"]
        props = pg["properties"]

        gr = props.get("goodreadsURL", {})
        url_val = gr.get("url") if gr.get("type") == "url" else None
        if not url_val:
            continue

        # scrape
        data = scrape_goodreads(url_val).to_notion_payload_dict()

        # güncelleme payload’u
        payload = build_updates(db_schema, pg, data)

        # göndermek üzere property’ler varsa güncelle
        if payload:
            client.pages.update(page_id=page_id, properties=payload)

        # kapak
        update_page_cover(page_id, data.get("Cover URL"))


if __name__ == "__main__":
    run_once()
