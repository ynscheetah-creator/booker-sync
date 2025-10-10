# openlibrary_api.py
import requests
from typing import Dict, Optional
import time


def fetch_from_openlibrary(title: str = None, author: str = None, isbn: str = None) -> Dict[str, Optional[str]]:
    """OpenLibrary API'den kitap bilgisi çek"""
    
    try:
        time.sleep(0.5)
        
        if isbn:
            url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            data = res.json()
            
            key = f"ISBN:{isbn}"
            if key not in data:
                return {}
            
            book = data[key]
            
            # Excerpt (açıklama)
            description = None
            if book.get("excerpts"):
                description = book["excerpts"][0].get("text", "")[:2000]
            
            return {
                "Title": book.get("title"),
                "Author": ", ".join([a["name"] for a in book.get("authors", [])]),
                "Publisher": ", ".join([p["name"] for p in book.get("publishers", [])]) if book.get("publishers") else None,
                "Year Published": str(book.get("publish_date", ""))[:4] if book.get("publish_date") else None,
                "Number of Pages": str(book.get("number_of_pages")) if book.get("number_of_pages") else None,
                "Cover URL": book.get("cover", {}).get("large") if book.get("cover") else None,
                "Description": description,
            }
        
        elif title:
            search_url = "https://openlibrary.org/search.json"
            params = {"title": title, "limit": 1}
            if author:
                params["author"] = author
            
            res = requests.get(search_url, params=params, timeout=10)
            res.raise_for_status()
            search_data = res.json()
            
            if search_data.get("numFound", 0) == 0:
                return {}
            
            doc = search_data["docs"][0]
            
            # First sentence as description
            description = None
            if doc.get("first_sentence"):
                description = ". ".join(doc["first_sentence"])[:2000]
            
            return {
                "Title": doc.get("title"),
                "Author": ", ".join(doc.get("author_name", [])) if doc.get("author_name") else None,
                "Publisher": ", ".join(doc.get("publisher", []))[:200] if doc.get("publisher") else None,
                "Year Published": str(doc.get("first_publish_year")) if doc.get("first_publish_year") else None,
                "Number of Pages": str(doc.get("number_of_pages_median")) if doc.get("number_of_pages_median") else None,
                "ISBN": doc.get("isbn", [None])[0] if doc.get("isbn") else None,
                "Cover URL": f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-L.jpg" if doc.get("cover_i") else None,
                "Description": description,
            }
        
        return {}
        
    except Exception as e:
        print(f"  ⚠️  OpenLibrary error: {e}")
        return {}
