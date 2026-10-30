import os
import urllib.request
import json

# Legge le credenziali dai Secrets di GitHub
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# Elenco dei titoli monitorati (puoi aggiornarlo o sincronizzarlo)
items = [
    {"name": "Alphabet Inc. (Google)", "ticker": "GOOGL", "score": 100, "current_price": 283.82, "note": "Ipervenduto estremo su 1H e 1D"},
    {"name": "Netflix, Inc.", "ticker": "NFLX", "score": 98, "current_price": 62.05, "note": "RSI 1D in ipervenduto (26.2)"},
    {"name": "Meta Platforms, Inc.", "ticker": "META", "score": 90, "current_price": 624.52, "note": "RSI 1D in ipervenduto (27.8)"},
    {"name": "Argento (Silver Futures)", "ticker": "SI=F", "score": 100, "current_price": 51.81, "note": "RSI 1D in forte ipervenduto (19.9)"}
]

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as response:
            return response.status == 205 or response.status == 200
    except Exception as e:
        print(f"Errore durante l'invio su Telegram: {e}")
        return False

# Filtra i titoli con punteggio di acquisto elevato (Score >= 80)
top_suggestions = [i for i in items if i['score'] >= 80]

if top_suggestions:
    msg = "🚨 <b>REPORT AUTOMATICO: Opportunità di Acquisto</b>\n\n"
    for item in top_suggestions:
        msg += f"• <b>{item['name']} ({item['ticker']})</b>\n"
        msg += f"  Punteggio: <b>{item['score']}/100</b> | Prezzo: {item['current_price']}$\n"
        msg += f"  Nota: {item['note']}\n\n"
    
    send_telegram(msg)
    print("Notifica automatica inviata con successo!")
else:
    print("Nessun titolo sopra la soglia oggi.")
