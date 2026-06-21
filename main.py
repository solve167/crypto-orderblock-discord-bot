import ccxt
import pandas as pd
import requests
import os
import time
from datetime import datetime
import numpy as np
from dotenv import load_dotenv
import signal
import sys

load_dotenv()

# ====================== 配置 ======================
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')
TIMEFRAMES = ['4h', '1d', '1w']  # 先用主要 TF 提高效率
TOP_COINS_LIMIT = 8
MIN_CONFLUENCE = 2  # 至少 2 個 TF 共振就發訊號（更靈敏）
MAX_RUNTIME = 280  # 秒，防止 GitHub 超時

# ====================== Discord 推播 ======================
def send_to_discord(message: str):
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ 未設定 DISCORD_WEBHOOK_URL")
        return False
    data = {"content": message, "username": "訂單塊大師 Bot"}
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=10)
        print("✅ Discord 推播成功")
        return True
    except Exception as e:
        print(f"❌ 推播失敗: {e}")
        return False

# ====================== 技術指標 ======================
def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return float(atr.iloc[-1]) if not atr.empty else (df['close'].iloc[-1] * 0.018)

# ====================== 核心：訂單塊偵測（優化版） ======================
def detect_orderblock(df):
    if df is None or len(df) < 100:
        return None
    
    current_price = float(df['close'].iloc[-1])
    atr = calculate_atr(df)
    lookback = 25
    
    recent_high = float(df['high'].iloc[-lookback:].max())
    recent_low = float(df['low'].iloc[-lookback:].min())
    mean_high = float(df['high'].iloc[-lookback:].mean())
    mean_low = float(df['low'].iloc[-lookback:].mean())
    
    # === 做多 - 需求區（Order Block 在下方）===
    if (current_price > mean_low * 1.008 and 
        recent_low < current_price * 0.982 and
        df['close'].iloc[-8:].mean() > df['close'].iloc[-20:-8].mean()):
        
        risk_dist = current_price - recent_low
        if risk_dist <= atr * 0.8 or risk_dist > current_price * 0.15:
            return None
            
        sl = round(recent_low - atr * 0.3, 4)  # 更貼近 ICT
        tp1 = round(current_price + risk_dist * 0.618, 4)
        tp2 = round(current_price + risk_dist * 1.0, 4)
        tp3 = round(current_price + risk_dist * 1.618, 4)
        
        if sl >= current_price or tp1 <= current_price:
            return None
        return {"direction": "多", "entry": round(current_price, 4), "sl": sl, 
                "tp1": tp1, "tp2": tp2, "tp3": tp3, "strength": 3}
    
    # === 做空 - 供給區（Order Block 在上方）===
    elif (current_price < mean_high * 0.992 and 
          recent_high > current_price * 1.018 and
          df['close'].iloc[-8:].mean() < df['close'].iloc[-20:-8].mean()):
        
        risk_dist = recent_high - current_price
        if risk_dist <= atr * 0.8 or risk_dist > current_price * 0.15:
            return None
            
        sl = round(recent_high + atr * 0.3, 4)
        tp1 = round(current_price - risk_dist * 0.618, 4)
        tp2 = round(current_price - risk_dist * 1.0, 4)
        tp3 = round(current_price - risk_dist * 1.618, 4)
        
        if sl <= current_price or tp1 >= current_price:
            return None
        return {"direction": "空", "entry": round(current_price, 4), "sl": sl, 
                "tp1": tp1, "tp2": tp2, "tp3": tp3, "strength": 3}
    
    return None

# ====================== 獲取熱門幣 ======================
def get_top_coins(limit=TOP_COINS_LIMIT):
    try:
        exchange = ccxt.okx({'enableRateLimit': True})
        tickers = exchange.fetch_tickers()
        coins = []
        for symbol, info in tickers.items():
            if symbol.endswith('/USDT') and not symbol.startswith(('USDT', 'USDC', 'USDD')):
                vol = info.get('quoteVolume') or info.get('volume') or 0
                if vol > 12000000:
                    coins.append({'symbol': symbol, 'volume': vol})
        coins.sort(key=lambda x: x['volume'], reverse=True)
        return [c['symbol'] for c in coins[:limit]]
    except:
        return ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT']

# ====================== 主分析函數 ======================
def run_analysis():
    signal.alarm(MAX_RUNTIME)  # 超時保護
    print(f"\n🚀 === 訂單塊大師 Bot 開始分析 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    
    top_symbols = get_top_coins()
    print(f"🔥 熱門幣種: {top_symbols}")
    
    all_signals = []
    
    for symbol in top_symbols:
        direction_count = {"多": 0, "空": 0}
        best_signal = None
        best_strength = 0
        
        for tf in TIMEFRAMES:
            try:
                exchange = ccxt.okx({'enableRateLimit': True})
                bars = exchange.fetch_ohlcv(symbol, tf, limit=400)
                df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                signal = detect_orderblock(df)
                if signal:
                    direction_count[signal["direction"]] += 1
                    print(f"✅ {symbol} {tf} → {signal['direction']} (強度: {signal.get('strength',1)})")
                    
                    if signal.get('strength', 1) > best_strength:
                        best_signal = signal
                        best_strength = signal.get('strength', 1)
            except Exception as e:
                print(f"⚠️ {symbol} {tf} 錯誤: {e}")
                continue
        
        # 共振過濾
        max_count = max(direction_count.values()) if direction_count else 0
        if max_count < MIN_CONFLUENCE or not best_signal:
            continue
        
        main_dir = "多" if direction_count.get("多", 0) >= direction_count.get("空", 0) else "空"
        
        title = "🔥 強勢共振" if max_count >= 3 else "⚡ 多TF共振"
        
        all_signals.append({
            "title": title,
            "symbol": symbol,
            "direction": main_dir,
            "count": max_count,
            **best_signal
        })
    
    # 排序並取前3
    all_signals.sort(key=lambda x: x['count'], reverse=True)
    top_signals = all_signals[:3]
    
    if not top_signals:
        send_to_discord("📉 本輪無足夠共振訂單塊訊號，市場正在盤整，耐心等待高機率 setup。")
        print("📉 本輪無訊號")
    else:
        for sig in top_signals:
            msg = f"""
🌟 **{sig['title']}** - {sig['symbol']}
🕒 更新: {datetime.now().strftime('%Y/%m/%d %H:%M')}
📊 **多時間框架共振**：{sig['count']}/{len(TIMEFRAMES)} 個 TF 同意 **{sig['direction']}**
📍 **交易方向**：**{sig['direction']}**
💰 **入場參考**：{sig['entry']}
🛡️ **止損**：{sig['sl']} (貼近 ICT 結構)
🎯 **止盈目標**
TP1: {sig['tp1']}
TP2: {sig['tp2']}
TP3: {sig['tp3']}

⚠️ 僅供參考 • 嚴格執行風險管理 • 非投資建議
"""
            send_to_discord(msg.strip())
            print(f"✅ 已發送 {sig['title']} {sig['symbol']}")
    
    print("🎉 本輪分析完成！")

# ====================== 超時處理 ======================
def timeout_handler(signum, frame):
    print("⏰ 分析超時，強制結束")
    sys.exit(1)

# ====================== 入口 ======================
if __name__ == "__main__":
    signal.signal(signal.SIGALRM, timeout_handler)
    print("🚀 訂單塊大師 Bot - GitHub Actions 優化版啟動...")
    run_analysis()
    print("🏁 程式正常結束")
