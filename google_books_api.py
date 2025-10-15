# google_books_api.py
import requests
from typing import Dict, Optional
import time
import re

def fetch_from_google_books(
    title: str = None, 
    author: str = None, 
    isbn: str = None
) -> Dict[str, Optional[str]]:
    """Google Books API'den kitap bilgisi çeker (Türkçe sonuçlara öncelik vererek)."""
    
    if isbn:
        query = f"isbn:{isbn}"
    elif title and author:
        query = f'intitle:"{title}" inauthor:"{author}"'
    elif title:
        query = f'intitle:"{title}"'
    else:
        return {}
    
    # YENİ: API'ye özellikle Türkçe sonuçları aradığımızı belirtiyoruz
    api_url = "https://www.googleapis.com/books/v1/volumes"
    params = {
        "q": query,
        "maxResults": 5, # Daha fazla sonuç arasından en iyisini seçmek için
        "langRestrict": "tr" # Sadece Türkçe dilindeki kitapları getir
    }
    
    try:
        time.sleep(0.5)
        res = requests.get(api_url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        if data.get("totalItems", 0) == 0:
            # Türkçe sonuç bulunamazsa, bu sefer dil kısıtlaması olmadan tekrar ara
            logging.info("  ℹ️ Google Books'ta Türkçe sonuç bulunamadı, genel arama yapılıyor...")
            del params["langRestrict"]
            res = requests.get(api_url, params=params, timeout=10)
            res.raise_for_status()
            data = res.json()
            if data.get("totalItems", 0) == 0:
                return {}

        # Gelen sonuçlar içinde en uygun olanı seç (örn: bilindik bir Türk yayınevi)
        best_match = data["items"][0] # Varsayılan olarak ilk sonuç
        turkish_publishers = ["can yayınları", "yapı kredi", "yky", "iletişim", "metis", "everest", "kırmızı kedi"]
        for item in data.get("items", []):
            publisher = item.get("volumeInfo", {}).get("publisher", "").lower()
            if any(tp in publisher for tp in turkish_publishers):
                best_match = item
                break
        
        info = best_match.get("volumeInfo", {})
        
        isbn_10, isbn_13 = None, None
        for identifier in info.get("industryIdentifiers", []):
            if identifier["type"] == "ISBN_10": isbn_10 = identifier["identifier"]
            elif identifier["type"] == "ISBN_13": isbn_13 = identifier["identifier"]
        
        cover = info.get("imageLinks", {}).get("thumbnail", "").replace("zoom=1", "zoom=0")
        description = info.get("description")
        if description: description = re.sub(r'<[^>]+>', '', description)[:2000]
        
        return {
            "Title": info.get("title"),
            "Author": ", ".join(info.get("authors", [])),
            "Publisher": info.get("publisher"),
            "Year Published": info.get("publishedDate", "")[:4],
            "Number of Pages": str(info.get("pageCount")),
            "Language": info.get("language"),
            "ISBN": isbn_10,
            "ISBN13": isbn_13,
            "Average Rating": str(info.get("averageRating")),
            "Cover URL": cover,
            "Description": description,
        }
    except Exception as e:
        # logging modülünü import ettiğinizi varsayarak
        try:
            import logging
            logging.warning(f"  ⚠️ Google Books API hatası: {e}")
        except ImportError:
            print(f"  ⚠️ Google Books API hatası: {e}")
        return {}
