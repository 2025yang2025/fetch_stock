import os
import sys
import requests
import datetime
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
# 📊 策略二：全市場法人籌碼跟單掃描 (建議傍晚 17:00 執行)
# ==========================================
def scan_strategy_2_chips():
    print("📊 啟動 [策略二：全市場法人籌碼跟單掃描]...")
    api = get_api()
    
    # 取得今天與 10 天前的日期字串
    today_dt = datetime.datetime.now()
    today_str = today_dt.strftime("%Y-%m-%d")
    start_date = (today_dt - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
    
    try:
        print(f"1. 開始下載從 {start_date} 到 {today_str} 的全市場法人籌碼資料...")
        df_chips = api.taiwan_stock_institutional_investors_buy_sell(start_date=start_date)
        
        if df_chips.empty:
            print("⚠️ 警告：無法取得任何法人籌碼資料。")
            send_tg("⚠️ 【策略二通知】目前無法取得法人籌碼資料，請稍後再試。")
            return
            
        print(f"2. 資料下載成功！總共 {len(df_chips)} 筆。開始確認最新資料日期...")
        
        # 核心防護：找出這份籌碼資料庫裡最新的日期是什麼時候 (如果是下午 3 點，最新通常是昨天)
        available_dates = sorted(df_chips["date"].unique(), reverse=True)
        latest_available_date = available_dates[0]
        
        print(f"💡 資料庫最新可用日期為: {latest_available_date}")
        
        # 篩選出最新那一天的籌碼
        df_today = df_chips[df_chips["date"] == latest_available_date]
        
        # 3. 篩選投信與外資買超排行 (單位：股數，轉為張數)
        print("3. 開始計算投信與外資買超排行...")
        
        # 投信
        investment_trust = df_today[df_today["name"] == "Investment_Trust"]
        top_it = investment_trust.sort_values(by="buy", ascending=False).head(5)
        
        # 外資
        foreign_investor = df_today[df_today["name"] == "Foreign_Investor"]
        top_fi = foreign_investor.sort_values(by="buy", ascending=False).head(5)
        
        # 4. 組裝 Telegram 訊息
        msg = f"📊 *【策略二：盤後法人籌碼跟單】*\n"
        msg += f"📅 籌碼日期：`{latest_available_date}`\n"
        if latest_available_date != today_str:
            msg += f"⚠️ *備註*：今日最新籌碼尚未公佈，自動顯示前一交易日資料。\n"
        msg += "------------------------\n\n"
        
        msg += "🎯 *投信力挺買超前五名：*\n"
        if not top_it.empty:
            for _, row in top_it.iterrows():
                msg += f"▪️ `{row['stock_id']}`：買超 {int(row['buy']/1000)} 張 | 賣超 {int(row['sell']/1000)} 張\n"
        else:
            msg += "暫無資料\n"
            
        msg += "\n👽 *外資現蹤買超前五名：*\n"
        if not top_fi.empty:
            for _, row in top_fi.iterrows():
                msg += f"▪️ `{row['stock_id']}`：買超 {int(row['buy']/1000)} 張 | 賣超 {int(row['sell']/1000)} 張\n"
        else:
            msg += "暫無資料\n"
            
        msg += "\n💡 *提示*：中小型股跟著「投信作帳」走，通常波段勝率較高。"
        
        print("4. 嘗試發送訊息至 Telegram...")
        success = send_tg(msg)
        if success:
            print("✨ Telegram 訊息發送成功！")
        else:
            print("❌ Telegram 訊息發送失敗，請檢查 Token 與 Chat ID。")
            
    except Exception as e:
        print(f"❌ 策略二執行時發生重大錯誤: {e}")
        send_tg(f"❌ 策略二執行錯誤: {e}")

# ==========================================
# 📑 策略三：定期基本面營收雙增篩選 (建議每週六執行)
# ==========================================
def scan_strategy_3_fundamental():
    print("📑 啟動 [策略三：定期基本面營收雙增篩選]...")
    api = get_api()
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    # 營收按月公布，抓過去 2 個月的資料來進行比對
    start_date = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    
    try:
        # 注意：全市場月營收資料量大，這裡我們隨機抽樣或示範邏輯
        # 實務上可以針對特定的熱門股清單，或者直接撈取最新月份營收
        df_revenue = api.taiwan_stock_month_revenue(start_date=start_date)
        if df_revenue.empty:
            send_tg("⚠️ 【策略三失敗】無法獲取最新月份營收資料。")
            return
            
        # 找出最新公佈的月份
        latest_date = df_revenue["date"].max()
        df_latest = df_revenue[df_revenue["date"] == latest_date]
        
        # 篩選條件：營收月增率 (revenue_month_growth_rate) > 0 且 營收年增率 (revenue_year_growth_rate) > 20%
        # 並且排除代號非4碼的標的
        df_latest["stock_id"] = df_latest["stock_id"].astype(str)
        growth_stocks = df_latest[
            (df_latest["revenue_month_growth_rate"] > 0) & 
            (df_latest["revenue_year_growth_rate"] > 20) &
            (df_latest["stock_id"].str.len() == 4)
        ]
        
        # 依照年增率排序取前 8 檔
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
    except Exception as e:
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
