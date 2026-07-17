import os
import time
import datetime
import pandas as pd
import requests
import yfinance as yf

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def generate_all_hk_tickers():
    """產生港股 1 到 9999 的標準代號格式"""
    return [f"{i:04d}.HK" for i in range(1, 10000)]

def send_tg(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ 錯誤：未設定 Telegram，僅在終端機輸出。")
        print(text)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
        return True
    except Exception as e:
        print(f"❌ Telegram 發送失敗: {e}")
        return False

# ==========================================
# ⚡ 核心優化：雙階段極速掃描
# ==========================================
def scan_all_hong_kong_market_fast():
    start_time = time.time()
    print("🔄 正在初始化全港股代號 (0001.HK - 9999.HK)...")
    all_tickers = generate_all_hk_tickers()
    total_candidates = len(all_tickers)
    
    # ------------------------------------------
    # 第一階段：極速粗篩 (只下載今日 1d 簡要數據)
    # ------------------------------------------
    print(f"🚀 【第一階段】開始快速篩選成交量與股價... (共 {total_candidates} 檔)")
    
    batch_size = 500  # 粗篩時一次投 500 檔，速度極快
    shortlist = []     # 存放通過初選的股票資訊
    
    for i in range(0, total_candidates, batch_size):
        batch = all_tickers[i:i+batch_size]
        batch_str = " ".join(batch)
        
        try:
            # 僅下載今日（1d）的資料，不下載歷史區間，大幅減少資料傳輸量
            df_today = yf.download(batch_str, period="1d", progress=False, ignore_tz=True)
            if df_today.empty:
                continue
            
            for ticker in batch:
                if ticker not in df_today.columns.levels[0]:
                    continue
                
                # 取得今日最後一筆資料（即目前最新價與成交量）
                sub_df = df_today[ticker].dropna()
                if sub_df.empty:
                    continue
                
                close_price = sub_df["Close"].iloc[-1]
                volume = sub_df["Volume"].iloc[-1]
                turnover = close_price * volume  # 今日成交額
                
                # 🎯 粗篩閥值：股價 >= 1 元 且 今日成交額 >= 8,000,000 港幣
                # 這樣可以直接在第一時間砍掉 95% 以上的無效代號
                if close_price >= 1.0 and turnover >= 8000000:
                    shortlist.append(ticker)
                    
            print(f"  ⚡ 已掃描至 {min(i+batch_size, total_candidates)} 檔... 目前初選入圍：{len(shortlist)} 檔")
            time.sleep(0.5)  # 輕微延遲即可
            
        except Exception as e:
            print(f"⚠️ 粗篩批次 {i // batch_size + 1} 出錯: {e}")
            continue
            
    print(f"\n✅ 【第一階段完成】耗時: {time.time() - start_time:.1f} 秒")
    print(f"🎯 從 9999 檔中成功篩選出 {len(shortlist)} 檔活躍港股！")
    
    if not shortlist:
        send_tg("🔍 *【港股掃描】*\n今日市場流動性低落，無任何股票達到 800 萬港幣成交額閥值。")
        return

    # ------------------------------------------
    # 第二階段：精準下載 (只針對入圍的強勢股進行多日分析)
    # ------------------------------------------
    print(f"\n🚀 【第二階段】開始針對這 {len(shortlist)} 檔進行 2 天 K 線深度分析...")
    valid_active_stocks = []
    
    # 因為只剩幾百檔，直接一次打包下載，1 秒就能完成
    shortlist_str = " ".join(shortlist)
    try:
        df_detailed = yf.download(shortlist_str, period="2d", group_by="ticker", progress=False, ignore_tz=True)
        
        for ticker in shortlist:
            if ticker not in df_detailed.columns.levels[0]:
                continue
            
            sub_df = df_detailed[ticker].dropna()
            if len(sub_df) < 2:
                continue
                
            prev_close = sub_df["Close"].iloc[-2]
            today_open = sub_df["Open"].iloc[-1]
            today_high = sub_df["High"].iloc[-1]
            today_close = sub_df["Close"].iloc[-1]
            today_volume = sub_df["Volume"].iloc[-1]
            
            turnover = today_volume * today_close
            change_percent = ((today_close - prev_close) / prev_close) * 100
            
            pure_code = ticker.split('.')[0]
            valid_active_stocks.append({
                "id": pure_code,
                "close": today_close,
                "high": today_high,
                "change": change_percent,
                "volume": today_volume,
                "turnover": turnover
            })
    except Exception as e:
        print(f"❌ 第二階段詳細資料下載失敗: {e}")
        return

    # ------------------------------------------
    # 📊 策略篩選與 TG 發送
    # ------------------------------------------
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    master_df = pd.DataFrame(valid_active_stocks)

    # 策略一：爆量突破收最高 (漲幅 >= 5%, 收盤接近最高價)
    breakout_cond = (master_df["change"] >= 5.0) & ((master_df["high"] - master_df["close"]) <= (master_df["close"] * 0.003))
    breakout_df = master_df[breakout_cond].sort_values(by="change", ascending=False).head(5)

    msg_1 = f"🚀 *【全港股突破警示：強勢收最高】* ({today_str})\n（第一階段已濾除低流動性雜訊）\n\n"
    if not breakout_df.empty:
        for _, row in breakout_df.iterrows():
            msg_1 += f"📌 *{row['id']}*\n💰 最新價：`{row['close']:.2f} HKD` (`+{row['change']:.2f}%`)\n📊 成交額：`{row['turnover']/1000000:.1f}M HKD`\n------------------------\n"
    else:
        msg_1 += "今日全港股暫無符合「強勢突破收最高」標的。\n"

    # 策略二：成交額 Top 5
    volume_surge_df = master_df[master_df["change"] > 0.0].sort_values(by="turnover", ascending=False).head(5)
    msg_2 = f"📊 *【全港股資金聚焦：今日成交額 Top 5】* ({today_str})\n\n"
    if not volume_surge_df.empty:
        for _, row in volume_surge_df.iterrows():
            msg_2 += f"🔥 *{row['id']}*\n💰 收盤價：`{row['close']:.2f} HKD` (`+{row['change']:.2f}%`)\n💸 今日成交額：`{row['turnover']/1000000:.1f}M HKD`\n------------------------\n"

    # 發送
    send_tg(msg_1)
    time.sleep(1)
    send_tg(msg_2)
    
    print(f"🎉 任務圓滿結束！總花費時間: {time.time() - start_time:.1f} 秒")

if __name__ == "__main__":
    scan_all_hong_kong_market_fast()
