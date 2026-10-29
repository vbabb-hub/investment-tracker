import os
import json
from datetime import datetime
import yfinance as yf
import urllib.request
import urllib.parse

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req) as response:
            pass
    except Exception as e:
        print(f"Errore Telegram: {e}")

def calculate_rsi(series, period=14):
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1)

def get_rsi_status(rsi):
    if rsi >= 75:
        return "Ipercomprato Estremo 🔴"
    elif rsi >= 70:
        return "Ipercomprato 🟠"
    elif rsi <= 25:
        return "Ipervenduto Estremo 🟢"
    elif rsi <= 30:
        return "Ipervenduto 🔵"
    return "Neutro ⚪"

def scan_market():
    # Carica la watchlist dei candidati da scansionare
    if not os.path.exists("data/watchlist.json"):
        print("Watchlist non trovata.")
        return

    with open("data/watchlist.json", "r") as f:
        watchlist = json.load(f)

    # Carica lo storico precedente per mantenere i suggerimenti già attivi o tracciati
    old_items = {}
    if os.path.exists("data/history.json"):
        try:
            with open("data/history.json", "r") as f:
                old_data = json.load(f)
                for item in old_data.get("items", []):
                    old_items[item["ticker"]] = item
        except Exception:
            pass

    results = []
    updated_at = datetime.utcnow().isoformat() + "Z"
    alerts_to_send = []

    for item in watchlist:
        ticker_symbol = item["ticker"]
        category = item["category"]

        try:
            ticker = yf.Ticker(ticker_symbol)

            # Filtro capitalizzazione (> 1B) per le azioni USA
            if category == "AZIONI":
                info = ticker.info
                market_cap = info.get("marketCap", 0)
                if market_cap and market_cap < 1_000_000_000:
                    print(f"Skipping {ticker_symbol}: Market Cap < 1B ({market_cap})")
                    continue

            hist_day = ticker.history(period="1d")
            if hist_day.empty:
                continue

            current_price = round(float(hist_day["Close"].iloc[-1]), 2)
            currency = "USD" # Default per US/Crypto

            rsi_signals = {}
            intervals = {"1h": "60m", "1d": "1d", "1wk": "1wk"}
            periods = {"1h": "5d", "1d": "6mo", "1wk": "2y"}

            is_interesting = False

            for tf_key, tf_val in intervals.items():
                hist_tf = ticker.history(period=periods[tf_key], interval=tf_val)
                if not hist_tf.empty and len(hist_tf) > 15:
                    rsi_val = calculate_rsi(hist_tf["Close"])
                    status = get_rsi_status(rsi_val)
                    rsi_signals[tf_key] = {"rsi": rsi_val, "status": status}

                    # Condizione di attivazione automatica del consiglio basata su RSI critico
                    if "Ipervenduto" in status or "Ipercomprato" in status:
                        is_interesting = True

            # Se il titolo era già tracciato o rispetta i criteri RSI, lo inseriamo nei risultati attivi
            if ticker_symbol in old_items or is_interesting:
                entry_price = old_items.get(ticker_symbol, {}).get("entry_price", current_price)
                entry_date = old_items.get(ticker_symbol, {}).get("entry_date", datetime.utcnow().strftime("%Y-%m-%d"))
                roi_pct = round(((current_price - entry_price) / entry_price) * 100, 2)

                # Se è un nuovo inserimento per segnale RSI
                if ticker_symbol not in old_items and is_interesting:
                    alert_msg = (
                        f"🎯 *Nuovo Segnale d'Acquisto Scovato!*\n"
                        f"Asset: *{item['name']}* (`{ticker_symbol}`)\n"
                        f"Prezzo Intercettato: {current_price} {currency}\n"
                        f"RSI segnali attivi sul mercato."
                    )
                    alerts_to_send.append(alert_msg)

                results.append({
                    "id": f"sug_{ticker_symbol.lower().replace('-','_')}",
                    "ticker": ticker_symbol,
                    "name": item["name"],
                    "category": category,
                    "entry_date": entry_date,
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "currency": currency,
                    "roi_pct": roi_pct,
                    "rsi_signals": rsi_signals
                })

        except Exception as e:
            print(f"Errore elaborazione {ticker_symbol}: {e}")

    for msg in alerts_to_send:
        send_telegram_alert(msg)

    output = {"last_updated": updated_at, "items": results}
    with open("data/history.json", "w") as f:
        json.dump(output, f, indent=2)

if __name__ == "__main__":
    scan_market()
