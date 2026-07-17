import os
import sys
import datetime
import time
import requests
import pandas as pd
import yfinance as yf

# ==========================================
# ⚙️ 系統基本設定
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def generate_optimized_hk_tickers():
    """
    🎯 核心優化：精準縮小全港股掃描範圍
    港股主板股票與科技巨頭幾乎100%集中在以下兩個區間，
    直接跳過 4000-5999 (認股證) 與 6000-8999 (ETF與結構性產品)，
    從 9999 檔瞬間瘦身至 ~3500 檔，速度提升 3 倍！
    """
    tickers = []
    # 區間 1：傳統藍籌、紅籌、主板核心 (0001 - 3999)
    for i in range(1, 4000):
        tickers.append(f"{i:04d}.HK")
    # 區間 2：中概股回港、次新股、大型科技股 (9600 - 9999)
    for i in range(9600, 10000):
        tickers.append(f"{i:04d}.HK")
    return tickers

def send_tg(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ 錯誤：未設定 Telegram 憑證，僅在終端機輸出。")
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
# ⚡ 雙階段極速掃描演算法
# ==========================================
def scan_all_hong_kong_market_fast():
    start_time = time.time()
    all_tickers = generate_optimized_hk_tickers()
    total_candidates = len(all_tickers)
    
    print(f"🚀 【第一階段】精準區間粗篩開始... (已瘦身至 {total_candidates} 檔)")
    
    # 調整 Batch 大小：過大容易被 Yahoo 阻擋，過小速度慢。300 是 Actions 上的平衡點
    batch_size = 300  
    shortlist = []     
    
    for i in range(0, total_candidates, batch_size):
        batch = all_tickers[i:i+batch_size]
        batch_str = " ".join(batch)
        
        try:
            # 使用 yfinance 抓取今日 1 點數據，添加 ignore_tz 減少序列化開銷
            df_today = yf.download(batch_str, period="1d", progress=False, ignore_tz=True)
            if df_today.empty:
                continue
            
            # 判斷多資產 DataFrame 格式
            current_tickers = df_today.columns.levels[0] if isinstance(df_today.columns, pd.MultiIndex) else [batch_str]
            
            for ticker in batch:
                if ticker not in current_tickers:
                    continue
                
                try:
                    sub_df = df_today[ticker].dropna() if isinstance(df_today.columns, pd.MultiIndex) else df_today.dropna()
                    if sub_df.empty:
                        continue
                    
                    close_price = sub_df["Close"].iloc[-1]
                    volume = sub_df["Volume"].iloc[-1]
                    turnover = close_price * volume  
                    
                    # 🎯 粗篩過濾線：股價 >= 1 元且當日成交額 >= 8,000,000 HKD
                    if close_price >= 1.0 and turnover >= 8000000:
                        shortlist.append(ticker)
                except:
                    continue
                    
            print(f"  ⚡ 已掃描前 {min(i+batch_size, total_candidates)} 檔... 入圍活跃股：{len(shortlist)} 檔")
            time.sleep(0.8)  # 留適度緩衝，避免 GitHub Actions 節點被封 IP
            
        except Exception as e:
            print(f"⚠️ 粗篩批次出錯，自動跳過: {e}")
            continue
            
    print(f"\n✅ 【第一階段完成】耗時: {time.time() - start_time:.1f} 秒")
    print(f"🎯 成功鎖定 {len(shortlist)} 檔高流動性核心港股！")
    
    if not shortlist:
        send_tg("🔍 *【港股掃描】*\n今日市場無任何股票達到 800 萬港幣成交額閥值。")
        return

    # ------------------------------------------
    # 第二階段：精準分析 (只針對入圍的少數股票下載 2 日K線)
    # ------------------------------------------
    print(f"\n🚀 【第二階段】深度分析中... 標的數量: {len(shortlist)} 檔")
    valid_active_stocks = []
    
    shortlist_str = " ".join(shortlist)
    try:
        # 由於此時只剩下 ~100 檔股票，一次下載 2d K線只需 1~2 秒
        df_detailed = yf.download(shortlist_str, period="2d", group_by="ticker", progress=False, ignore_tz=True)
        
        for ticker in shortlist:
            if ticker not in df_detailed.columns.levels[0]:
                continue
            
            sub_df = df_detailed[ticker].dropna()
            if len(sub_df) < 2:
                continue
                
            prev_close = sub_df["Close"].iloc[-2]
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

    msg_1 = f"🚀 *【全港股突破警示：強勢收最高】* ({today_str})\n（已完成全市場成交量粗篩優化）\n\n"
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

    send_tg(msg_1)
    time.sleep(1)
    send_tg(msg_2)
    print(f"🎉 任務順利結束！總花費時間: {time.time() - start_time:.1f} 秒")

if __name__ == "__main__":
    scan_all_hong_kong_market_fast()
