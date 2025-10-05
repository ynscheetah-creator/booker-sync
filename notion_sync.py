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

def _set_if_empty(props: Dict[str, Any], key: str, value):
    if value in (None, ""):
        return
    if key not in props:
        return
    curr = props[key]
    is_empty = False
    if "title" in curr:
        is_empty = len(curr.get("title", [])) == 0
        if is_empty:
            curr["title"] = [{"type": "text", "text": {"content": str(value)}}]
    elif "rich_text" in curr:
        is_empty = len(curr.get("rich_text", [])) == 0
        if is_empty:
            curr["rich_text"] = [{"type": "text", "text": {"content": str(value)}}]
    elif "number" in curr:
        is_empty = curr.get("number") in (None,)
        if is_empty:
            curr["number"] = int(value)
    elif "url" in curr:
        is_empty = curr.get("url") in (None, "")
        if is_empty:
            curr["url"] = str(value)
    elif "select" in curr:
        is_empty = curr.get("select") in (None,)
        if is_empty:
            curr["select"] = {"name": str(value)}

def update_page(page_id: str, data: Dict[str, Any]):
    c = notion_client()
    page = c.pages.retrieve(page_id=page_id)
    props = page["properties"].copy()

    _set_if_empty(props, "Title", data.get("Title"))
    _set_if_empty(props, "Author", data.get("Author"))
    _set_if_empty(props, "Translator", data.get("Translator"))
    _set_if_empty(props, "Publisher", data.get("Publisher"))
    _set_if_empty(props, "Number of Pages", data.get("Number of Pages"))
    _set_if_empty(props, "coverURL", data.get("coverURL"))
    _set_if_empty(props, "Year Published", data.get("Year Published"))
    _set_if_empty(props, "Language", data.get("Language"))
    _set_if_empty(props, "Description", data.get("Description"))

    if "LastSynced" in props:
        props["LastSynced"] = {"date": {"start": now_iso()}}

    c.pages.update(page_id=page_id, properties=props)

def query_targets(limit: int = 50):
    c = notion_client()
    flt = {
        "or": [
            {"property": "1000kitapURL", "url": {"is_not_empty": True}},
            {"property": "goodreadsURL", "url": {"is_not_empty": True}},
        ]
    }
    return c.databases.query(database_id=DATABASE_ID, filter=flt, page_size=limit)
