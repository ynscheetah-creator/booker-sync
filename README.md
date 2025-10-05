# Booker Sync — 1000Kitap & Goodreads → Notion
Notion veritabanınıza 1000Kitap **veya** Goodreads bağlantısı eklediğinizde
*Başlık, Yazar, Çevirmen, Yayınevi, Sayfa Sayısı, Kapak URL, Yayın Yılı,
**Dil (Language)** ve **Açıklama (Description)** alanlarını otomatik doldurur.

## Kurulum (lokalde)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # düzenleyin
python -m src.main
```

## Notion sütunları
- `1000kitapURL` (URL), `goodreadsURL` (URL)
- `Title` (Title), `Author` (Rich text), `Translator` (Rich text)
- `Publisher` (Rich text), `Number of Pages` (Number), `coverURL` (URL)
- `Year Published` (Number), `Language` (Select veya Rich text), `Description` (Rich text)
- `LastSynced` (Date) — otomatik dolacak

> Dikkat: Betik yalnızca **boş** alanları doldurur; dolu alanlara dokunmaz.

## GitHub Actions
Workflow dosyası `.github/workflows/sync.yml` içindedir.
Repository *Secrets* içine şu anahtarları ekleyin:
- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`
- `USER_AGENT` (örn. Chrome UA)

Actions > Run workflow ile elle tetikleyebilir, ya da cron ile 15 dk'da bir çalışır.
