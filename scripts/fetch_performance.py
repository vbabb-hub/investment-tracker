for item in suggestions:
        ticker_symbol = item["ticker"]
        entry_price = item["entry_price"]
        category = item["category"]
        
        current_price = entry_price
        roi_pct = 0.0
        rsi_signals = {}

        try:
            ticker = yf.Ticker(ticker_symbol)
            
            if category == "AZIONI":
                info = ticker.info
                market_cap = info.get("marketCap", 0)
                if market_cap and market_cap < 1_000_000_000:
                    continue

            hist_day = ticker.history(period="1d")
            if not hist_day.empty:
                current_price = round(float(hist_day["Close"].iloc[-1]), 2)
                roi_pct = round(((current_price - entry_price) / entry_price) * 100, 2)

            if category in ["AZIONI", "CRYPTO", "ETF"]: # Incluso ETF per sicurezza
                intervals = {"1h": "60m", "1d": "1d", "1wk": "1wk"}
                periods = {"1h": "5d", "1d": "6mo", "1wk": "2y"}
                
                for tf_key, tf_val in intervals.items():
                    try:
                        hist_tf = ticker.history(period=periods[tf_key], interval=tf_val)
                        if not hist_tf.empty and len(hist_tf) > 15:
                            rsi_val = calculate_rsi(hist_tf["Close"])
                            status = get_rsi_status(rsi_val)
                            rsi_signals[tf_key] = {"rsi": rsi_val, "status": status}
                    except Exception:
                        pass

        except Exception as e:
            print(f"Errore critico per {ticker_symbol}: {e}")

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
