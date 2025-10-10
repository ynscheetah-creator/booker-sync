# google_books_api.py
import requests
from typing import Dict, Optional
import time
import re


def fetch_from_google_books(title: str = None, author: str = None, isbn: str = None) -> Dict[str, Optional[str]]:
    """Google Books API'den kitap bilgisi çek"""
    
    if isbn:
        query = f"isbn:{isbn}"
    elif title and author:
        query = f'intitle:"{title}" inauthor:"{author}"'
    elif title:
        query = f'intitle:"{title}"'
    else:
        return {}
    
    api_url = "https://www.googleapis.com/books/v1/volumes"
    params = {"q": query, "maxResults": 1}
    
    try:
        time.sleep(0.5)
        res = requests.get(api_url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        if data.get("totalItems", 0) == 0:
            return {}
        
        item = data["items"][0]
        info = item.get("volumeInfo", {})
        
        # ISBN çek
        isbn_10 = None
        isbn_13 = None
        for identifier in info.get("industryIdentifiers", []):
            if identifier["type"] == "ISBN_10":
                isbn_10 = identifier["identifier"]
            elif identifier["type"] == "ISBN_13":
                isbn_13 = identifier["identifier"]
        
        # Cover URL (büyük resim)
        cover = None
        if info.get("imageLinks"):
            cover = info["imageLinks"].get("thumbnail", "").replace("zoom=1", "zoom=2")
        
        # Description (HTML temizle)
        description = info.get("description")
        if description:
            # HTML taglerini temizle
            description = re.sub(r'<[^>]+>', '', description)
            # Notion text limiti: 2000 karakter
            description = description[:2000]
        
        return {
            "Title": info.get("title"),
            "Author": ", ".join(info.get("authors", [])) if info.get("authors") else None,
            "Publisher": info.get("publisher"),
            "Year Published": info.get("publishedDate", "")[:4] if info.get("publishedDate") else None,
            "Number of Pages": str(info.get("pageCount")) if info.get("pageCount") else None,
            "Language": info.get("language"),
            "ISBN": isbn_10,
            "ISBN13": isbn_13,
            "Average Rating": str(info.get("averageRating")) if info.get("averageRating") else None,
            "Cover URL": cover,
            "Description": description,
        }
    except Exception as e:
        print(f"  ⚠️  Google Books error: {e}")
        return {}
