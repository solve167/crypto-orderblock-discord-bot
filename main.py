import ccxt
import pandas as pd
import requests
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def send_to_discord(message: str):
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        print("⚠️ 未設定 DISCORD_WEBHOOK_URL")
        return
    data = {"content": message, "username": "訂單塊大師 Bot"}
    try:
        requests.post(webhook_url, json=data)
        print("✅ 推播成功")
    except Exception as e:
        print(f"推播失敗: {e}")

def fetch_data(symbol, timeframe, limit=500):
    try:
        exchange = ccxt.binance()
        bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"❌ {symbol} {timeframe} 抓取失敗: {e}")
        return None

def detect_orderblock(df):
    if df is None or len(df) < 50:
        return None
    
    current_price = float(df['close'].iloc[-1])
    lookback = 20
    
    high_idx = df['high'].iloc[-lookback:].idxmax()
    low_idx = df['low'].iloc[-lookback:].idxmin()
    
    # 放寬做多邏輯
    if current_price > df['low'].iloc[-lookback:].mean() * 1.008:
        ob_low = float(df['low'].iloc[low_idx])
        risk_dist = (current_price - ob_low) * 1.1
        return {
            "direction": "多",
            "entry": round(current_price, 4),
            "sl": round(ob_low * 0.975, 4),
            "tp1": round(current_price + risk_dist * 0.618, 4),
            "tp2": round(current_price + risk_dist * 1.0, 4),
            "tp3": round(current_price + risk_dist * 1.618, 4),
        }
    
    # 放寬做空邏輯
    elif current_price < df['high'].iloc[-lookback:].mean() * 0.992:
        ob_high = float(df['high'].iloc[high_idx])
        risk_dist = (ob_high - current_price) * 1.1
        return {
            "direction": "空",
            "entry": round(current_price, 4),
            "sl": round(ob_high * 1.025, 4),
            "tp1": round(current_price - risk_dist * 0.618, 4),
            "tp2": round(current_price - risk_dist * 1.0, 4),
            "tp3": round(current_price - risk_dist * 1.618, 4),
        }
    return None

def get_top_coins(limit=12):
    try:
        exchange = ccxt.binance()
        tickers = exchange.fetch_tickers()
        coins = []
        for symbol, info in tickers.items():
            if symbol.endswith('/USDT') and not symbol.startswith(('USDT', 'USDC', 'BUSD')):
                vol = info.get('quoteVolume') or 0
                if vol > 30000000:   # 降低門檻
                    coins.append({'symbol': symbol, 'volume': vol})
        coins.sort(key=lambda x: x['volume'], reverse=True)
        return [c['symbol'] for c in coins[:limit]]
    except:
        return ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT']

if __name__ == "__main__":
    print("🚀 訂單塊熱門幣自動分析啟動...")
    timeframes = ['4h', '8h', '12h', '1d', '1M']
    top_symbols = get_top_coins()
    print(f"熱門幣: {top_symbols[:8]}...")
    
    all_signals = []
    
    for symbol in top_symbols:
        direction_count = {"多": 0, "空": 0}
        signals = []
        
        for tf in timeframes:
            df = fetch_data(symbol, tf)
            if df is not None:
                signal = detect_orderblock(df)
                if signal:
                    signals.append(signal)
                    direction_count[signal["direction"]] += 1
                    print(f"  {symbol} {tf} → {signal['direction']}")
        
        max_count = max(direction_count.values())
        if max_count < 3:
            continue
        
        title_map = {5: "多他媽" if direction_count["多"]==5 else "空他媽",
                     4: "多多" if direction_count["多"]>=4 else "空空",
                     3: "可多" if direction_count["多"]==3 else "可空"}
        title = title_map.get(max_count, "可多")
        
        main_dir = "多" if direction_count["多"] >= direction_count["空"] else "空"
        latest = signals[-1]
        
        all_signals.append({
            "title": title,
            "symbol": symbol,
            "direction": main_dir,
            "count": max_count,
            "entry": latest['entry'],
            "sl": latest['sl'],
            "tp1": latest['tp1'],
            "tp2": latest['tp2'],
            "tp3": latest['tp3']
        })
    
    all_signals.sort(key=lambda x: x['count'], reverse=True)
    top3 = all_signals[:3]
    
    if not top3:
        send_to_discord("📉 本輪無足夠共振訂單塊訊號，等待更好機會。")
        print("無足夠訊號")
    else:
        for sig in top3:
            msg = f"""
🌟 **{sig['title']} 訂單塊共振** - {sig['symbol']}
🕒 更新: {datetime.now().strftime('%Y/%m/%d %H:%M')}

📊 **多TF共振**：{sig['count']}/5 個時間框架同意 {sig['direction']}

📍 **交易方向**：**{sig['direction']}**
💰 **入場參考**：{sig['entry']}
🛡️ **止損**：{sig['sl']} (ICT ±2%)

🎯 **止盈目標**
TP1: {sig['tp1']}
TP2: {sig['tp2']}
TP3: {sig['tp3']}
---
"""
            send_to_discord(msg.strip())
            print(f"已發送 {sig['title']} {sig['symbol']}")
