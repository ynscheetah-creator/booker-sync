# main.py
from notion_sync import run_once
import sys
import traceback


if __name__ == "__main__":
    try:
        run_once()
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
