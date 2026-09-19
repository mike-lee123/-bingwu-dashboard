import os
from datetime import datetime
import pandas as pd
import numpy as np
import requests

def fetch_from_yahoo_chart_api(symbol, range_str="1y"):
    """從 Yahoo 抓取日 K 數據"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        headers = {"User-Agent": "Mozilla/5.0"}
        params = {"range": range_str, "interval": "1d", "includeAdjustedClose": "true"}
        res = requests.get(url, headers=headers, params=params, timeout=5)
        if res.status_code != 200: return pd.DataFrame()
        json_data = res.json()
        result = json_data.get("chart", {}).get("result", [None])[0]
        if not result: return pd.DataFrame()
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        df = pd.DataFrame({
            "Open": quote.get("open", []), "High": quote.get("high", []),
            "Low": quote.get("low", []), "Close": quote.get("close", []),
            "Volume": quote.get("volume", [])
        }, index=pd.to_datetime([datetime.fromtimestamp(ts).date() for ts in timestamps])).dropna(subset=["Close"])
        return df
    except: return pd.DataFrame()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period, min_periods=1).mean()
    loss = ((-delta.where(delta < 0, 0)).rolling(window=period, min_periods=1).mean())
    rs = gain / (loss + 1e-8)
    return 100 - (100 / (1 + rs))

def calculate_cyc(df, n=20):
    pv = df['Close'] * df['Volume']
    return pv.rolling(window=n).sum() / (df['Volume'].rolling(window=n).sum() + 1e-8)

def run_eod_scoring_engine():
    print("🧠 [EOD 戰略大腦] 開始執行每日盤後多維算分...")
    
    # 以台股大盤指數 (^TWII) 作為全市場風向標
    df = fetch_from_yahoo_chart_api("^TWII", range_str="6mo")
    if df.empty or len(df) < 30:
        print("❌ 無法取得足夠的大盤數據，預設回傳 70 分。")
        return 70
        
    df['MA13'] = df['Close'].rolling(window=13).mean()
    df['CYC20'] = calculate_cyc(df, 20)
    df['RSI'] = calculate_rsi(df['Close'], period=14)
    
    last = df.iloc[-1]
    close = float(last['Close'])
    ma13 = float(last['MA13'])
    cyc20 = float(last['CYC20'])
    rsi = float(last['RSI'])
    
    # 核心算分邏輯 (滿分 100 分)
    score = 50.0  # 基準分
    
    if close > ma13: score += 20.0     # 站上 13 日生命線
    if close > cyc20: score += 20.0    # 站上 20 日成本均線
    if 50 <= rsi <= 75: score += 10.0  # RSI 處於強勢多頭區間
    
    final_score = int(round(score))
    
    # 自動將分數寫入文字檔供狙擊手 V19 讀取
    score_file = "daily_score.txt"
    with open(score_file, "w", encoding="utf-8") as f:
        f.write(str(final_score))
        
    print(f"✅ 計算完畢！今日大盤收盤價: {close:.2f}")
    print(f"🎯 今日 EOD 綜合戰略算分：【 {final_score} 分 】")
    print(f"💾 已自動儲存至系統檔案: {score_file}")
    return final_score

if __name__ == "__main__":
    run_eod_scoring_engine()