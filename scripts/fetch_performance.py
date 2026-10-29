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
        print("Credenziali Telegram non configurate. Salto l'invio.")
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
            if response.status != 200:
                print(f"Errore invio Telegram: {response.read().decode()}")
    except Exception as e:
        print(f"Eccezione invio notifica Telegram: {e}")

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

def fetch_market_data():
    old_signals = {}
    if os.path.exists("data/history.json"):
        try:
            with open("data/history.json", "r") as f:
                old_data = json.load(f)
                for item in old_data.get("items", []):
                    old_signals[item["ticker"]] = item.get("rsi_signals", {})
        except Exception:
            pass

    with open("data/suggestions.json", "r") as f:
        suggestions = json.load(f)

    results = []
    updated_at = datetime.utcnow().isoformat() + "Z"
    alerts_to_send = []

    for item in suggestions:
        ticker_symbol = item["ticker"]
        entry_price = item["entry_price"]
        category = item["category"]
        
        current_price = entry_price
        roi_pct = 0.0
        rsi_signals = {}

        try:
            ticker = yf.Ticker(ticker_symbol)
            
            # Filtro capitalizzazione di mercato (> 1B) per le azioni USA
            if category == "AZIONI":
                info = ticker.info
                market_cap = info.get("marketCap", 0)
                if market_cap and market_cap < 1_000_000_000:
                    print(f"Skipping {ticker_symbol}: Market Cap sotto 1B.")
                    continue

            hist_day = ticker.history(period="1d")
            if not hist_day.empty:
                current_price = round(float(hist_day["Close"].iloc[-1]), 2)
                roi_pct = round(((current_price - entry_price) / entry_price) * 100, 2)

            if category in ["AZIONI", "CRYPTO"]:
                intervals = {"1h": "60m", "1d": "1d", "1wk": "1wk"}
                periods = {"1h": "5d", "1d": "6mo", "1wk": "2y"}
                
                for tf_key, tf_val in intervals.items():
                    hist_tf = ticker.history(period=periods[tf_key], interval=tf_val)
                    if not hist_tf.empty and len(hist_tf) > 15:
                        rsi_val = calculate_rsi(hist_tf["Close"])
                        status = get_rsi_status(rsi_val)
                        rsi_signals[tf_key] = {"rsi": rsi_val, "status": status}
                        
                        old_status = old_signals.get(ticker_symbol, {}).get(tf_key, {}).get("status")
                        if status != old_status and ("Ipervenduto" in status or "Ipercomprato" in status):
                            alert_msg = (
                                f"🔔 *Alert RSI [{tf_key}]*\n"
                                f"Asset: *{item['name']}* (`{ticker_symbol}`)\n"
                                f"Fase: *{status}*\n"
                                f"Valore RSI: `{rsi_val}`\n"
                                f"Prezzo: {current_price} {item['currency']} (ROI: {roi_pct}%)"
                            )
                            alerts_to_send.append(alert_msg)

        except Exception as e:
            print(f"Errore {ticker_symbol}: {e}")

        results.append({
            "id": item["id"],
            "ticker": item["ticker"],
            "name": item["name"],
            "category": item["category"],
            "entry_date": item["entry_date"],
            "entry_price": item["entry_price"],
            "current_price": current_price,
            "currency": item["currency"],
            "roi_pct": roi_pct,
            "rsi_signals": rsi_signals
        })

    for msg in alerts_to_send:
        send_telegram_alert(msg)

    output = {"last_updated": updated_at, "items": results}
    with open("data/history.json", "w") as f:
        json.dump(output, f, indent=2)

if __name__ == "__main__":
    fetch_market_data()
