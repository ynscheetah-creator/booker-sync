import os
from typing import Dict, Any
from notion_client import Client
from utils import now_iso

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

def notion_client() -> Client:
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_TOKEN missing")
    return Client(auth=NOTION_TOKEN)

def _is_empty(prop: Dict[str, Any]) -> bool:
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

def _encode_value_for(prop: Dict[str, Any], value):
    # Prop tipine göre doğru JSON şeması döndür
    if value in (None, ""):
        return None
    if "title" in prop:
        return {"title": [{"type": "text", "text": {"content": str(value)}}]}
    if "rich_text" in prop:
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
    if "number" in prop:
        try:
            return {"number": int(value)}
        except Exception:
            return None
    if "url" in prop:
        return {"url": str(value)}
    if "select" in prop:
        return {"select": {"name": str(value)}}
    if "date" in prop:
        return {"date": {"start": str(value)}}
    return None

def update_page(page_id: str, data: Dict[str, Any]):
    c = notion_client()
    page = c.pages.retrieve(page_id=page_id)
    props = page["properties"]

    updates: Dict[str, Any] = {}

    # Şu alanları işlemeye çalış
    fields = [
        ("Title", data.get("Title")),
        ("Author", data.get("Author")),
        ("Translator", data.get("Translator")),
        ("Publisher", data.get("Publisher")),
        ("Number of Pages", data.get("Number of Pages")),
        ("coverURL", data.get("coverURL")),
        ("Year Published", data.get("Year Published")),
        ("Language", data.get("Language")),
        ("Description", data.get("Description")),
    ]
    for key, val in fields:
        if key in props and _is_empty(props[key]):
            enc = _encode_value_for(props[key], val)
            if enc:
                updates[key] = enc

    # LastSynced -> her zaman güncelle
    if "LastSynced" in props:
        updates["LastSynced"] = {"date": {"start": now_iso()}}

    if updates:
        c.pages.update(page_id=page_id, properties=updates)

def query_targets(limit: int = 100):
    # Filtre yok; URL olmayanları main.py zaten atlıyor
    c = notion_client()
    return c.databases.query(database_id=DATABASE_ID, page_size=limit)
