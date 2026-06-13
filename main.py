import ccxt
import pandas as pd
import requests
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ================== Discord 推播 ==================
def send_to_discord(message: str):
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        print("⚠️ 未設定 DISCORD_WEBHOOK_URL")
        return False
    data = {"content": message, "username": "訂單塊大師 Bot"}
    try:
        response = requests.post(webhook_url, json=data)
        print(f"推播狀態: {response.status_code}")
        return True
    except Exception as e:
        print(f"推播失敗: {e}")
        return False

# ================== 抓取K線 ==================
def fetch_data(symbol, timeframe, limit=300):
    try:
        exchange = ccxt.binance()
        bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except:
        return None

# ================== 改進版訂單塊偵測 ==================
def detect_orderblock(df):
    if df is None or len(df) < 80:
        return None
    current_price = float(df['close'].iloc[-1])
    lookback = 25
    
    high_idx = df['high'].iloc[-lookback:].idxmax()
    low_idx = df['low'].iloc[-lookback:].idxmin()
    
    # 做空 (熊市OB)
    if high_idx > low_idx + 5:
        ob_high = float(df['high'].iloc[high_idx])
        if current_price <= ob_high * 0.988:
            risk_dist = (ob_high - current_price) * 1.15
            return {
                "direction": "空",
                "entry": round(current_price, 4),
                "sl": round(ob_high * 1.022, 4),
                "tp1": round(current_price - risk_dist * 0.618, 4),
                "tp2": round(current_price - risk_dist * 1.0, 4),
                "tp3": round(current_price - risk_dist * 1.618, 4),
                "strength": 5 if high_idx > len(df)-10 else 4  # 越新結構越強
            }
    
    # 做多 (牛市OB)
    else:
        ob_low = float(df['low'].iloc[low_idx])
        if current_price >= ob_low * 1.012:
            risk_dist = (current_price - ob_low) * 1.15
            return {
                "direction": "多",
                "entry": round(current_price, 4),
                "sl": round(ob_low * 0.978, 4),
                "tp1": round(current_price + risk_dist * 0.618, 4),
                "tp2": round(current_price + risk_dist * 1.0, 4),
                "tp3": round(current_price + risk_dist * 1.618, 4),
                "strength": 5 if low_idx > len(df)-10 else 4
            }
    return None

# ================== 自動抓熱門TOP幣種 ==================
def get_top_coins(limit=15):
    try:
        exchange = ccxt.binance()
        tickers = exchange.fetch_tickers()
        coins = []
        for symbol, info in tickers.items():
            if symbol.endswith('/USDT') and 'USDT' not in symbol.split('/')[0] and info['quoteVolume'] > 50000000:  # 交易量門檻
                coins.append({
                    'symbol': symbol,
                    'volume': info['quoteVolume']
                })
        # 排序取Top
        coins.sort(key=lambda x: x['volume'], reverse=True)
        return [c['symbol'] for c in coins[:limit]]
    except Exception as e:
        print(f"抓取熱門幣失敗: {e}")
        return ['ETH/USDT', 'BTC/USDT', 'XRP/USDT', 'SOL/USDT', 'BNB/USDT']

# ================== 主程式 ==================
if __name__ == "__main__":
    print("🚀 自動熱門幣訂單塊共振分析啟動...")
    
    timeframes = ['4h', '8h', '12h', '1d', '1M']
    top_symbols = get_top_coins(limit=12)
    print(f"🔥 找到熱門幣: {top_symbols}")
    
    all_signals = []
    
    for symbol in top_symbols:
        print(f"\n🔍 分析 {symbol} ...")
        direction_count = {"多": 0, "空": 0}
        signals = []
        
        for tf in timeframes:
            df = fetch_data(symbol, tf)
            if df is not None:
                signal = detect_orderblock(df)
                if signal:
                    signals.append((tf, signal))
                    direction_count[signal["direction"]] += 1
        
        if not signals or max(direction_count.values()) < 3:
            continue
        
        max_count = max(direction_count.values())
        if max_count == 5:
            title = "多他媽" if direction_count["多"] == 5 else "空他媽"
        elif max_count >= 4:
            title = "多多" if direction_count["多"] >= 4 else "空空"
        else:
            title = "可多" if direction_count["多"] == 3 else "可空"
        
        main_dir = "多" if direction_count["多"] > direction_count["空"] else "空"
        latest = signals[-1][1]
        
        # 計算強度分數 (共振數 + 結構新舊)
        strength_score = max_count * 10 + latest.get("strength", 4)
        
        all_signals.append({
            "title": title,
            "symbol": symbol,
            "direction": main_dir,
            "strength": strength_score,
            "count": max_count,
            "entry": latest['entry'],
            "sl": latest['sl'],
            "tp1": latest['tp1'],
            "tp2": latest['tp2'],
            "tp3": latest['tp3']
        })
    
    # 排序取前3最強
    all_signals.sort(key=lambda x: x['strength'], reverse=True)
    top3 = all_signals[:3]
    
    if not top3:
        print("本輪無足夠強訊號")
        send_to_discord("📉 本輪無足夠共振訂單塊訊號，等待更好機會。")
    else:
        for sig in top3:
            msg = f"""
🌟 **{sig['title']} 訂單塊共振** - {sig['symbol']}
🕒 更新: {datetime.now().strftime('%Y/%m/%d %H:%M')}

📊 **多TF共振**：{sig['count']}/5 個時間框架同意 {sig['direction']}
   • 4H / 8H / 12H / 日線 / 月線

📍 **交易方向**：**{sig['direction']}**
💰 **入場參考**：{sig['entry']}
🛡️ **止損**：{sig['sl']} (ICT壓力/支撐 ±2%)

🎯 **止盈目標**
TP1: {sig['tp1']}
TP2: {sig['tp2']}
TP3: {sig['tp3']}
---
            """
            send_to_discord(msg.strip())
            print(f"✅ 已發送 {sig['title']} - {sig['symbol']}")
    
    print("\n🎉 熱門幣Top3分析完成！")