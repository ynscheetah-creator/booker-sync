import requests
from typing import Dict, Optional

def fetch_google_books(query: str, user_agent: Optional[str] = None) -> Dict:
    """Search by title or ISBN via Google Books API"""
    if not query:
        return {}
    headers = {"User-Agent": user_agent or "Mozilla/5.0"}
    url = f"https://www.googleapis.com/books/v1/volumes?q={query}"
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code != 200:
        return {}

    j = r.json()
    items = j.get("items") or []
    if not items:
        return {}

    v = items[0].get("volumeInfo", {})
    lang = (v.get("language") or "").upper() if v.get("language") else None
    year = None
    if isinstance(v.get("publishedDate"), str) and v["publishedDate"][:4].isdigit():
        year = int(v["publishedDate"][:4])
    cover = None
    if isinstance(v.get("imageLinks"), dict):
        cover = v["imageLinks"].get("thumbnail") or v["imageLinks"].get("smallThumbnail")

    return {
        "Title": v.get("title"),
        "Author": ", ".join(v.get("authors", [])) if v.get("authors") else None,
        "Publisher": v.get("publisher"),
        "Year Published": year,
        "Number of Pages": v.get("pageCount"),
        "coverURL": cover,
        "Language": lang,
        "Description": v.get("description"),
        "source": "googlebooks",
    }
