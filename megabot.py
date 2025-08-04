import os
import time
import threading
from datetime import datetime
import requests
import telebot
from flask import Flask, request, jsonify, render_template_string

# ====== TWOJE DANE TELEGRAM ======
API_KEY = "8330502624:AAEr5TliWy66wQm9EX02OUuGeWoslYjWeUY"
CHAT_ID = "7743162708"
bot = telebot.TeleBot(API_KEY)

import openai
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

signal_queue = []
dashboard_signals = []

# ====== PAIRS NA KAŻDEJ GIEŁDZIE ======
BINANCE_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "TRXUSDT", "XLMUSDT", "EOSUSDT", "HBARUSDT",
    "LOKAUSDT", "SUIUSDT", "MDTUSDT", "BLURUSDT", "PNGUSDT", "HOPRUSDT",
    "ASMUSDT", "BONKUSDT", "PENGUUSDT", "JASMYUSDT", "CLVUSDT", "TRUMPUSDT", "ONDOUSDT", "CFXUSDT"
]

COINBASE_PAIRS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "TRX-USD", "XLM-USD", "EOS-USD", "HBAR-USD",
    "LOKA-USD", "SUI-USD", "MDT-USD", "BLUR-USD", "PNG-USD", "JASMY-USD", "CLV-USD", "TRUMP-USD"
]

KRAKEN_PAIRS = [
    "XBTUSD", "ETHUSD", "SOLUSD", "ADAUSD", "TRXUSD", "XLMUSD", "EOSUSD", "HBARUSD",
    "LOKAUSD", "SUIUSD", "MDTUSD", "BLURUSD", "PNGUSD", "JASMYUSD", "CLVUSD", "TRUMPUSD"
]

# ====== AI Funkcja – analiza sentymentu/komentarz GPT ======
def ai_comment(coin, typ, reason, custom_prompt=None):
    if not openai.api_key:
        return "(Brak klucza OPENAI_API_KEY)"
    try:
        if custom_prompt:
            prompt = custom_prompt
        else:
            prompt = (
                f"Wygeneruj analizę eksperta AI dla sygnału kryptowalutowego.\n"
                f"Kryptowaluta: {coin}\n"
                f"Typ sygnału: {typ}\n"
                f"Opis sygnału: {reason}\n"
                f"Oceń w 2-3 zdaniach czy warto wejść, na co zwrócić uwagę, podsumuj sentyment. Po polsku, rzeczowo, zwięźle."
            )
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0.5,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"(Błąd GPT: {e})"

# ========== Binance ==========
def fetch_binance_ticker(symbol):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=10"
    data = requests.get(url).json()
    if not isinstance(data, list) or len(data) < 2:
        return None, None
    closes = [float(x[4]) for x in data]
    vols = [float(x[5]) for x in data]
    return closes, vols

def pump_detector_binance_thread():
    while True:
        for pair in BINANCE_PAIRS:
            try:
                closes, vols = fetch_binance_ticker(pair)
                if closes is None or vols is None:
                    continue
                change = ((closes[-1] - closes[0]) / closes[0]) * 100
                avg_vol = sum(vols[:-1]) / max(1, len(vols)-1)
                if change >= 5 or vols[-1] > avg_vol*3:
                    reason = f"Pump (Binance)! Zmiana {change:.2f}%, wolumen {vols[-1]:.2f}"
                    ai = ai_comment(pair, "Pump Detector", reason)
                    sygnal = {
                        "type": "pump",
                        "coin": f"BINANCE:{pair}",
                        "reason": reason,
                        "ai": ai,
                        "score": 8.0 + min(change/10, 2),
                        "timestamp": time.time()
                    }
                    signal_queue.append(sygnal)
            except Exception as e:
                print(f"PumpDetectorBinance error {pair}: {e}")
        time.sleep(300)

# ========== Coinbase ==========
def fetch_coinbase_ticker(symbol):
    url = f"https://api.exchange.coinbase.com/products/{symbol}/candles?granularity=60&limit=10"
    headers = {"User-Agent": "Mozilla/5.0"}
    data = requests.get(url, headers=headers).json()
    if not isinstance(data, list) or len(data) < 2:
        return None, None
    closes = [float(x[4]) for x in reversed(data)]
    vols = [float(x[5]) for x in reversed(data)]
    return closes, vols

def pump_detector_coinbase_thread():
    while True:
        for pair in COINBASE_PAIRS:
            try:
                closes, vols = fetch_coinbase_ticker(pair)
                if closes is None or vols is None:
                    continue
                change = ((closes[-1] - closes[0]) / closes[0]) * 100
                avg_vol = sum(vols[:-1]) / max(1, len(vols)-1)
                if change >= 5 or vols[-1] > avg_vol*3:
                    reason = f"Pump (Coinbase)! Zmiana {change:.2f}%, wolumen {vols[-1]:.2f}"
                    ai = ai_comment(pair, "Pump Detector", reason)
                    sygnal = {
                        "type": "pump",
                        "coin": f"COINBASE:{pair}",
                        "reason": reason,
                        "ai": ai,
                        "score": 8.0 + min(change/10, 2),
                        "timestamp": time.time()
                    }
                    signal_queue.append(sygnal)
            except Exception as e:
                print(f"PumpDetectorCoinbase error {pair}: {e}")
        time.sleep(300)

# ========== Kraken ==========
def fetch_kraken_ticker(symbol):
    url = f"https://api.kraken.com/0/public/OHLC?pair={symbol}&interval=1"
    data = requests.get(url).json()
    result = data.get("result", {})
    key = [k for k in result.keys() if k != "last"]
    if not key or not isinstance(result[key[0]], list) or len(result[key[0]]) < 2:
        return None, None
    candles = result[key[0]]
    closes = [float(x[4]) for x in candles]
    vols = [float(x[6]) for x in candles]
    return closes, vols

def pump_detector_kraken_thread():
    while True:
        for pair in KRAKEN_PAIRS:
            try:
                closes, vols = fetch_kraken_ticker(pair)
                if closes is None or vols is None:
                    continue
                change = ((closes[-1] - closes[0]) / closes[0]) * 100
                avg_vol = sum(vols[:-1]) / max(1, len(vols)-1)
                if change >= 5 or vols[-1] > avg_vol*3:
                    reason = f"Pump (Kraken)! Zmiana {change:.2f}%, wolumen {vols[-1]:.2f}"
                    ai = ai_comment(pair, "Pump Detector", reason)
                    sygnal = {
                        "type": "pump",
                        "coin": f"KRAKEN:{pair}",
                        "reason": reason,
                        "ai": ai,
                        "score": 8.0 + min(change/10, 2),
                        "timestamp": time.time()
                    }
                    signal_queue.append(sygnal)
            except Exception as e:
                print(f"PumpDetectorKraken error {pair}: {e}")
        time.sleep(300)

# ====== Decision Layer – kompresja i selekcja sygnałów ======
def decision_layer_thread():
    while True:
        now = time.time()
        recent_signals = [s for s in signal_queue if now-s["timestamp"] < 900]  # 15 min "okno"
        coins = {}
        for s in recent_signals:
            if s["coin"] not in coins:
                coins[s["coin"]] = []
            coins[s["coin"]].append(s)
        for coin, signals in coins.items():
            types = set([s['type'] for s in signals])
            if len(types) >= 1:  # minimum 1 strategia dla uproszczenia
                msg = f"⚡️ *SYGNAŁ* na {coin}!\n"
                for s in signals:
                    msg += f"- {s['type']} ({s['reason']}) [score: {s['score']}]\n"
                    if "ai" in s and s["ai"]:
                        msg += f"_AI: {s['ai']}_\n"
                msg += f"\nCzas: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
                dashboard_signals.append({
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "type": "SYGNAŁ",
                    "coin": coin,
                    "message": msg
                })
        signal_queue.clear()
        time.sleep(60)

# ====== Web dashboard + webhook ======
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>MegaBot Dashboard</title>
    <style>
        body { font-family: Arial, sans-serif; background: #23272e; color: #fafafa; }
        h1 { color: #00e676; }
        table { margin: auto; border-collapse: collapse; width: 90%; background: #1e1e1e; }
        th, td { border: 1px solid #333; padding: 10px; }
        th { background: #00e676; color: black; }
        tr:nth-child(even) { background: #2a2a2a; }
        a { color: #00e676; text-decoration: none; }
    </style>
</head>
<body>
    <h1>🤖 MegaBot Dashboard</h1>
    <table>
        <tr>
            <th>Czas</th>
            <th>Typ</th>
            <th>Giełda:Krypto</th>
            <th>Wiadomość</th>
        </tr>
        {% for s in signals %}
        <tr>
            <td>{{ s.time }}</td>
            <td>{{ s.type }}</td>
            <td>{{ s.coin }}</td>
            <td>{{ s.message|safe }}</td>
        </tr>
        {% endfor %}
    </table>
    <p>🔄 Auto-refresh co 60s</p>
    <script>setTimeout(() => location.reload(), 60000);</script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    return render_template_string(HTML_TEMPLATE, signals=dashboard_signals[-50:])

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        coin = data.get("symbol", "N/A")
        action = data.get("action", "N/A")
        price = data.get("price", "N/A")
        rsi = data.get("rsi", "N/A")
        msg = (
            f"📢 *Sygnał z TradingView/Webhook*\n"
            f"💎 Symbol: {coin}\n"
            f"📈 Akcja: {action}\n"
            f"💰 Cena: {price}\n"
            f"📊 RSI: {rsi}\n"
            f"Czas: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        dashboard_signals.append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": "Webhook",
            "coin": coin,
            "message": msg
        })
        return jsonify({"status": "ok", "message": "Alert wysłany do Telegrama"}), 200
    except Exception as e:
        print("❌ Błąd webhooka:", e)
        return jsonify({"status": "error", "message": str(e)}), 500

def run_flask():
    print("🟢 Flask Dashboard/Webhook start")
    app.run(host="0.0.0.0", port=8080)

# ====== Uruchom wszystkie wątki ======
if __name__ == "__main__":
    threading.Thread(target=pump_detector_binance_thread, daemon=True).start()
    threading.Thread(target=pump_detector_coinbase_thread, daemon=True).start()
    threading.Thread(target=pump_detector_kraken_thread, daemon=True).start()
    threading.Thread(target=decision_layer_thread, daemon=True).start()
    threading.Thread(target=run_flask, daemon=True).start()
    print("🚀 MegaBot uruchomiony!")
    while True:
        time.sleep(60)
