from datetime import datetime, timezone

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def blocks_to_text(blocks):
    if not blocks: return ""
    return "".join([b.get("plain_text","") for b in blocks]).strip()
