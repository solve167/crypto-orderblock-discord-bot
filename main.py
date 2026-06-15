import ccxt
import pandas as pd
import requests
import os
from datetime import datetime
import numpy as np
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

def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return float(atr.iloc[-1]) if not atr.empty else (df['close'].iloc[-1] * 0.018)

def detect_orderblock(df):
    if df is None or len(df) < 70:
        return None
   
    current_price = float(df['close'].iloc[-1])
    lookback = 20
    atr = calculate_atr(df)
   
    recent_high = float(df['high'].iloc[-lookback:].max())
    recent_low = float(df['low'].iloc[-lookback:].min())
    mean_high = float(df['high'].iloc[-lookback:].mean())
    mean_low = float(df['low'].iloc[-lookback:].mean())

    # === 做多邏輯（強制 OB 在下方）===
    if (current_price > mean_low * 1.012 and 
        current_price > recent_low * 1.008 and
        recent_low < current_price * 0.985 and   # 關鍵：OB 必須明顯低於現價
        df['close'].iloc[-5:].mean() > df['close'].iloc[-15:-5].mean()):
        
        ob_low = recent_low
        risk_dist = current_price - ob_low   # 正向距離
        
        if risk_dist <= 0 or risk_dist > current_price * 0.15:  # 過大風險不取
            return None
        
        sl = round(ob_low * 0.965, 4)   # 再往下一些
        tp1 = round(current_price + risk_dist * 0.618, 4)
        tp2 = round(current_price + risk_dist * 1.0, 4)
        tp3 = round(current_price + risk_dist * 1.618, 4)
        
        # 強制驗證
        if sl >= current_price or tp1 <= current_price:
            return None
            
        return {
            "direction": "多",
            "entry": round(current_price, 4),
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
        }
    
    # === 做空邏輯（強制 OB 在上方）===
    elif (current_price < mean_high * 0.988 and 
          current_price < recent_high * 0.992 and
          recent_high > current_price * 1.015 and   # 關鍵：OB 必須明顯高於現價
          df['close'].iloc[-5:].mean() < df['close'].iloc[-15:-5].mean()):
        
        ob_high = recent_high
        risk_dist = ob_high - current_price
        
        if risk_dist <= 0 or risk_dist > current_price * 0.15:
            return None
        
        sl = round(ob_high * 1.035, 4)
        tp1 = round(current_price - risk_dist * 0.618, 4)
        tp2 = round(current_price - risk_dist * 1.0, 4)
        tp3 = round(current_price - risk_dist * 1.618, 4)
        
        if sl <= current_price or tp1 >= current_price:
            return None
            
        return {
            "direction": "空",
            "entry": round(current_price, 4),
            "sl": sl,
            "tp1": round(tp1, 4),
            "tp2": round(tp2, 4),
            "tp3": round(tp3, 4),
        }
    
    return None

def get_top_coins(limit=10):
    try:
        exchange = ccxt.okx()
        tickers = exchange.fetch_tickers()
        coins = []
        for symbol, info in tickers.items():
            if symbol.endswith('/USDT') and not symbol.startswith(('USDT','USDC')):
                vol = info.get('quoteVolume') or info.get('volume') or 0
                if vol > 13000000:
                    coins.append({'symbol': symbol, 'volume': vol})
        coins.sort(key=lambda x: x['volume'], reverse=True)
        return [c['symbol'] for c in coins[:limit]]
    except:
        return ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'HYPE/USDT', 'DOGE/USDT', 'WLD/USDT']

if __name__ == "__main__":
    print("🚀 訂單塊大師 Bot - 方向永不錯誤終極版啟動...")
    timeframes = ['4h', '6h', '12h', '1d', '1w']
    
    top_symbols = get_top_coins()
    print(f"熱門幣: {top_symbols[:8]}...")
   
    all_signals = []
   
    for symbol in top_symbols:
        direction_count = {"多": 0, "空": 0}
        signals = []
       
        for tf in timeframes:
            try:
                exchange = ccxt.okx({'enableRateLimit': True})
                bars = exchange.fetch_ohlcv(symbol, tf, limit=500)
                df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                
                signal = detect_orderblock(df)
                if signal:
                    signals.append(signal)
                    direction_count[signal["direction"]] += 1
                    print(f" ✅ {symbol} {tf} → {signal['direction']} | E:{signal['entry']} SL:{signal['sl']} TP1:{signal['tp1']}")
            except Exception as e:
                err_str = str(e)
                if "bar error" in err_str or "Parameter" in err_str:
                    print(f"⚠️ {symbol} {tf} 不支援，跳過")
                else:
                    print(f"❌ {symbol} {tf} 抓取失敗")
                continue
       
        max_count = max(direction_count.values()) if direction_count else 0
        if max_count < 3:
            continue
       
        title_map = {
            5: "多他媽",
            4: "多多" if direction_count.get("多", 0) >= 4 else "空空",
            3: "可多" if direction_count.get("多", 0) == 3 else "可空"
        }
        title = title_map.get(max_count, "可多")
       
        main_dir = "多" if direction_count.get("多", 0) >= direction_count.get("空", 0) else "空"
        latest = signals[-1]
        
        entry = latest['entry']
        sl = latest['sl']
        tp1 = latest['tp1']
        direction = latest['direction']
        
        # 最終鐵壁檢查
        if (direction == "多" and (sl >= entry or tp1 <= entry)) or \
           (direction == "空" and (sl <= entry or tp1 >= entry)):
            print(f"⚠️ {symbol} 方向異常，已過濾")
            continue
        
        all_signals.append({
            "title": title,
            "symbol": symbol,
            "direction": main_dir,
            "count": max_count,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
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
🛡️ **止損**：{sig['sl']} (ICT ±1.5%)
🎯 **止盈目標**
TP1: {sig['tp1']}
TP2: {sig['tp2']}
TP3: {sig['tp3']}
---
僅提供參考，不構成投資建議。
"""
            send_to_discord(msg.strip())
            print(f"✅ 已發送 {sig['title']} {sig['symbol']}")
   
    print("🎉 訂單塊大師 Bot 本輪分析完成！")
