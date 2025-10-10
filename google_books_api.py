# google_books_api.py
import requests
from typing import Dict, Optional
import time
import re


def fetch_from_google_books(
    title: str = None, 
    author: str = None, 
    isbn: str = None,
    language: str = None  # YENİ: "tr" için Türkçe
) -> Dict[str, Optional[str]]:
    """Google Books API'den kitap bilgisi çek"""
    
    if isbn:
        query = f"isbn:{isbn}"
    elif title and author:
        query = f'intitle:"{title}" inauthor:"{author}"'
        # Dil filtresi ekle
        if language:
            query += f" inlanguage:{language}"
    elif title:
        query = f'intitle:"{title}"'
        if language:
            query += f" inlanguage:{language}"
    else:
        return {}
    
    api_url = "https://www.googleapis.com/books/v1/volumes"
    params = {
        "q": query, 
        "maxResults": 3  # Birden fazla sonuç al
    }
    
    # Dil tercihi varsa parametre ekle
    if language:
        params["langRestrict"] = language
    
    try:
        time.sleep(0.5)
        res = requests.get(api_url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        if data.get("totalItems", 0) == 0:
            return {}
        
        # İlk uygun sonucu bul (Türkçe yayınevli vs.)
        turkish_publishers = [
            "İş Bankası", "Can Yayınları", "Yapı Kredi", 
            "İletişim", "Doğan Kitap", "Everest", "Epsilon",
            "Alfa", "Türkiye İş Bankası", "Metis", "YKY"
        ]
        
        best_match = None
        for item in data.get("items", []):
            info = item.get("volumeInfo", {})
            publisher = info.get("publisher", "")
            lang = info.get("language", "")
            
            # Türkçe yayınevi varsa öncelikle seç
            if any(tp in publisher for tp in turkish_publishers):
                best_match = item
                break
            # Dil Türkçe ise seç
            elif lang == "tr":
                best_match = item
                break
        
        # Hiçbiri yoksa ilk sonucu al
        if not best_match:
            best_match = data["items"][0]
        
        info = best_match.get("volumeInfo", {})
        
        # ISBN çek
        isbn_10 = None
        isbn_13 = None
        for identifier in info.get("industryIdentifiers", []):
            if identifier["type"] == "ISBN_10":
                isbn_10 = identifier["identifier"]
            elif identifier["type"] == "ISBN_13":
                isbn_13 = identifier["identifier"]
        
        # Cover URL
        cover = None
        if info.get("imageLinks"):
            cover = info["imageLinks"].get("thumbnail", "").replace("zoom=1", "zoom=2")
        
        # Description (HTML temizle)
        description = info.get("description")
        if description:
            description = re.sub(r'<[^>]+>', '', description)
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
