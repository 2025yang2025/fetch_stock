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
# ⚡ 全港股極速粗篩（自動相容週末/休市）
# ==========================================
def fetch_hk_shortlist_auto():
    """
    優先嘗試新浪即時 API，如果遇到週末（成交額全為 0），
    則自動透過常用的藍籌與活躍股群組進行 yfinance 歷史數據回溯，確保週末也能跑出週五的報告。
    """
    print("🌐 正在抓取港股流動性數據...")
    shortlist = []
    
    # 嘗試從新浪獲取
    for page in range(1, 6):
        url = f"https://vip.stock.finance.sina.com.cn/hq/api/jsonp.php/IO.XSRV2.CallbackList['hk']/HK_Service.getMainMethodPageList?page={page}&num=80&sort=amount&asc=0"
        try:
            response = requests.get(url, timeout=10)
            text = response.text
            if "bracket" in text or "CallbackList" in text:
                left = text.find("[")
                right = text.rfind("]") + 1
                text = text[left:right]
            
            data = pd.read_json(text)
            if data.empty:
                break
                
            for _, row in data.iterrows():
                raw_code = str(row['symbol'])
                pure_code = raw_code[-4:] if len(raw_code) == 5 else raw_code
                ticker = f"{int(pure_code):04d}.HK"
                
                trade = float(row['trade'])      
                turnover = float(row['amount'])  
                
                # 如果開盤日有正常成交額
                if trade >= 1.0 and turnover >= 8000000:
                    shortlist.append(ticker)
        except:
            continue
            
    shortlist = list(set(shortlist))
    
    # 🎯 週末/休市應變防禦：如果新浪篩出來是空的（例如週六），
    # 我們改用「港股前 150 大核心活躍股」名單強制進行歷史回溯（抓週五最後一天的K線）
    if not shortlist:
        print("⚠️ 偵測到當前可能為休市期間（成交額為0），啟動核心活躍股回溯機制...")
        # 這裡精選了港股交易最頻繁、最容易出現突破的主板核心代號區間
        backup_tickers = []
        # 精選主板最活躍的精華段（涵蓋騰訊、美團、阿里、比亞迪等核心標的）
        for i in [1, 2, 3, 4, 5, 6, 11, 12, 16, 17, 27, 66, 175, 241, 267, 288, 386, 388, 700, 762, 857, 883, 941, 960, 981, 992, 1024, 1088, 1093, 1109, 1113, 1177, 1211, 1299, 1398, 1810, 1928, 2015, 2020, 2269, 2313, 2318, 2319, 2331, 2333, 2382, 2388, 2628, 3690, 3968, 3988, 6030, 9618, 9868, 9888, 9961, 9988, 9999]:
            backup_tickers.append(f"{i:04d}.HK")
        return backup_tickers
        
    return shortlist

# ==========================================
# 🚀 第二階段：精準分析與發送
# ==========================================
def scan_all_hong_kong_market_fast():
    start_time = time.time()
    
    shortlist = fetch_hk_shortlist_auto()
    
    print(f"\n🚀 【深度分析階段】正在分析 {len(shortlist)} 檔核心港股最近 2 個交易日的 K 線...")
    valid_active_stocks = []
    
    shortlist_str = " ".join(shortlist)
    try:
        # 下載最近 2 天的歷史數據 (如果今天是週六，yf 會自動抓週四與週五的資料，完美銜接！)
        df_detailed = yf.download(shortlist_str, period="2d", group_by="ticker", progress=False, ignore_tz=True)
        
        for ticker in shortlist:
            try:
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
                
                # 在這裡做二次流動性檢查（適用於週末回溯時過濾掉週五成交量不夠的股票）
                if today_close >= 1.0 and turnover >= 8000000:
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
        print(f"❌ 詳細資料下載失敗: {e}")
        return

    if not valid_active_stocks:
        send_tg("🔍 *【港股掃描】*\n近期選定標的流動性未達 800 萬港幣閥值。")
        return

    # ------------------------------------------
    # 📊 策略篩選與 TG 發送
    # ------------------------------------------
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    master_df = pd.DataFrame(valid_active_stocks)

    # 策略一：爆量突破收最高 (漲幅 >= 5%, 收盤接近最高價)
    breakout_cond = (master_df["change"] >= 5.0) & ((master_df["high"] - master_df["close"]) <= (master_df["close"] * 0.005))
    breakout_df = master_df[breakout_cond].sort_values(by="change", ascending=False).head(5)

    msg_1 = f"🚀 *【全港股突破警示：強勢收最高】* ({today_str})\n（已啟動週末/休市自動回溯相容機制）\n\n"
    if not breakout_df.empty:
        for _, row in breakout_df.iterrows():
            msg_1 += f"📌 *{row['id']}*\n💰 價格：`{row['close']:.2f} HKD` (`+{row['change']:.2f}%`)\n📊 成交額：`{row['turnover']/1000000:.1f}M HKD`\n------------------------\n"
    else:
        msg_1 += "該交易區間暫無符合「強勢突破收最高」標的。\n"

    # 策略二：成交額 Top 5
    volume_surge_df = master_df[master_df["change"] > 0.0].sort_values(by="turnover", ascending=False).head(5)
    msg_2 = f"📊 *【全港股資金聚焦：成交額 Top 5】* ({today_str})\n\n"
    if not volume_surge_df.empty:
        for _, row in volume_surge_df.iterrows():
            msg_2 += f"🔥 *{row['id']}*\n💰 收盤價：`{row['close']:.2f} HKD` (`+{row['change']:.2f}%`)\n💸 今日成交額：`{row['turnover']/1000000:.1f}M HKD`\n------------------------\n"

    send_tg(msg_1)
    time.sleep(1)
    send_tg(msg_2)
    print(f"🎉 任務順利結束！總花費時間: {time.time() - start_time:.1f} 秒")

if __name__ == "__main__":
    scan_all_hong_kong_market_fast()
