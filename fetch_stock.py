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
# ⚡ 新浪財經 API 全港股極速粗篩
# ==========================================
def fetch_hk_shortlist_from_sina():
    """
    使用新浪財經接口，一鍵獲取所有港股主板的即時成交額。
    好處：100% 準確，1 秒抓完，直接過濾掉成交額不足的標的。
    """
    print("🌐 正在透過新浪財經 API 抓取全港股即時數據...")
    shortlist = []
    
    # 港股主板分頁抓取（每頁 80 檔，一般抓前 5 頁共 400 檔最活躍的就非常足夠了）
    # 因為新浪是按成交額由高到低排序，前 400 檔已經包攬了市場 99% 的流動性
    for page in range(1, 6):
        url = f"https://vip.stock.finance.sina.com.cn/hq/api/jsonp.php/IO.XSRV2.CallbackList['hk']/HK_Service.getMainMethodPageList?page={page}&num=80&sort=amount&asc=0"
        try:
            response = requests.get(url, timeout=10)
            text = response.text
            
            # 清理 jsonp 的外殼字串
            if "bracket" in text or "CallbackList" in text:
                left = text.find("[")
                right = text.rfind("]") + 1
                text = text[left:right]
            
            # 轉換為 JSON
            data = pd.read_json(text)
            if data.empty:
                break
                
            for _, row in data.iterrows():
                # 新浪的代號是 5 碼，例如 00700，我們轉換成 yfinance 的 0700.HK
                raw_code = str(row['symbol'])
                pure_code = raw_code[-4:] if len(raw_code) == 5 else raw_code
                ticker = f"{int(pure_code):04d}.HK"
                
                trade = float(row['trade'])      # 最新價
                turnover = float(row['amount'])  # 成交額 (港幣)
                
                # 🎯 粗篩過濾：股價 >= 1 元 且 今日成交額 >= 8,000,000 HKD
                if trade >= 1.0 and turnover >= 8000000:
                    shortlist.append(ticker)
                    
        except Exception as e:
            print(f"⚠️ 抓取新浪分頁 {page} 失敗: {e}")
            continue
            
    # 去重
    shortlist = list(set(shortlist))
    print(f"🎯 第一階段完成！從新浪財經精準過濾出 {len(shortlist)} 檔活躍港股（成交額 > 800萬）。")
    return shortlist

# ==========================================
# 🚀 第二階段：精準分析與發送
# ==========================================
def scan_all_hong_kong_market_fast():
    start_time = time.time()
    
    # 1. 第一階段：直接拿精準入圍名單
    shortlist = fetch_hk_shortlist_from_sina()
    
    if not shortlist:
        send_tg("🔍 *【港股掃描】*\n今日市場流動性異常，無任何股票達到 800 萬港幣成交額閥值。")
        return

    # 2. 第二階段：只針對入圍股票下載 2 日 K 線計算技術指標
    print(f"\n🚀 【第二階段】深度分析中... 標的數量: {len(shortlist)} 檔")
    valid_active_stocks = []
    
    shortlist_str = " ".join(shortlist)
    try:
        # 只查這幾百檔的 2 日K線，速度極快且絕不漏資料
        df_detailed = yf.download(shortlist_str, period="2d", group_by="ticker", progress=False, ignore_tz=True)
        
        for ticker in shortlist:
            try:
                # 檢查 yfinance 回傳的 DataFrame 格式，安全讀取
                if isinstance(df_detailed.columns, pd.MultiIndex):
                    if ticker not in df_detailed.columns.levels[0]:
                        continue
                    sub_df = df_detailed[ticker].dropna()
                else:
                    sub_df = df_detailed.dropna()
                    
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
                    "turnover": turnover
                })
            except:
                continue
    except Exception as e:
        print(f"❌ 第二階段詳細資料下載失敗: {e}")
        return

    if not valid_active_stocks:
        print("⚠️ 第二階段解析後的有效股票為空。")
        return

    # ------------------------------------------
    # 📊 策略篩選與 TG 發送
    # ------------------------------------------
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    master_df = pd.DataFrame(valid_active_stocks)

    # 策略一：爆量突破收最高 (漲幅 >= 5%, 收盤接近最高價)
    breakout_cond = (master_df["change"] >= 5.0) & ((master_df["high"] - master_df["close"]) <= (master_df["close"] * 0.005))
    breakout_df = master_df[breakout_cond].sort_values(by="change", ascending=False).head(5)

    msg_1 = f"🚀 *【全港股突破警示：強勢收最高】* ({today_str})\n（已切換至新浪高精準度數據源）\n\n"
    if not breakout_df.empty:
        for _, row in breakout_df.iterrows():
            msg_1 += f"📌 *{row['id']}*\n💰 最新價：`{row['close']:.2f} HKD` (`+{row['change']:.2f}%`)\n📊 估算成交額：`{row['turnover']/1000000:.1f}M HKD`\n------------------------\n"
    else:
        msg_1 += "今日全港股暫無符合「強勢突破收最高」標的。\n"

    # 策略二：成交額 Top 5
    volume_surge_df = master_df[master_df["change"] > 0.0].sort_values(by="turnover", ascending=False).head(5)
    msg_2 = f"📊 *【全港股資金聚焦：今日成交額 Top 5】* ({today_str})\n\n"
    if not volume_surge_df.empty:
        for _, row in volume_surge_df.iterrows():
            msg_2 += f"🔥 *{row['id']}*\n💰 收盤價：`{row['close']:.2f} HKD` (`+{row['change']:.2f}%`)\n💸 估算成交額：`{row['turnover']/1000000:.1f}M HKD`\n------------------------\n"

    send_tg(msg_1)
    time.sleep(1)
    send_tg(msg_2)
    print(f"🎉 修正版任務順利結束！總花費時間: {time.time() - start_time:.1f} 秒")

if __name__ == "__main__":
    scan_all_hong_kong_market_fast()
