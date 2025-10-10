import os
from typing import Dict, Any, Optional, List
from notion_client import Client
from utils import now_iso

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID  = os.getenv("NOTION_DATABASE_ID")
OVERWRITE    = os.getenv("OVERWRITE", "false").lower() == "true"

def client() -> Client:
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_TOKEN missing")
    return Client(auth=NOTION_TOKEN)

def _enc(schema: Dict[str, Any], value):
    if value in (None, ""):
        return None
    if "title" in schema:
        return {"title": [{"type": "text", "text": {"content": str(value)}}]}
    if "rich_text" in schema:
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
    if "number" in schema:
        try: return {"number": float(value)}
        except Exception: return None
    if "url" in schema:
        return {"url": str(value)}
    if "select" in schema:
        return {"select": {"name": str(value)}}
    if "date" in schema:
        return {"date": {"start": str(value)}}
    return None

def _is_empty(prop: Dict[str, Any]) -> bool:
    if not prop: return True
    if "title" in prop:     return len(prop.get("title", [])) == 0
    if "rich_text" in prop: return len(prop.get("rich_text", [])) == 0
    if "number" in prop:    return prop.get("number") is None
    if "url" in prop:       return not prop.get("url")
    if "select" in prop:    return prop.get("select") is None
    return True

ORDER = [
    "Title","Author","Publisher","Language","Description",
    "Number of Pages","Year Published","ISBN13","coverURL","Cover URL","goodreadsURL"
]

def build_updates(schema: Dict[str, Any], data: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    for key in ORDER:
        if key not in schema: 
            continue
        if not OVERWRITE and not _is_empty(current.get(key)):
            continue
        enc = _enc(schema[key], data.get(key))
        if enc:
            updates[key] = enc
    if "LastSynced" in schema:
        updates["LastSynced"] = {"date": {"start": now_iso()}}
    return updates

def query_targets() -> Dict[str, Any]:
    c = client()
    return c.databases.query(
        database_id=DATABASE_ID,
        filter={
            "and":[
                {"property":"goodreadsURL","url":{"is_not_empty":True}},
                # >>> sadece gerçek kitap sayfası:
                {"property":"goodreadsURL","url":{"contains":"/book/show/"}},
                {"or":[
                    {"property":"Title","title":{"is_empty":True}},
                    {"property":"Author","rich_text":{"is_empty":True}},
                ]}
            ]
        },
        page_size=100,
    )

def update_page(page_id: str, data: Dict[str, Any]):
    c = client()
    page   = c.pages.retrieve(page_id=page_id)
    schema = page["properties"]

    updates = build_updates(schema, data, current=schema)

    # Kapak (Cover URL / coverURL ikisi de destek)
    cover_url = data.get("Cover URL") or data.get("coverURL")
    cover_payload = {}
    if cover_url and (page.get("cover") is None or OVERWRITE):
        cover_payload = {"cover": {"type": "external", "external": {"url": str(cover_url)}}}

    if updates or cover_payload:
        c.pages.update(page_id=page_id, properties=updates or {}, **cover_payload)
