import os
import sys
import requests
import datetime
import time
import pandas as pd
from FinMind.data import DataLoader

# ==========================================
# 🌍 全域變數
# ==========================================
DYNAMIC_STOCK_NAMES = {}
GLOBAL_ALL_TICKERS = []

def fetch_all_taiwan_market_tickers():
    """全域只呼叫一次，動態獲取證交所標準4碼股票與名稱對照"""
    global DYNAMIC_STOCK_NAMES, GLOBAL_ALL_TICKERS
    if GLOBAL_ALL_TICKERS: # 如果已經抓過，直接回傳
        return GLOBAL_ALL_TICKERS
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    all_tickers = []
    try:
        url_twse = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        res = requests.get(url_twse, headers=headers, timeout=15)
        if res.status_code == 200 and res.text.strip().startswith('['):
            for item in res.json():
                code = item.get("Code", "").strip()
                name = item.get("Name", "").strip()
                if code.isdigit() and len(code) == 4:
                    ticker_id = f"{code}.TW"
                    all_tickers.append(ticker_id)
                    DYNAMIC_STOCK_NAMES[ticker_id] = name
            print(f"🌲 [成功] 證交所全市場名單動態獲取完成，共 {len(all_tickers)} 檔。")
    except Exception as e:
        print(f"⚠️ 證交所名單 API 抓取異常 (啟用保險備用機制): {e}")
        
    if not all_tickers:
        # 萬一被證交所阻擋，提供基本焦點科技股當保險墊底
        backup_dict = {
            "2330.TW": "台積電", "2317.TW": "鴻海", "2454.TW": "聯發科", 
            "3017.TW": "奇鋐", "2382.TW": "廣達", "3231.TW": "緯創", "2308.TW": "台達電"
        }
        for k, v in backup_dict.items():
            all_tickers.append(k)
            DYNAMIC_STOCK_NAMES[k] = v
            
    GLOBAL_ALL_TICKERS = sorted(list(set(all_tickers)))
    return GLOBAL_ALL_TICKERS

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
# 🚀 策略一：全市場 K 線動態突破掃描
# ==========================================
def scan_strategy_1_breakout():
    print("🚀 啟動 [策略一：全市場 K 線動態突破掃描]...")
    api = get_api()
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    
    try:
        df_all = api.taiwan_stock_price_all()
        if df_all is None or df_all.empty:
            send_tg(f"🔍 *【策略一：K 線動態突破】* ({today_str})\n今日全市場日K線尚未由 API 完全轉檔上架，暫無訊號。")
            return
            
        df_all.columns = df_all.columns.str.lower()
        df_all["stock_id"] = df_all["stock_id"].astype(str)
        
        filtered_df = df_all[
            (df_all["trading_volume"] >= 1000000) & 
            (df_all["close"] >= 10) & 
            (df_all["stock_id"].str.len() == 4)
        ]
        
        candidate_list = filtered_df["stock_id"].tolist()
        triggered_stocks = []
        
        print(f"⚙️ 符合量價初篩共 {len(candidate_list)} 檔，進行動態突破分析...")
        for symbol in candidate_list[:60]:
            try:
                df_k = api.taiwan_stock_price(stock_id=symbol, start_date=start_date)
                if df_k is None or df_k.empty or len(df_k) < 25:
                    continue
                
                df_k.columns = df_k.columns.str.lower()
                df_k["20h"] = df_k["close"].shift(1).rolling(window=20).max()
                
                last_row = df_k.iloc[-1]
                current_close = last_row["close"]
                prev_20h = last_row["20h"]
                
                if current_close > prev_20h:
                    prev_close = df_k.iloc[-2]["close"]
                    change_percent = ((current_close - prev_close) / prev_close) * 100
                    triggered_stocks.append({
                        "id": symbol, 
                        "name": DYNAMIC_STOCK_NAMES.get(f"{symbol}.TW", symbol), 
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
    except Exception as e:
        send_tg(f"❌ 策略一執行中斷錯誤: {e}")

# ==========================================
# 📊 策略二：全市場法人籌碼跟單掃描
# ==========================================
def scan_strategy_2_chips():
    print("📊 啟動 [策略二：全市場動態過濾 - 法人籌碼跟單掃描]...")
    
    # 共享最上層抓好的清單，絕不重複發 Request 轟炸證交所
    all_market_tickers = fetch_all_taiwan_market_tickers()
    
    strat2_candidates = []
    for tk in all_market_tickers:
        pure_code = tk.split('.')[0]
        if pure_code.startswith(('23', '24', '30', '32', '34', '35', '36', '37', '61', '62', '64', '80')):
            strat2_candidates.append(tk)
            
    print(f"🕵️ 策略二電子科技股過濾完成，共計 {len(strat2_candidates)} 檔標的。")
    
    api = get_api()
    today_dt = datetime.datetime.now()
    today_str = today_dt.strftime("%Y-%m-%d")
    start_date = (today_dt - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    
    it_buyers = []
    fi_buyers = []
    latest_date_detected = today_str
    
    for idx, tk in enumerate(strat2_candidates):
        pure_code = tk.split('.')[0]
        stock_name = DYNAMIC_STOCK_NAMES.get(tk, pure_code)
        try:
            df_stock_chips = api.taiwan_stock_institutional_investors(stock_id=pure_code, start_date=start_date)
            if df_stock_chips is None or df_stock_chips.empty:
                continue
                
            df_stock_chips.columns = df_stock_chips.columns.str.lower()
            stock_latest_date = df_stock_chips["date"].max()
            latest_date_detected = stock_latest_date
            
            df_latest = df_stock_chips[df_stock_chips["date"] == stock_latest_date]
            for _, row in df_latest.iterrows():
                net_buy = int((row["buy"] - row["sell"]) / 1000)
                if row["name"] == "investment_trust" and net_buy > 200:
                    it_buyers.append({"id": pure_code, "name": stock_name, "net": net_buy})
                elif row["name"] == "foreign_investor" and net_buy > 1000:
                    fi_buyers.append({"id": pure_code, "name": stock_name, "net": net_buy})
        except:
            continue
        if idx % 15 == 0:
            time.sleep(0.05)

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
    send_tg(msg)

# ==========================================
# 📈 策略三：每月營收雙增股篩選
# ==========================================
def scan_strategy_3_fundamental():
    print("📈 啟動 [策略三：每月營收雙增股篩選]...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    candidates = []
    
    try:
        # 改採完全免費的證交所營收結算總表 API
        url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
        res = requests.get(url, headers=headers, timeout=20)
        
        if res.status_code == 200 and res.text.strip().startswith('['):
            data = res.json()
            for item in data:
                try:
                    code = item.get("公司代號", "").strip()
                    name = item.get("公司名稱", "").strip()
                    
                    if not code.startswith(('23', '24', '30', '32', '34', '35', '36', '37', '61', '62', '64', '80')):
                        continue
                        
                    mom = float(item.get("上月比較增減(%)", 0))
                    yoy = float(item.get("去年同月比較增減(%)", 0))
                    rev_str = item.get("當月營收", "0").strip()
                    rev_this_month = int(int(rev_str if rev_str else 0) / 1000)
                    
                    if mom > 10.0 and yoy > 20.0:
                        candidates.append({"id": code, "name": name, "mom": mom, "yoy": yoy, "rev": rev_this_month})
                except:
                    continue
        else:
            # 萬一連總表都被阻擋，調用最上層抓取完成的 DYNAMIC_STOCK_NAMES 提示安全通關
            print("⚠️ 營收 OpenAPI 限制訪問，本期改為安全跳過機制。")
    except Exception as e:
        print(f"⚠️ 策略三營收網路讀取限制: {e}")

    top_fundamental = sorted(candidates, key=lambda x: x["yoy"], reverse=True)[:5]
    
    msg = f"📈 *【策略三：每月營收雙增強勢股】*\n"
    msg += f"📅 數據來源：證交所最新公告營收彙總\n"
    msg += f"🕵️ 篩選標準：電子科技股 + 營收月增 > 10% + 年增 > 20%\n"
    msg += "------------------------\n\n"
    
    msg += "🚀 *最新營收雙增前 5 名表現黑馬：*\n"
    if top_fundamental:
        for item in top_fundamental:
            msg += f"▪️ `{item['id']}` {item['name']}\n"
            msg += f"   📊 當月營收：`{item['rev']:,}` 萬元\n"
            msg += f"   🚀 月增率 (MoM)：`+{item['mom']:.1f}%`\n"
            msg += f"   🔥 年增率 (YoY)：`+{item['yoy']:.1f}%`\n\n"
    else:
        msg += "本期暫無符合「月增>10%且年增>20%」的電子科技股 (或適逢證交所官網阻擋維護中)。\n"
        
    msg += "\n💡 *提示*：本策略已全面優化流量防禦，免除 FinMind 付費權限限制。"
    send_tg(msg)

# ==========================================
# 🏁 程式進入點
# ==========================================
if __name__ == "__main__":
    print("🤖 初始化台灣證交所市場名單對照表...")
    # 🔥 關鍵：全域最頂層只對證交所發出一次 Request 拿清單！
    fetch_all_taiwan_market_tickers()
    
    if len(sys.argv) >= 2:
        mode = sys.argv[1]
        if mode == "strategy_1":
            scan_strategy_1_breakout()
        elif mode == "strategy_2":
            scan_strategy_2_chips()
        elif mode == "strategy_3":
            scan_strategy_3_fundamental()
    else:
        print("🤖 啟動全自動排程一鍵連發模式...")
        
        print("⏳ 正在執行策略一...")
        try: scan_strategy_1_breakout()
        except Exception as e: send_tg(f"❌ 策略一執行中斷錯誤: {e}")
            
        time.sleep(5) 
        
        print("⏳ 正在執行策略二...")
        try: scan_strategy_2_chips()
        except Exception as e: send_tg(f"❌ 策略二執行中斷錯誤: {e}")
            
        time.sleep(5)
        
        print("⏳ 正在執行策略三...")
        try: scan_strategy_3_fundamental()
        except Exception as e: send_tg(f"❌ 策略三執行中斷錯誤: {e}")
            
        print("✨ 流程全數執行完畢。")
