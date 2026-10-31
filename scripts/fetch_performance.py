import os
import json
from datetime import datetime
import numpy as np
import yfinance as yf

ALERT_THRESHOLD = 70      # score minimo per l'alert Telegram (usato anche da check_market.py)
BACKTEST_HORIZON = 20     # giorni di borsa per le statistiche storiche
BACKTEST_RSI_LEVEL = 30   # segnale: RSI 1D che scende sotto questa soglia

def rsi_series(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_rsi(series, period=14):
    if len(series) < period + 1:
        return 50.0
    val = rsi_series(series, period).iloc[-1]
    return 50.0 if val != val else round(float(val), 1)

def compute_trend(close, price):
    """SMA 50/200 sulle chiusure giornaliere. Valori None se lo storico e' troppo corto."""
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
    if sma50 is not None and sma50 != sma50: sma50 = None
    if sma200 is not None and sma200 != sma200: sma200 = None
    return {
        "sma50": round(sma50, 2) if sma50 else None,
        "sma200": round(sma200, 2) if sma200 else None,
        "sma200_dist_pct": round((price - sma200) / sma200 * 100, 1) if sma200 else None,
        "price_above_200": (price > sma200) if sma200 else None,
        "sma50_above_200": (sma50 > sma200) if (sma50 and sma200) else None,
        "price_below_50": (price < sma50) if sma50 else None,
    }

def compute_rel_volume(hist):
    """Volume dell'ultima sessione COMPLETA / media delle 20 sessioni precedenti.
    Se l'ultima barra e' di oggi e la giornata non e' finita (prima delle 21 UTC) usa quella precedente."""
    if "Volume" not in hist or len(hist) < 22:
        return None
    vol = hist["Volume"].astype(float)
    now = datetime.utcnow()
    idx = -2 if (hist.index[-1].date() == now.date() and now.hour < 21) else -1
    last = vol.iloc[idx]
    avg = vol.iloc[idx - 20:idx].mean()
    if last != last or avg != avg or avg <= 0:
        return None
    return round(float(last / avg), 2)

def backtest_rsi_signals(close, horizon=BACKTEST_HORIZON):
    """Per ogni discesa dell'RSI 1D sotto soglia: rendimento % dopo `horizon` sedute e
    se il prezzo era sopra la SMA200 in quel momento. Ritorna lista di (rendimento, trend_up|None)."""
    rsi = rsi_series(close)
    sma200 = close.rolling(200).mean()
    sig = ((rsi <= BACKTEST_RSI_LEVEL) & (rsi.shift(1) > BACKTEST_RSI_LEVEL)).values
    vals = close.values
    out = []
    for pos in np.flatnonzero(sig):
        if pos + horizon >= len(vals):
            continue
        ret = (vals[pos + horizon] / vals[pos] - 1) * 100
        s200 = sma200.iloc[pos]
        out.append((float(ret), None if s200 != s200 else bool(vals[pos] > s200)))
    return out

def summarize_returns(rets):
    if not rets:
        return {"n": 0, "win_rate": None, "avg_ret": None}
    wins = sum(1 for r in rets if r > 0)
    return {"n": len(rets), "win_rate": round(wins / len(rets) * 100, 1), "avg_ret": round(sum(rets) / len(rets), 2)}

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

def calculate_score(rsi_signals, dist_52w, pe_ratio, trend=None, rel_volume=None):
    """Score 0-100 con pesi espliciti. Ritorna (score, parti, note).
    RSI 35 + Trend 25 + Volume 15 + Distanza max 52w 15 + Valutazione 10 = 100.
    Cap a 69 (sotto soglia alert) se il trend ribassato e' confermato (prezzo < SMA200 e SMA50 < SMA200)."""
    trend = trend or {}
    notes = []

    # --- RSI (max 35): 1D pesa di piu', 1W e 1H confermano ---
    r1d = rsi_signals.get("1d", {}).get("rsi", 50)
    r1w = rsi_signals.get("1wk", {}).get("rsi", 50)
    r1h = rsi_signals.get("1h", {}).get("rsi", 50)
    p_1d = 20 if r1d <= 20 else 17 if r1d <= 25 else 13 if r1d <= 30 else 7 if r1d <= 35 else 3 if r1d <= 40 else 0
    p_1w = 8 if r1w <= 30 else 5 if r1w <= 40 else 2 if r1w < 60 else 0
    p_1h = 7 if r1h <= 25 else 5 if r1h <= 30 else 3 if r1h <= 40 else 0
    p_rsi = p_1d + p_1w + p_1h
    for tf, key in (("1D", "1d"), ("1W", "1wk"), ("1H", "1h")):
        sig = rsi_signals.get(key)
        if sig and not sig["status"].startswith("Neutro"):
            notes.append(f"RSI {tf} {sig['status'].split(' ')[0].lower()} ({sig['rsi']})")

    # --- Trend (max 25): un ipervenduto dentro un trend sano vale di piu' ---
    above200 = trend.get("price_above_200")
    golden = trend.get("sma50_above_200")
    below50 = trend.get("price_below_50")
    p_trend = (15 if above200 else 0) if above200 is not None else 8
    p_trend += (6 if golden else 0) if golden is not None else 3
    if above200 and below50:
        p_trend += 4  # ritracciamento sotto la SMA50 ma sopra la SMA200
    d200 = trend.get("sma200_dist_pct")
    if d200 is not None:
        notes.append(f"{'sopra' if d200 >= 0 else 'sotto'} SMA200 ({d200:+.1f}%)")

    # --- Volume relativo (max 15): conta davvero solo vicino all'ipervenduto (capitolazione) ---
    p_vol = 0
    if rel_volume is not None:
        base = 15 if rel_volume >= 2 else 10 if rel_volume >= 1.5 else 5 if rel_volume >= 1 else 0
        p_vol = base if r1d <= 40 else round(base * 0.4)
        if rel_volume >= 1.5:
            notes.append(f"volume {rel_volume:.1f}x la media")

    # --- Distanza dal massimo 52w (max 15) ---
    p_dist = 0
    if dist_52w is not None:
        p_dist = 15 if dist_52w <= -30 else 10 if dist_52w <= -15 else 5 if dist_52w <= -5 else 0
        if dist_52w <= -15:
            notes.append(f"{dist_52w}% dal massimo 52w")

    # --- Valutazione P/E (max 10); neutro (5) per ETF/crypto/futures senza P/E ---
    if pe_ratio is not None and pe_ratio > 0:
        p_val = 10 if pe_ratio < 15 else 7 if pe_ratio < 25 else 3 if pe_ratio < 40 else 0
    else:
        p_val = 5

    score = p_rsi + p_trend + p_vol + p_dist + p_val
    if above200 is False and golden is False and score > ALERT_THRESHOLD - 1:
        score = ALERT_THRESHOLD - 1
        notes.append("trend ribassato confermato: score limitato")

    parts = {"rsi": p_rsi, "trend": p_trend, "volume": p_vol, "distanza_52w": p_dist, "valutazione": p_val}
    return max(0, min(100, int(score))), parts, " • ".join(notes) if notes else "Nessun segnale estremo: situazione neutrale."

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

    paper_portfolio = old_data.get("paper_portfolio", [])
    active_paper_trades = {trade["ticker"]: trade for trade in paper_portfolio}

    dca_portfolio = old_data.get("dca_portfolio", [])
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    results = []
    earnings_calendar = []
    updated_at = datetime.utcnow().isoformat() + "Z"
    current_prices = {}
    all_signals = []

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
            currency = "USD" if "-USD" in ticker_symbol or "=F" in ticker_symbol else "EUR" if (".MI" in ticker_symbol or ".DE" in ticker_symbol) else "USD"
            current_prices[ticker_symbol] = current_price

            pe_ratio = info.get("trailingPE") or info.get("forwardPE")
            pe_ratio = round(float(pe_ratio), 1) if pe_ratio else None

            high_52w = info.get("fiftyTwoWeekHigh")
            dist_52w_pct = None
            if high_52w and high_52w > 0:
                dist_52w_pct = round(((current_price - high_52w) / high_52w) * 100, 1)

            # Calendario
            earnings_date_str = "N/D"
            ex_div_str = "N/D"
            try:
                ed_raw = info.get("earningsTimestamp")
                if ed_raw:
                    earnings_date_str = datetime.utcfromtimestamp(ed_raw).strftime("%Y-%m-%d")
            except Exception:
                pass

            try:
                ex_raw = info.get("exDividendDate")
                if ex_raw:
                    ex_div_str = datetime.utcfromtimestamp(ex_raw).strftime("%Y-%m-%d")
            except Exception:
                pass

            if category in ["AZIONI", "ETF"]:
                earnings_calendar.append({
                    "ticker": ticker_symbol,
                    "name": item["name"],
                    "category": category,
                    "earnings_date": earnings_date_str,
                    "ex_dividend_date": ex_div_str
                })

            rsi_signals = {}
            intervals = {"1h": "60m", "1d": "1d", "1wk": "1wk"}
            periods = {"1h": "5d", "1d": "5y", "1wk": "2y"}

            is_oversold = False
            trigger_reason = "-"
            daily_hist = None

            for tf_key, tf_val in intervals.items():
                try:
                    hist_tf = ticker.history(period=periods[tf_key], interval=tf_val)
                    if not hist_tf.empty and len(hist_tf) > 15:
                        rsi_val = calculate_rsi(hist_tf["Close"])
                        status = get_rsi_status(rsi_val)
                        rsi_signals[tf_key] = {"rsi": rsi_val, "status": status}
                        if tf_key == "1d":
                            daily_hist = hist_tf

                        if "Ipervenduto" in status:
                            is_oversold = True
                            trigger_reason = f"RSI {tf_key.upper()} ({rsi_val})"
                except Exception:
                    pass

            trend = {}
            rel_volume = None
            backtest = {"n": 0, "win_rate": None, "avg_ret": None}
            if daily_hist is not None:
                try:
                    trend = compute_trend(daily_hist["Close"], current_price)
                    rel_volume = compute_rel_volume(daily_hist)
                    sigs = backtest_rsi_signals(daily_hist["Close"])
                    all_signals.extend(sigs)
                    backtest = summarize_returns([r for r, _ in sigs])
                except Exception as e:
                    print(f"Metriche tecniche non calcolate per {ticker_symbol}: {e}")

            score, score_parts, note = calculate_score(rsi_signals, dist_52w_pct, pe_ratio, trend, rel_volume)

            # Portafoglio Unico
            if is_oversold and ticker_symbol not in active_paper_trades:
                invested_usd = 100.0
                shares = round(invested_usd / current_price, 4)
                buy_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
                
                active_paper_trades[ticker_symbol] = {
                    "id": f"trade_{ticker_symbol.lower().replace('=','_').replace('.','_')}",
                    "ticker": ticker_symbol,
                    "name": item["name"],
                    "buy_date": buy_date,
                    "buy_price": current_price,
                    "invested": invested_usd,
                    "shares": shares,
                    "current_price": current_price,
                    "current_value": invested_usd,
                    "pnl_pct": 0.0,
                    "pnl_usd": 0.0,
                    "trigger_reason": trigger_reason
                }

            # Portafoglio DCA
            if is_oversold:
                already_bought_today = any(
                    t["ticker"] == ticker_symbol and t["buy_date"].startswith(today_str) 
                    for t in dca_portfolio
                )
                if not already_bought_today:
                    invested_usd = 100.0
                    shares = round(invested_usd / current_price, 4)
                    buy_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
                    
                    dca_portfolio.append({
                        "id": f"dca_{ticker_symbol.lower().replace('=','_').replace('.','_')}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                        "ticker": ticker_symbol,
                        "name": item["name"],
                        "buy_date": buy_date,
                        "buy_price": current_price,
                        "invested": invested_usd,
                        "shares": shares,
                        "current_price": current_price,
                        "current_value": invested_usd,
                        "pnl_pct": 0.0,
                        "pnl_usd": 0.0,
                        "trigger_reason": trigger_reason
                    })

            results.append({
                "id": f"sug_{ticker_symbol.lower().replace('=','_').replace('.','_')}",
                "ticker": ticker_symbol,
                "name": item["name"],
                "category": category,
                "current_price": current_price,
                "currency": currency,
                "pe_ratio": pe_ratio,
                "dist_52w_pct": dist_52w_pct,
                "score": score,
                "score_parts": score_parts,
                "note": note,
                "rsi_signals": rsi_signals,
                "sma50": trend.get("sma50"),
                "sma200": trend.get("sma200"),
                "sma200_dist_pct": trend.get("sma200_dist_pct"),
                "sma50_above_200": trend.get("sma50_above_200"),
                "rel_volume": rel_volume,
                "backtest": backtest
            })

        except Exception as e:
            print(f"Errore con {ticker_symbol}: {e}")

    # Aggiornamento performance
    for ticker_symbol, trade in active_paper_trades.items():
        if ticker_symbol in current_prices:
            cp = current_prices[ticker_symbol]
            current_value = round(trade["shares"] * cp, 2)
            pnl_usd = round(current_value - trade["invested"], 2)
            pnl_pct = round((pnl_usd / trade["invested"]) * 100, 2)
            trade["current_price"] = cp
            trade["current_value"] = current_value
            trade["pnl_usd"] = pnl_usd
            trade["pnl_pct"] = pnl_pct

    for trade in dca_portfolio:
        ts = trade["ticker"]
        if ts in current_prices:
            cp = current_prices[ts]
            current_value = round(trade["shares"] * cp, 2)
            pnl_usd = round(current_value - trade["invested"], 2)
            pnl_pct = round((pnl_usd / trade["invested"]) * 100, 2)
            trade["current_price"] = cp
            trade["current_value"] = current_value
            trade["pnl_usd"] = pnl_usd
            trade["pnl_pct"] = pnl_pct

    output = {
        "last_updated": updated_at,
        "items": results,
        "paper_portfolio": list(active_paper_trades.values()),
        "dca_portfolio": dca_portfolio,
        "earnings_calendar": earnings_calendar,
        "stats": {
            "horizon_days": BACKTEST_HORIZON,
            "rsi_level": BACKTEST_RSI_LEVEL,
            "alert_threshold": ALERT_THRESHOLD,
            "overall": summarize_returns([r for r, _ in all_signals]),
            "trend_up": summarize_returns([r for r, t in all_signals if t is True]),
            "trend_down": summarize_returns([r for r, t in all_signals if t is False])
        }
    }

    os.makedirs("data", exist_ok=True)
    with open("data/history.json", "w") as f:
        json.dump(output, f, indent=2)

if __name__ == "__main__":
    scan_market()
