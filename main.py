# main.py
import sys
import traceback
import logging
from notion_sync import run_once

def setup_logging():
    """Loglamayı hem dosyaya hem konsola yapacak şekilde ayarlar."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("booker-sync.log", mode='w'), # Her çalıştığında log dosyasını sıfırla
            logging.StreamHandler(sys.stdout)
        ]
    )

if __name__ == "__main__":
    setup_logging()
    try:
        run_once()
    except Exception as e:
        # En üst seviyedeki beklenmedik hataları yakala ve logla
        logging.critical(f"\n❌ PROGRAM DURDURULDU: Beklenmedik bir hata oluştu: {e}")
        logging.critical(traceback.format_exc())
        sys.exit(1)
