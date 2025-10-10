import re
import json
import html
from typing import Dict, Optional
import requests
from bs4 import BeautifulSoup

# Dışarıdan USER_AGENT .env / GitHub Secret ile gelmeli (workflow öyle ayarlı)
from utils import get_user_agent

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": get_user_agent()})

# Yardımcılar
def _clean(txt: Optional[str]) -> Optional[str]:
    if not txt:
        return None
    t = html.unescape(txt).strip()
    # Goodreads bazı alanlarda “=”” ... ”” gibi export formatına yakın dize üretir; normalize edelim
    t = t.replace("\xa0", " ").replace("\u200b", "").strip()
    return t or None

def _only_digits(txt: Optional[str]) -> Optional[str]:
    if not txt:
        return None
    m = re.search(r"(\d+)", txt)
    return m.group(1) if m else None

def _meta(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find("meta", {"property": prop}) or soup.find("meta", {"name": prop})
    return _clean(tag.get("content")) if tag and tag.get("content") else None

def _first_text(soup: BeautifulSoup, selector: str) -> Optional[str]:
    el = soup.select_one(selector)
    return _clean(el.get_text(" ", strip=True)) if el else None

def _jsonld(soup: BeautifulSoup) -> Dict:
    out = {}
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "{}")
        except Exception:
            continue
        # Bazı sayfalarda Liste dönebiliyor
        if isinstance(data, list):
            for d in data:
                if isinstance(d, dict) and d.get("@type") in {"Book", "CreativeWork"}:
                    out.update(d)
        elif isinstance(data, dict) and data.get("@type") in {"Book", "CreativeWork"}:
            out.update(data)
    return out

# TR/EN etiket haritası (detay kutularında “infoBoxRowTitle” alanı)
LABEL_MAP = {
    # publisher
    "publisher": "Publisher",
    "yayıncı": "Publisher",
    "yayınevi": "Publisher",
    # year published (genelde “Published … 1952” veya TR’de “Yayın tarihi … 1952”)
    "published": "Year Published",
    "yayın tarihi": "Year Published",
    "basım tarihi": "Year Published",
    # original title / original publication year
    "original title": "Original Title",
    "orijinal adı": "Original Title",
    "orijinal ad": "Original Title",
    "original publication year": "Original Publication Year",
    "orijinal yayın yılı": "Original Publication Year",
    # number of pages
    "pages": "Number of Pages",
    "sayfa": "Number of Pages",
    # language
    "language": "Language",
    "dil": "Language",
    # isbn
    "isbn": "ISBN",
    "isbn13": "ISBN13",
}

def _normalize_label(raw: str) -> str:
    key = raw.strip().lower()
    # iki kelimeli eşleşmeleri kolaylaştır
    key = key.replace(":", "").replace("  ", " ")
    return LABEL_MAP.get(key, raw)

def _parse_details_box(soup: BeautifulSoup) -> Dict[str, str]:
    """
    Sağ taraftaki “Book details / Detaylar” kutusundan (infoBox) değerleri oku.
    Goodreads teması zamanla değişebildiği için hem eski hem yeni sınıfları dener.
    """
    out: Dict[str, str] = {}

    # 1) Eski “bookDataBox”
    for row in soup.select("#bookDataBox .clearFloats"):
        label_el = row.select_one(".infoBoxRowTitle")
        value_el = row.select_one(".infoBoxRowItem")
        if not label_el or not value_el:
            continue
        label = _normalize_label(label_el.get_text(" ", strip=True))
        value = _clean(value_el.get_text(" ", strip=True))
        if not label or not value:
            continue

        if label in {"ISBN", "ISBN13"}:
            # ISBN alanlarında bazen “978975768427 (ISBN13: 978975…)” gibi ek yazılar oluyor
            value = value.replace("ISBN13:", "").strip()
            value = re.sub(r"[^\dXx\- ]", "", value)  # harf kalsın (X) ama gürültüyü at
            value = value.replace(" ", "")
        elif label == "Number of Pages":
            value = _only_digits(value)
        out[label] = value

    # 2) Yeni “Details” / #details alanı – microdata
    # Sayfa sayısı
    val = _first_text(soup, "#details span[itemprop='numberOfPages']")
    if val and "Number of Pages" not in out:
        out["Number of Pages"] = _only_digits(val)

    # Yayın yılı (datePublished)
    # Bazı sayfalarda #details içinde role=contentinfo bölgesinde geçiyor
    date_pub = _first_text(soup, "#details span[itemprop='datePublished']") or \
               _first_text(soup, "#details div:contains('Published')")
    if date_pub:
        # sadece yıl
        y = re.search(r"(20\d{2}|19\d{2})", date_pub)
        if y and "Year Published" not in out:
            out["Year Published"] = y.group(1)

    # Dil
    lang = _first_text(soup, "#details div[itemprop='inLanguage'], #details span[itemprop='inLanguage']")
    if lang and "Language" not in out:
        out["Language"] = lang

    # Publisher (microdata ile)
    pub = _first_text(soup, "#details [itemprop='publisher'] [itemprop='name'], #details [itemprop='publisher']")
    if pub and "Publisher" not in out:
        out["Publisher"] = pub

    return out

def fetch_goodreads(url: str) -> Dict[str, Optional[str]]:
    # URL normalize / Book Id çıkar
    m = re.search(r"/book/show/(\d+)", url)
    book_id = m.group(1) if m else None

    r = SESSION.get(url, timeout=25)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    # Önce JSON-LD (varsa)
    ld = _jsonld(soup)

    # ---------- Title ----------
    title = ld.get("name") if isinstance(ld.get("name"), str) else None
    if not title:
        title = _meta(soup, "og:title") \
            or _first_text(soup, "h1#bookTitle, h1.Text__title1, h1.BookPageTitleSection__title")
    title = _clean(title)

    # ---------- Author ----------
    # JSON-LD
    author = None
    if isinstance(ld.get("author"), dict):
        author = ld["author"].get("name")
    elif isinstance(ld.get("author"), list) and ld["author"]:
        # ilk yazar
        a0 = ld["author"][0]
        if isinstance(a0, dict):
            author = a0.get("name")
    # Microdata / eski şablon
    if not author:
        author = _first_text(soup, "a.authorName span[itemprop='name'], a.ContributorLink, span[itemprop='author'] [itemprop='name']")

    # ---------- Cover ----------
    cover = _meta(soup, "og:image") or _first_text(soup, "img#coverImage") or _first_text(soup, "img.BookCover__image")
    # Eğer metinden geldiyse <img> için src alalım
    if cover and cover.startswith(("http", "https")) is False:
        img = soup.select_one("img#coverImage, img.BookCover__image")
        if img and img.get("src"):
            cover = img["src"]

    # ---------- Detay kutuları ----------
    details = _parse_details_box(soup)

    # Dil yoksa TR/EN içeriğe göre tahmin (best-effort)
    if not details.get("Language"):
        # sayfa Türkçe ise gövde içinde “Sayfa” veya “Yayın tarihi” geçer
        body_txt = soup.get_text(" ", strip=True).lower()
        if " yay" in body_txt or "sayfa" in body_txt or "orijinal adı" in body_txt:
            details["Language"] = "Turkish"

    # ---------- ISBN / ISBN13 – JSON-LD fallback ----------
    if not details.get("ISBN") and isinstance(ld.get("isbn"), str):
        details["ISBN"] = _clean(ld["isbn"])
    if not details.get("ISBN13") and isinstance(ld.get("isbn13"), str):
        details["ISBN13"] = _clean(ld["isbn13"])

    # ---------- Year Published – JSON-LD fallback ----------
    if not details.get("Year Published") and isinstance(ld.get("datePublished"), str):
        y = re.search(r"(20\d{2}|19\d{2})", ld["datePublished"])
        if y:
            details["Year Published"] = y.group(1)

    # ---------- Sonuç ----------
    return {
        "goodreadsURL": url,
        "Book Id": book_id,
        "Title": title,
        "Author": author,
        "Publisher": details.get("Publisher"),
        "Year Published": details.get("Year Published"),
        "Original Publication Year": details.get("Original Publication Year"),
        "Number of Pages": details.get("Number of Pages"),
        "Language": details.get("Language"),
        "ISBN": details.get("ISBN"),
        "ISBN13": details.get("ISBN13"),
        "Cover URL": cover,
    }
