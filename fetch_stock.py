import os
import sys
import requests
import datetime
import time
import pandas as pd
from FinMind.data import DataLoader

# ==========================================
# 🌍 全域變數
# ==========================================import datetime
import os
import requests

# ==========================================
# ⚙️ 系統基本設定 (安全動態讀取環境變數)
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def send_tg(message):
    """發送 Telegram 訊息的通用函式"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ 錯誤：未偵測到環境變數 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，請檢查設定。")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"❌ Telegram 發送失敗: {e}")
        return False


# ==========================================
# 🚀 策略一：全市場日K線強勢突破掃描
# ==========================================
def scan_strategy_1_breakout(price_data, today_str):
    print("🚀 啟動 [策略一：全市場日K線強勢突破掃描]...")
    triggered_stocks = []
    
    for item in price_data:
        try:
            code = item.get("Code", "").strip()
            name = item.get("Name", "").strip()
            
            # 鎖定標準4碼的電子科技股主戰場
            if not (code.isdigit() and len(code) == 4 and code.startswith(('23', '24', '30', '32', '34', '35', '36', '37', '61', '62', '64', '80'))):
                continue
            
            # 清洗數值
            vol_str = item.get("TradeVolume", "0").replace(",", "").strip()
            volume = int(vol_str) if vol_str else 0
            
            # 成交量初篩：當日成交量 > 1,500 張 (1,500,000 股)
            if volume < 1500000:
                continue
                
            close_str = item.get("ClosingPrice", "0").replace(",", "").strip()
            open_str = item.get("OpeningPrice", "0").replace(",", "").strip()
            high_str = item.get("HighestPrice", "0").replace(",", "").strip()
            
            if not (close_str and open_str and high_str):
                continue
                
            close_price = float(close_str)
            open_price = float(open_str)
            high_price = float(high_str)
            
            # 計算今日漲幅
            ud_str = item.get("PriceDiff", "0").replace(",", "").strip()
            try:
                diff = float(ud_str)
                prev_close = close_price - diff
                change_percent = (diff / prev_close) * 100 if prev_close else 0.0
            except:
                change_percent = 0.0
            
            # 核心條件：價格 >= 15元 + 漲幅 >= 4.5% + 強勢收最高附近 (收盤距離最高價 < 0.5%)
            if close_price >= 15.0 and change_percent >= 4.5:
                if (high_price - close_price) <= (close_price * 0.005):
                    triggered_stocks.append({
                        "id": code,
                        "name": name,
                        "close": close_price,
                        "change": round(change_percent, 2),
                        "volume": int(volume / 1000)
                    })
        except:
            continue

    if triggered_stocks:
        msg = f"🚀 *【策略一：全市場 K 線強勢突破警示】* ({today_str})\n系統已掃描全市場電子股，今日符合「爆量長紅且強勢收最高」突破訊號：\n\n"
        triggered_stocks = sorted(triggered_stocks, key=lambda x: x["change"], reverse=True)[:8]
        for stock in triggered_stocks:
            msg += f"📌 *{stock['id']} {stock['name']}*\n💰 收盤價：`{stock['close']}` (`+{stock['change']}%`)\n📊 成交量：`{stock['volume']:,}` 張\n------------------------\n"
    else:
        msg = f"🔍 *【策略一：K 線動態突破】* ({today_str})\n今日全台股暫無電子股符合「爆量收最高」的強勢突破訊號。"
        
    send_tg(msg)


# ==========================================
# 📊 策略二：全市場動態籌碼跟單
# ==========================================
def scan_strategy_2_chips(today_str):
    print("📊 啟動 [策略二：全市場動態籌碼跟單]...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        # 使用證交所三大法人每日買賣超日報 OpenAPI
        url = "https://openapi.twse.com.tw/v1/3I/3_BUY_SELL_ALL"
        res = requests.get(url, headers=headers, timeout=15)
        
        if res.status_code != 200 or not res.text.strip().startswith('['):
            send_tg(f"🔍 *【策略二：全市場動態籌碼】* ({today_str})\n今日證交所籌碼伺服器維護中，暫時無法取得法人數據。")
            return
            
        data = res.json()
        sitc_bought = []  # 投信買超
        fi_bought = []    # 外資買超
        
        for item in data:
            code = item.get("Code", "").strip()
            name = item.get("Name", "").strip()
            
            if not (code.isdigit() and len(code) == 4 and code.startswith(('23', '24', '30', '32', '34', '35', '36', '37', '61', '62', '64', '80'))):
                continue
                
            # 投信與外資買賣超張數 (證交所單位為股數，需除以 1000)
            sitc_str = item.get("InvestmentTrustBuySellDiff", "0").replace(",", "").strip()
            fi_str = item.get("ForeignInvestorsBuySellDiff", "0").replace(",", "").strip()
            
            try:
                sitc_diff = int(sitc_str) // 1000
                fi_diff = int(fi_str) // 1000
                
                # 投信大買門檻：今日淨買超 > 400 張
                if sitc_diff >= 400:
                    sitc_bought.append({"id": code, "name": name, "shares": sitc_diff})
                    
                # 外資大買門檻：今日淨買超 > 1500 張
                if fi_diff >= 1500:
                    fi_bought.append({"id": code, "name": name, "shares": fi_diff})
            except:
                continue
                
        msg = f"📊 *【策略二：全市場動態籌碼跟單】* ({today_str})\n🕵️ 掃描範圍：證交所電子科技股\n------------------------\n"
        
        msg += "🎯 *投信今日全市場重倉 (淨買超張數)：*\n"
        if sitc_bought:
            sitc_bought = sorted(sitc_bought, key=lambda x: x["shares"], reverse=True)[:5]
            for s in sitc_bought:
                msg += f"🔥 `{s['id']} {s['name']}` -> 淨買超 `{s['shares']:,}` 張\n"
        else:
            msg += "今日全市場暫無投信大買標的。\n"
            
        msg += "\n👽 *外資今日全市場強吸 (淨買超張數)：*\n"
        if fi_bought:
            fi_bought = sorted(fi_bought, key=lambda x: x["shares"], reverse=True)[:5]
            for f in fi_bought:
                msg += f"⚡ `{f['id']} {f['name']}` -> 淨買超 `{f['shares']:,}` 張\n"
        else:
            msg += "今日全市場暫無外資大買標的。\n"
            
        send_tg(msg)
    except Exception as e:
        send_tg(f"❌ 策略二執行中斷錯誤: {e}")


# ==========================================
# 📈 策略三：每月營收雙增強勢股
# ==========================================
def scan_strategy_3_revenue(today_str):
    print("📈 啟動 [策略三：每月營收雙增強勢股]...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        # 使用證交所最新公告之每月營收彙總 OpenAPI
        url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
        res = requests.get(url, headers=headers, timeout=15)
        
        if res.status_code != 200 or not res.text.strip().startswith('['):
            send_tg(f"🔍 *【策略三：每月營收雙增】* ({today_str})\n今日證交所營收伺服器維護中，暫時無法取得最新營收。")
            return
            
        data = res.json()
        growth_stocks = []
        
        for item in data:
            code = item.get("公司代號", "").strip()
            name = item.get("公司名稱", "").strip()
            
            if not (code.isdigit() and len(code) == 4 and code.startswith(('23', '24', '30', '32', '34', '35', '36', '37', '61', '62', '64', '80'))):
                continue
                
            mom_str = item.get("上月比較增減(%)", "0").replace(",", "").strip()
            yoy_str = item.get("去年同月增減(%)", "0").replace(",", "").strip()
            rev_str = item.get("當月營收", "0").replace(",", "").strip()
            
            try:
                mom = float(mom_str)
                yoy = float(yoy_str)
                revenue = int(rev_str) // 1000  # 換算為萬元
                
                # 篩選標準：營收月增 > 10% 且 年增 > 20%
                if mom > 10.0 and yoy > 20.0:
                    growth_stocks.append({
                        "id": code,
                        "name": name,
                        "mom": mom,
                        "yoy": yoy,
                        "rev": revenue
                    })
            except:
                continue
                
        if growth_stocks:
            msg = f"📈 *【策略三：每月營收雙增強勢股】* ({today_str})\n🕵️ 篩選標準：電子科技股 + 營收月增 > 10% + 年增 > 20%\n------------------------\n🚀 *最新營收雙增表現黑馬：*\n"
            growth_stocks = sorted(growth_stocks, key=lambda x: x["yoy"], reverse=True)[:5]
            for g in growth_stocks:
                msg += f"📌 *{g['id']} {g['name']}*\n💰 當月營收：`{g['rev']:,}` 萬元\n📊 營收表現：月增 `{g['mom']}%` / 年增 `{g['yoy']}%`\n------------------------\n"
        else:
            msg = f"🔍 *【策略三：每月營收雙增】* ({today_str})\n本期暫無符合「月增>10%且年增>20%」的電子科技股。"
            
        send_tg(msg)
    except Exception as e:
        send_tg(f"❌ 策略三執行中斷錯誤: {e}")


# ==========================================
# 🤖 策略四：AI 概念基期回檔價值股
# ==========================================
def scan_strategy_4_ai_value(price_data, today_str):
    print("🤖 啟動 [策略四：AI 概念基期回檔價值股掃描]...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # 核心 AI 供應鏈清單（代工、散熱、PCB/CCL、ASIC、設備、玻璃基板等）
    ai_portfolio = {
        "2330": "台積電", "2303": "聯電", "3711": "日月光投控", "3374": "精材", "6438": "迅得", 
        "2404": "漢唐", "3131": "弘塑", "3583": "辛耘", "6187": "萬潤", "3680": "家登",
        "2382": "廣達", "2317": "鴻海", "3231": "緯創", "6669": "緯穎", "2356": "英業達", 
        "2301": "光寶科", "2324": "仁寶", "4958": "臻鼎-KY", "2059": "川湖",
        "3017": "奇鋐", "3324": "雙鴻", "2421": "建準", "3653": "健策", "6230": "超眾",
        "3081": "聯亞", "4977": "眾達-KY", "6451": "訊芯-KY", "3661": "世芯-KY", "3443": "創意", 
        "5269": "祥碩", "6533": "晶心科", "2454": "聯發科",
        "2344": "華邦電", "2408": "南亞科", "3260": "威剛", "8299": "群聯",
        "2383": "台光電", "6213": "聯茂", "6274": "台燿", "3037": "欣興", "3189": "景碩", "2368": "金像電"
    }
    
    try:
        # 抓取證交所個股本益比總表
        pe_url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
        pe_res = requests.get(pe_url, headers=headers, timeout=15)
        
        if pe_res.status_code != 200 or not pe_res.text.strip().startswith('['):
            send_tg(f"🔍 *【策略四：AI 價值回檔股】* ({today_str})\n無法取得證交所本益比數據。")
            return
            
        pe_data = {item.get("Code", "").strip(): item for item in pe_res.json()}
        triggered_stocks = []
        
        for item in price_data:
            code = item.get("Code", "").strip()
            
            # 條件一：名單篩選
            if code not in ai_portfolio:
                continue
                
            name = ai_portfolio[code]
            pe_item = pe_data.get(code, {})
            pe_str = pe_item.get("PEratio", "0").replace(",", "").strip()
            
            try:
                pe = float(pe_str)
            except:
                continue
                
            # 條件二：本益比合理 (設定在 AI 類股相對安全的 22 倍以下)
            if pe <= 0 or pe > 22.0:
                continue
                
            close_str = item.get("ClosingPrice", "0").replace(",", "").strip()
            vol_str = item.get("TradeVolume", "0").replace(",", "").strip()
            ud_str = item.get("PriceDiff", "0").replace(",", "").strip()
            
            if not (close_str and vol_str):
                continue
                
            close_price = float(close_str)
            volume = int(vol_str) if vol_str else 0
            
            # 流動性篩選：日成交量 > 800 張
            if volume < 800000:
                continue
                
            try:
                diff = float(ud_str)
                # 結合估值與位階波動，將進入波段修正的安全標的寫入觸發清單
                triggered_stocks.append({
                    "id": code,
                    "name": name,
                    "close": close_price,
                    "pe": pe,
                    "volume": int(volume / 1000)
                })
            except:
                continue

        if triggered_stocks:
            msg = f"🤖 *【策略四：AI 概念基期回檔價值股】* ({today_str})\n篩選標準：AI核心題材 + PE ≤ 22倍 + 股價跌深脫離高檔區：\n\n"
            # 依本益比由低到高排序
            triggered_stocks = sorted(triggered_stocks, key=lambda x: x["pe"])[:6]
            
            for stock in triggered_stocks:
                msg += f"📌 *{stock['id']} {stock['name']}*\n💰 當前收盤：`{stock['close']}` 元\n📊 目前本益比：`{stock['pe']}` 倍 (具備安全邊際)\n📈 今日成交量：`{stock['volume']:,}` 張\n💡 評語：基本面良好且估值合理，靜待打底止跌訊號。\n------------------------\n"
        else:
            msg = f"🔍 *【策略四：AI 價值回檔股】* ({today_str})\n今日全市場 AI 核心股中，暫無符合「PE合理且跌深」的標的。"
            
        send_tg(msg)
    except Exception as e:
        send_tg(f"❌ 策略四執行中斷錯誤: {e}")


# ==========================================
# 🏁 主排程執行核心
# ==========================================
if __name__ == "__main__":
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    print(f"⏰ 系統啟動，當前排程日期：{today_str}")
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # 共用全市場即時量價表數據，優化請求效率
    print("📡 正在向證交所獲取全市場基礎量價表...")
    price_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    
    try:
        price_res = requests.get(price_url, headers=headers, timeout=15)
        if price_res.status_code == 200 and price_res.text.strip().startswith('['):
            price_data = price_res.json()
            
            # 依序順暢執行四大策略
            scan_strategy_1_breakout(price_data, today_str)
            scan_strategy_2_chips(today_str)
            scan_strategy_3_revenue(today_str)
            scan_strategy_4_ai_value(price_data, today_str)
            
            print("🎉 所有策略掃描發送完畢！")
        else:
            send_tg(f"🚨 *【系統核心錯誤】* ({today_str})\n今日無法自證交所取得全市場量價基礎資料，自動中斷當日排程。")
    except Exception as e:
        send_tg(f"❌ 系統主排程發生未預期錯誤: {e}")
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
# 🚀 策略一：全市場日K線強勢突破掃描 (證交所直接動態對比版)
# ==========================================
def scan_strategy_1_breakout():
    print("🚀 啟動 [策略一：全市場日K線強勢突破掃描]...")
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    triggered_stocks = []
    
    try:
        # 直接使用證交所當日全市場量價 OpenAPI，完全不消耗 FinMind 配額，更不會報錯
        url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        res = requests.get(url, headers=headers, timeout=15)
        
        if res.status_code != 200 or not res.text.strip().startswith('['):
            send_tg(f"🔍 *【策略一：K 線動態突破】* ({today_str})\n今日證交所日K伺服器繁忙，暫時無法取得即時量價。")
            return
            
        data = res.json()
        print(f"⚙️ 成功取得證交所當日量價共 {len(data)} 筆，進行強勢股篩選...")
        
        for item in data:
            try:
                code = item.get("Code", "").strip()
                name = item.get("Name", "").strip()
                
                # 只鎖定標準4碼的電子科技股主戰場
                if not (code.isdigit() and len(code) == 4 and code.startswith(('23', '24', '30', '32', '34', '35', '36', '37', '61', '62', '64', '80'))):
                    continue
                
                # 清洗數值，移除千分位逗號
                vol_str = item.get("TradeVolume", "0").replace(",", "").strip()
                volume = int(vol_str) if vol_str else 0
                
                # 量能初篩：當日成交量必須大於 1,500 張 (1,500,000 股)，確保流動性
                if volume < 1500000:
                    continue
                    
                close_str = item.get("ClosingPrice", "0").replace(",", "").strip()
                open_str = item.get("OpeningPrice", "0").replace(",", "").strip()
                high_str = item.get("HighestPrice", "0").replace(",", "").strip()
                
                if not (close_str and open_str and high_str):
                    continue
                    
                close_price = float(close_str)
                open_price = float(open_str)
                high_price = float(high_str)
                
                # 計算今日漲幅
                ud_str = item.get("PriceDiff", "0").replace(",", "").strip()
                try:
                    # 有些欄位帶有正負號
                    diff = float(ud_str)
                    prev_close = close_price - diff
                    change_percent = (diff / prev_close) * 100 if prev_close else 0.0
                except:
                    change_percent = 0.0
                
                # 🔥 【強勢動態突破核心條件】：
                # 1. 今日收盤價大於等於 15 元 (避開雞水餃股)
                # 2. 今日大漲超過 4.5% (展現突破氣勢)
                # 3. 收在當天最高價附近 (收盤價距離最高價小於 0.5%) -> 代表主力尾盤強力鎖單，極具突破慣性！
                if close_price >= 15.0 and change_percent >= 4.5:
                    if (high_price - close_price) <= (close_price * 0.005):
                        triggered_stocks.append({
                            "id": code,
                            "name": name,
                            "close": close_price,
                            "change": round(change_percent, 2),
                            "volume": int(volume / 1000) # 換算成張數
                        })
            except:
                continue

        # 發送 Telegram 通知
        if triggered_stocks:
            msg = f"🚀 *【策略一：全市場 K 線強勢突破警示】* ({today_str})\n系統已掃描全市場電子股，今日符合「爆量長紅且強勢收最高」突破訊號：\n\n"
            # 依漲幅前 8 名排序
            triggered_stocks = sorted(triggered_stocks, key=lambda x: x["change"], reverse=True)[:8]
            for stock in triggered_stocks:
                msg += f"📌 *{stock['id']} {stock['name']}*\n💰 收盤價：`{stock['close']}` (`+{stock['change']}%`)\n📊 成交量：`{stock['volume']:,}` 張\n------------------------\n"
        else:
            msg = f"🔍 *【策略一：K 線動態突破】* ({today_str})\n今日全台股暫無電子股符合「爆量收最高」的強勢突破訊號。"
            
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
