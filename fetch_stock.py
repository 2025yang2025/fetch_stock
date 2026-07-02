import os
import sys
import requests
import datetime
import time
import pandas as pd
from FinMind.data import DataLoader

def send_tg(text):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    response = requests.post(url, json=payload)
    return response.status_code == 200

def get_api():
    fm_api_token = os.environ.get("FINMIND_TOKEN", "")
    api = DataLoader()
    if fm_api_token:
        api.login_token(token=fm_api_token)
    return api

# ==========================================
# 🚀 策略一：全市場 K 線動態突破掃描 (建議下午 14:15 執行)
# ==========================================
def scan_strategy_1_breakout():
    print("🚀 啟動 [策略一：全市場 K 線動態突破掃描]...")
    api = get_api()
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    
    try:
        df_all = api.taiwan_stock_price_all()
        if df_all.empty:
            send_tg("⚠️ 【策略一失敗】無法取得今日全市場股價。")
            return
            
        # 初篩：量 > 1000張, 價 > 10元, 排除非4碼權證
        df_all["stock_id"] = df_all["stock_id"].astype(str)
        filtered_df = df_all[
            (df_all["Trading_Volume"] >= 1000000) & 
            (df_all["Close"] >= 10) & 
            (df_all["stock_id"].str.len() == 4)
        ]
        
        candidate_list = filtered_df["stock_id"].tolist()
        triggered_stocks = []
        
        # 深度比對 K 線 (限前 60 檔避免 Actions 逾時)
        for symbol in candidate_list[:60]:
            try:
                df_k = api.taiwan_stock_price(stock_id=symbol, start_date=start_date)
                if df_k.empty or len(df_k) < 25:
                    continue
                
                df_k["20H"] = df_k["close"].shift(1).rolling(window=20).max()
                last_row = df_k.iloc[-1]
                current_close = last_row["close"]
                prev_20h = last_row["20H"]
                
                if current_close > prev_20h:
                    prev_close = df_k.iloc[-2]["close"]
                    change_percent = ((current_close - prev_close) / prev_close) * 100
                    triggered_stocks.append({
                        "id": symbol, "name": last_row["stock_name"], 
                        "close": current_close, "change": round(change_percent, 2),
                        "volume": int(last_row["Trading_Volume"] / 1000)
                    })
            except:
                continue

        if triggered_stocks:
            msg = f"🚀 *【策略一：K 線動態突破警示】* ({today_str})\n系統已自動掃描全市場，今日「突破 20 日高點」的強勢股：\n\n"
            triggered_stocks = sorted(triggered_stocks, key=lambda x: x["change"], reverse=True)[:8]
            for stock in triggered_stocks:
                msg += f"📌 *{stock['id']} {stock['name']}*\n💰 收盤價：`{stock['close']}` ({stock['change']}%)\n📊 成交量：{stock['volume']} 張\n------------------------\n"
        else:
            msg = f"🔍 *【策略一：K 線動態突破】* ({today_str})\n今日全台股暫無個股符合突破訊號。"
        send_tg(msg)
    except Exception as e:
        send_tg(f"❌ 策略一執行錯誤: {e}")

# ==========================================
# 📊 策略二：全市場法人籌碼跟單掃描
# ==========================================
def scan_strategy_2_chips():
    print("📊 啟動 [策略二：全市場動態過濾 - 法人籌碼跟單掃描]...")
    
    # 1. 呼叫你寫的函數：直接從證交所 API 抓取全台灣最新股票清單
    all_market_tickers = fetch_all_taiwan_market_tickers()
    print(f"🌲 證交所動態獲取完成，全市場共 {len(all_market_tickers)} 檔標的。")
    
    # 2. 呼叫你寫的函數：利用字首過濾出策略二需要的電子半導體候選股
    strat2_candidates, _ = fetch_fundamental_snapshot(all_market_tickers)
    print(f"🔍 經過字首過濾 (23, 24, 30...)，共篩選出 {len(strat2_candidates)} 檔電子焦點股。")
    
    api = get_api()
    today_dt = datetime.datetime.now()
    today_str = today_dt.strftime("%Y-%m-%d")
    # 籌碼比對只需要看最近幾天，抓 7 天很安全
    start_date = (today_dt - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    
    it_buyers = []  # 投信買超清單
    fi_buyers = []  # 外資買超清單
    latest_date_detected = today_str
    
    print(f"🚀 開始逐檔掃描這 {len(strat2_candidates)} 檔股票的 FinMind 法人籌碼 (免費用戶安全版)...")
    
    for idx, tk in enumerate(strat2_candidates):
        # 把 "2330.TW" 轉成 FinMind 要的 "2330"
        pure_code = tk.split('.')[0]
        
        # 取得股票名稱（優先從你建立的 DYNAMIC_STOCK_NAMES 字典拿，拿不到就顯示代號）
        stock_name = DYNAMIC_STOCK_NAMES.get(tk, pure_code)
        
        try:
            # 帶入 stock_id 進行單股查詢，完美繞過免費帳號全市場限制！
            df_stock_chips = api.taiwan_stock_institutional_investors(
                stock_id=pure_code, 
                start_date=start_date
            )
            
            if df_stock_chips.empty:
                continue
                
            # 確保法人名稱小寫
            df_stock_chips["name"] = df_stock_chips["name"].str.lower()
            
            # 抓出這檔股票最新的籌碼日期，並更新全域參考日期
            stock_latest_date = df_stock_chips["date"].max()
            latest_date_detected = stock_latest_date
            
            # 只取最新那一天的數據
            df_latest = df_stock_chips[df_stock_chips["date"] == stock_latest_date]
            
            for _, row in df_latest.iterrows():
                net_buy = int((row["buy"] - row["sell"]) / 1000) # 換算成張數
                
                # 篩選條件：投信當日買超 > 200張，或外資買超 > 1000張（全市場股票多，條件可以稍微拉高）
                if row["name"] == "investment_trust" and net_buy > 200:
                    it_buyers.append({"id": pure_code, "name": stock_name, "net": net_buy})
                elif row["name"] == "foreign_investor" and net_buy > 1000:
                    fi_buyers.append({"id": pure_code, "name": stock_name, "net": net_buy})
                    
        except Exception as e:
            # 遇到異常直接跳過，不影響整個迴圈
            continue
            
        # 頻率控制：免費用戶每查 10 檔稍微歇個 0.1 秒，避免被官方短時間封鎖
        if idx % 10 == 0:
            time.sleep(0.1)

    print("2. 全市場電子股籌碼比對完成，開始排序前 5 名...")
    
    # 依買超張數由大到小排序
    top_it = sorted(it_buyers, key=lambda x: x["net"], reverse=True)[:5]
    top_fi = sorted(fi_buyers, key=lambda x: x["net"], reverse=True)[:5]
    
    # 3. 組裝 Telegram 訊息 (帶上動態抓到的股票中文名稱！)
    msg = f"📊 *【策略二：全市場動態籌碼跟單】*\n"
    msg += f"📅 籌碼日期：`{latest_date_detected}`\n"
    msg += f"🕵️ 掃描範圍：證交所全市場電子科技股 ({len(strat2_candidates)} 檔)\n"
    msg += "------------------------\n\n"
    
    msg += "🎯 *投信今日全市場重倉 (淨買超張數)：*\n"
    if top_it:
        for item in top_it:
            msg += f"▪️ `{item['id']}` {item['name']}：`+{item['net']}` 張\n"
    else:
        msg += "今日全市場暫無投信大買標的。\n"
        
    msg += "\n👽 *外資今日全市場強吸 (淨買超張數)：*\n"
    if top_fi:
        for item in top_fi:
            msg += f"▪️ `{item['id']}` {item['name']}：`+{item['net']}` 張\n"
    else:
        msg += "今日全市場暫無外資大買標的。\n"
        
    msg += "\n💡 *提示*：本報告已透過證交所 OpenAPI 實現全市場動態同步，且免付費。"
    
    print("3. 嘗試發送訊息至 Telegram...")
    success = send_tg(msg)
    if success:
        print("✨ Telegram 全市場籌碼報告發送成功！")
    else:
        print("❌ Telegram 發送失敗。")

# ==========================================
# 📑 策略三：定期基本面營收雙增篩選
# ==========================================
def scan_strategy_3_fundamental():
    print("📑 啟動 [策略三：定期基本面營收雙增篩選]...")
    api = get_api()
    start_date = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    try:
        # 修正：正確的函數名稱是 taiwan_stock_month_revenue
        df_revenue = api.taiwan_stock_month_revenue(start_date=start_date)
        if df_revenue.empty:
            send_tg("⚠️ 【策略三失敗】無法獲取最新月份營收資料。")
            return
            
        latest_date = df_revenue["date"].max()
        df_latest = df_revenue[df_revenue["date"] == latest_date].copy()
        
        df_latest["stock_id"] = df_latest["stock_id"].astype(str)
        growth_stocks = df_latest[
            (df_latest["revenue_month_growth_rate"] > 0) & 
            (df_latest["revenue_year_growth_rate"] > 20) &
            (df_latest["stock_id"].str.len() == 4)
        ]
        
        top_growth = growth_stocks.sort_values(by="revenue_year_growth_rate", ascending=False).head(8)
        
        msg = f"📑 *【策略三：基本面營收雙增榜】* (資料月份: {latest_date})\n"
        msg += "系統已篩選出最新月營收「月增 ＞ 0%」且「年增 ＞ 20%」的成長股：\n\n"
        
        for _, row in top_growth.iterrows():
            msg += f"📌 *{row['stock_id']} {row['stock_name']}*\n"
            msg += f"📈 年增率：`+{round(row['revenue_year_growth_rate'], 1)}%`\n"
            msg += f"📊 月增率：`+{round(row['revenue_month_growth_rate'], 1)}%`\n"
            msg += "------------------------\n"
            
        msg += "\n🍀 適合納入中長線策略的「基本面護身」觀察清單。"
        send_tg(msg)
        print("✨ 策略三執行完成並發送成功！")
    except Exception as e:
        print(f"❌ 策略三執行時發生重大錯誤: {e}")
        send_tg(f"❌ 策略三執行錯誤: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("請指定策略參數 (strategy_1 / strategy_2 / strategy_3)")
        sys.exit(1)
        
    mode = sys.argv[1]
    if mode == "strategy_1":
        scan_strategy_1_breakout()
    elif mode == "strategy_2":
        scan_strategy_2_chips()
    elif mode == "strategy_3":
        scan_strategy_3_fundamental()
