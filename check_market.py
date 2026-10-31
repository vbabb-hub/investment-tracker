import os
import json
import html
import urllib.request
from datetime import datetime, timezone

# Credenziali dai Secrets di GitHub (accetta entrambi i nomi usati nei workflow)
TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
THRESHOLD = int(os.environ.get("ALERT_THRESHOLD") or 70)   # stessa soglia dello score in fetch_performance.py
MAX_ITEMS = 10
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "history.json")


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as response:
            return response.status == 200
    except Exception as e:
        print(f"Errore durante l'invio su Telegram: {e}")
        return False


def fallback_note(item):
    parts = [f"RSI {tf.upper()} {s['status']} ({s['rsi']})"
             for tf, s in item.get("rsi_signals", {}).items() if not s["status"].startswith("Neutro")]
    return " • ".join(parts) or "Segnale combinato di score elevato"


def main():
    if not TOKEN or not CHAT_ID:
        raise SystemExit("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID non configurati nei Secrets.")
    if not os.path.exists(DATA_FILE):
        raise SystemExit("data/history.json non trovato.")

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    top = sorted((i for i in data.get("items", []) if i.get("score", 0) >= THRESHOLD),
                 key=lambda i: i["score"], reverse=True)[:MAX_ITEMS]
    if not top:
        print(f"Nessun titolo con score >= {THRESHOLD}.")
        return

    msg = f"🚨 <b>Opportunità di acquisto (score ≥ {THRESHOLD})</b>\n"
    try:
        upd = datetime.fromisoformat(data["last_updated"].replace("Z", "+00:00"))
        age_h = (datetime.now(timezone.utc) - upd).total_seconds() / 3600
        msg += f"<i>Dati aggiornati {upd.strftime('%d/%m %H:%M')} UTC</i>"
        if age_h > 6:
            msg += f" ⚠️ <i>({age_h:.0f}h fa)</i>"
        msg += "\n"
    except Exception:
        pass
    msg += "\n"

    for i in top:
        cur = "€" if i.get("currency") == "EUR" else "$"
        note = i.get("note") or fallback_note(i)
        msg += f"• <b>{html.escape(i['name'])} ({html.escape(i['ticker'])})</b>\n"
        msg += f"  Score: <b>{i['score']}/100</b> | Prezzo: {i['current_price']}{cur}\n"
        msg += f"  {html.escape(note)}\n\n"

    print("Notifica inviata." if send_telegram(msg) else "Invio fallito.")


if __name__ == "__main__":
    main()
