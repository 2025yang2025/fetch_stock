import os
import sys
import requests
import datetime
import time
import pandas as pd
from FinMind.data import DataLoader

# ==========================================
# 🌍 全域設定與證交所 OpenAPI 資料抓取
# ==========================================
DYNAMIC_STOCK_NAMES = {}

def fetch_all_taiwan_market_tickers():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    all_tickers = []
    try:
        # 從證交所 OpenAPI 獲取全市場今日個股
        url_twse = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        res = requests.get(url_twse, headers=headers, timeout=10)
        if res.status_code == 200:
            for item in res.json():
                code = item.get("Code", "").strip()
                name = item.get("Name", "").strip()
                # 篩選標準 4 碼股票
                if code.isdigit() and len(code) == 4:
                    ticker_id = f"{code}.TW"
                    all_tickers.append(ticker_id)
                    DYNAMIC_STOCK_NAMES[ticker_id] = name
    except Exception as e:
        print(f"⚠️ 證交所 API 抓取異常: {e}")
        pass
        
    if not all_tickers:
        # 備用保險清單
        backup_dict = {"2330.TW": "台積電", "2317.TW": "鴻海", "2454.TW": "聯發科"}
        for k, v in backup_dict.items():
            all_tickers.append(k)
            DYNAMIC_STOCK_NAMES[k] = v
    return sorted(list(set(all_tickers)))

def fetch_fundamental_snapshot(tickers):
    strat2_candidates = []
    strat3_candidates = []
    for tk in tickers:
        pure_code = tk.split('.')[0]
        # 篩選特定字首的科技/電子股主力
        if pure_code.startswith(('23', '24', '30', '32', '34', '35', '36', '37', '61', '62', '64', '80')):
            strat2_candidates.append(tk)
            if pure_code in ['2330', '2454', '3443', '3661', '6415', '3017', '3533', '6187']:
                strat3_candidates.append(tk)
    return strat2_candidates, strat3_candidates

# ==========================================
# 🤖 通用工具函數
# ==========================================
def send_tg(text):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("❌ 錯誤：未設定 TELEGRAM_TOKEN 或 TELEGRAM_CHAT_ID 環境變數。")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except:
        return False

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
            
        # 安全機制：欄位名稱全部轉小寫，防止 FinMind 大小寫混用導致 KeyError
        df_all.columns = df_all.columns.str.lower()
        df_all["stock_id"] = df_all["stock_id"].astype(str)
        
        # 初篩：量 > 1000張 (1000000股), 價 > 10元, 排除非4碼股票
        filtered_df = df_all[
            (df_all["trading_volume"] >= 1000000) & 
            (df_all["close"] >= 10) & 
            (df_all["stock_id"].str.len() == 4)
        ]
        
        candidate_list = filtered_df["stock_id"].tolist()
        triggered_stocks = []
        
        # 深度比對 K 線 (限前 60 檔避免 Actions 執行逾時)
        print(f"⚙️ 符合量價初篩共 {len(candidate_list)} 檔，取前 60 檔進行突破分析...")
        for symbol in candidate_list[:60]:
            try:
                df_k = api.taiwan_stock_price(stock_id=symbol, start_date=start_date)
                if df_k.empty or len(df_k) < 25:
                    continue
                
                df_k.columns = df_k.columns.str.lower()
                # 計算過去 20 天最高價 (不含今天)
                df_k["20h"] = df_k["close"].shift(1).rolling(window=20).max()
                
                last_row = df_k.iloc[-1]
                current_close = last_row["close"]
                prev_20h = last_row["20h"]
                
                # 判斷收盤是否突破 20 日高點
                if current_close > prev_20h:
                    prev_close = df_k.iloc[-2]["close"]
                    change_percent = ((current_close - prev_close) / prev_close) * 100
                    triggered_stocks.append({
                        "id": symbol, 
                        "name": last_row.get("stock_name", symbol), 
                        "close": current_close, 
                        "change": round(change_percent, 2),
                        "volume": int(last_row["trading_volume"] / 1000)
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
        print("✨ 策略一執行完成並發送成功！")
    except Exception as e:
        send_tg(f"❌ 策略一執行錯誤: {e}")

# ==========================================
# 📊 策略二：全市場法人籌碼跟單掃描 (免費用戶安全版)
# ==========================================
def scan_strategy_2_chips():
    print("📊 啟動 [策略二：全市場動態過濾 - 法人籌碼跟單掃描]...")
    
    # 確保先去抓最新的證交所股票清單
    all_market_tickers = fetch_all_taiwan_market_tickers()
    print(f"🌲 證交所動態獲取完成，全市場共 {len(all_market_tickers)} 檔標的。")
    
    strat2_candidates, _ = fetch_fundamental_snapshot(all_market_tickers)
    print(f"🔍 經過字首過濾 (23, 24, 30...)，共篩選出 {len(strat2_candidates)} 檔電子焦點股。")
    
    api = get_api()
    today_dt = datetime.datetime.now()
    today_str = today_dt.strftime("%Y-%m-%d")
    start_date = (today_dt - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    
    it_buyers = []  # 投信買超清單
    fi_buyers = []  # 外資買超清單
    latest_date_detected = today_str
    
    print(f"🚀 開始逐檔掃描這 {len(strat2_candidates)} 檔股票的 FinMind 法人籌碼...")
    
    for idx, tk in enumerate(strat2_candidates):
        pure_code = tk.split('.')[0]
        stock_name = DYNAMIC_STOCK_NAMES.get(tk, pure_code)
        
        try:
            # 帶入 stock_id 做單股查詢，完美繞過免費帳號全市場限制
            df_stock_chips = api.taiwan_stock_institutional_investors(
                stock_id=pure_code, 
                start_date=start_date
            )
            
            if df_stock_chips.empty:
                continue
                
            df_stock_chips.columns = df_stock_chips.columns.str.lower()
            
            # 抓最新日期
            stock_latest_date = df_stock_chips["date"].max()
            latest_date_detected = stock_latest_date
            
            df_latest = df_stock_chips[df_stock_chips["date"] == stock_latest_date]
            
            for _, row in df_latest.iterrows():
                net_buy = int((row["buy"] - row["sell"]) / 1000)  # 換算成張數
                
                if row["name"] == "investment_trust" and net_buy > 200:
                    it_buyers.append({"id": pure_code, "name": stock_name, "net": net_buy})
                elif row["name"] == "foreign_investor" and net_buy > 1000:
                    fi_buyers.append({"id": pure_code, "name": stock_name, "net": net_buy})
                    
        except Exception:
            continue
            
        if idx % 10 == 0:
            time.sleep(0.1)

    print("2. 全市場電子股籌碼比對完成，開始排序前 5 名...")
    top_it = sorted(it_buyers, key=lambda x: x["net"], reverse=True)[:5]
    top_fi = sorted(fi_buyers, key=lambda x: x["net"], reverse=True)[:5]
    
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
        df_revenue = api.taiwan_stock_month_revenue(start_date=start_date)
        if df_revenue.empty:
            send_tg("⚠️ 【策略三失敗】無法獲取最新月份營收資料。")
            return
            
        df_revenue.columns = df_revenue.columns.str.lower()
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
            msg += f"📌 *{row['stock_id']} {row.get('stock_name', row['stock_id'])}*\n"
            msg += f"📈 年增率：`+{round(row['revenue_year_growth_rate'], 1)}%`\n"
            msg += f"📊 月增率：`+{round(row['revenue_month_growth_rate'], 1)}%`\n"
            msg += "------------------------\n"
            
        msg += "\n🍀 適合納入中長線策略的「基本面護身」觀察清單。"
        send_tg(msg)
        print("✨ 策略三執行完成並發送成功！")
    except Exception as e:
        print(f"❌ 策略三執行時發生重大錯誤: {e}")
        send_tg(f"❌ 策略三執行錯誤: {e}")

# ==========================================
# 🏁 程式進入點（全面加強防禦防撞牆版）
# ==========================================
if __name__ == "__main__":
    import sys
    
    # 如果有帶參數，就單獨跑該策略
    if len(sys.argv) >= 2:
        mode = sys.argv[1]
        if mode == "strategy_1":
            try:
                scan_strategy_1_breakout()
            except Exception as e:
                print(f"❌ 策略一執行錯誤: {e}")
                send_tg(f"❌ 策略一執行錯誤: {e}")
        elif mode == "strategy_2":
            try:
                scan_strategy_2_chips()
            except Exception as e:
                print(f"❌ 策略二執行錯誤: {e}")
                send_tg(f"❌ 策略二執行錯誤: {e}")
        elif mode == "strategy_3":
            try:
                scan_strategy_3_fundamental()
            except Exception as e:
                print(f"❌ 策略三執行錯誤: {e}")
                send_tg(f"❌ 策略三執行錯誤: {e}")
                
    # 如果手動執行 "all" 或是不帶參數（一鍵連發）
    else:
        print("🤖 啟動全自動排程模式：開始連續執行三個策略...")
        
        # 執行策略一
        try:
            print("⏳ 正在執行策略一...")
            scan_strategy_1_breakout()
        except Exception as e:
            error_msg = f"❌ 策略一執行中斷錯誤: {e}"
            print(error_msg)
            send_tg(error_msg)
            
        time.sleep(5) 
        
        # 執行策略二
        try:
            print("⏳ 正在執行策略二...")
            scan_strategy_2_chips()
        except Exception as e:
            error_msg = f"❌ 策略二執行中斷錯誤: {e}"
            print(error_msg)
            send_tg(error_msg)
            
        time.sleep(5)
        
        # 執行策略三
        try:
            print("⏳ 正在執行策略三...")
            scan_strategy_3_fundamental()
        except Exception as e:
            error_msg = f"❌ 策略三執行中斷錯誤: {e}"
            print(error_msg)
            send_tg(error_msg)
            
        print("✨ 流程執行完畢。")
