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
    if not os.path.exists("data/watchlist.json"):
        print("Watchlist non trovata.")
        return

    with open("data/watchlist.json", "r") as f:
        watchlist = json.load(f)

    old_data = {}
    if os.path.exists("data/history.json"):
        try:
            with open("data/history.json", "r") as f:
                old_data = json.load(f)
        except Exception:
            pass

    old_items = {item["ticker"]: item for item in old_data.get("items", [])}
    paper_portfolio = old_data.get("paper_portfolio", [])
    active_paper_trades = {trade["ticker"]: trade for trade in paper_portfolio}

    results = []
    updated_at = datetime.utcnow().isoformat() + "Z"
    alerts_to_send = []

    for item in watchlist:
        ticker_symbol = item["ticker"]
        category = item["category"]

        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info

            if category == "AZIONI":
                market_cap = info.get("marketCap", 0)
                if market_cap and market_cap < 1_000_000_000:
                    continue

            hist_day = ticker.history(period="1d")
            if hist_day.empty:
                continue

            current_price = round(float(hist_day["Close"].iloc[-1]), 2)
            currency = "USD"

            pe_ratio = info.get("trailingPE") or info.get("forwardPE")
            pe_ratio = round(float(pe_ratio), 1) if pe_ratio else None

            high_52w = info.get("fiftyTwoWeekHigh")
            dist_52w_pct = None
            if high_52w and high_52w > 0:
                dist_52w_pct = round(((current_price - high_52w) / high_52w) * 100, 1)

            rsi_signals = {}
            intervals = {"1h": "60m", "1d": "1d", "1wk": "1wk"}
            periods = {"1h": "5d", "1d": "6mo", "1wk": "2y"}

            is_oversold = False

            for tf_key, tf_val in intervals.items():
                hist_tf = ticker.history(period=periods[tf_key], interval=tf_val)
                if not hist_tf.empty and len(hist_tf) > 15:
                    rsi_val = calculate_rsi(hist_tf["Close"])
                    status = get_rsi_status(rsi_val)
                    rsi_signals[tf_key] = {"rsi": rsi_val, "status": status}

                    if "Ipervenduto" in status:
                        is_oversold = True

            if is_oversold and ticker_symbol not in active_paper_trades:
                invested_usd = 100.0
                shares = round(invested_usd / current_price, 4)
                buy_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
                
                new_trade = {
                    "id": f"trade_{ticker_symbol.lower()}",
                    "ticker": ticker_symbol,
                    "name": item["name"],
                    "buy_date": buy_date,
                    "buy_price": current_price,
                    "invested": invested_usd,
                    "shares": shares,
                    "current_price": current_price,
                    "current_value": invested_usd,
                    "pnl_pct": 0.0,
                    "pnl_usd": 0.0
                }
                active_paper_trades[ticker_symbol] = new_trade
                alerts_to_send.append(
                    f"🟢 *Simulazione Acquisto (100$)*\n"
                    f"Asset: *{item['name']}* (`{ticker_symbol}`)\n"
                    f"Prezzo di ingresso: {current_price} {currency} (RSI in ipervenduto)"
                )
            elif ticker_symbol in active_paper_trades:
                trade = active_paper_trades[ticker_symbol]
                current_value = round(trade["shares"] * current_price, 2)
                pnl_usd = round(current_value - trade["invested"], 2)
                pnl_pct = round((pnl_usd / trade["invested"]) * 100, 2)
                
                trade["current_price"] = current_price
                trade["current_value"] = current_value
                trade["pnl_usd"] = pnl_usd
                trade["pnl_pct"] = pnl_pct

            results.append({
                "id": f"sug_{ticker_symbol.lower().replace('-','_')}",
                "ticker": ticker_symbol,
                "name": item["name"],
                "category": category,
                "current_price": current_price,
                "currency": currency,
                "pe_ratio": pe_ratio,
                "dist_52w_pct": dist_52w_pct,
                "rsi_signals": rsi_signals
            })

        except Exception as e:
            print(f"Errore elaborazione {ticker_symbol}: {e}")

    for msg in alerts_to_send:
        send_telegram_alert(msg)

    updated_portfolio = list(active_paper_trades.values())

    output = {
        "last_updated": updated_at,
        "items": results,
        "paper_portfolio": updated_portfolio
    }

    with open("data/history.json", "w") as f:
        json.dump(output, f, indent=2)

if __name__ == "__main__":
    scan_market()
