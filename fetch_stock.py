import sys
import json
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime

# ==========================================
# Telegram 推送設定 (請替換為你的 Token 與 Chat ID)
# ==========================================
TG_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TG_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

def send_telegram_message(message):
    if not TG_BOT_TOKEN or TG_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("⚠️ 未設定 Telegram Bot Token，僅印出訊息：\n")
        print(message)
        return
        
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print("✅ Telegram 訊息推播成功！")
        else:
            print(f"❌ Telegram 推播失敗，狀態碼：{res.status_code}, 內容：{res.text}")
    except Exception as e:
        print(f"❌ Telegram 發送異常: {e}")

# ==========================================
# ⚡ 1. 全港股極速粗篩（修復 API 阻擋與 JSONP 解析）
# ==========================================
def fetch_hk_shortlist_auto():
    print("🌐 正在抓取港股流動性數據並建立中文名稱字典...")
    shortlist = []
    name_dict = {}
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://vip.stock.finance.sina.com.cn/"
    }
    
    for page in range(1, 8):
        url = f"https://vip.stock.finance.sina.com.cn/hq/api/jsonp.php/IO.XSRV2.CallbackList['hk']/HK_Service.getMainMethodPageList?page={page}&num=80&sort=amount&asc=0"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            text = response.text
            
            left_idx = text.find("[")
            right_idx = text.rfind("]")
            
            if left_idx != -1 and right_idx != -1:
                json_str = text[left_idx:right_idx+1]
                data_list = json.loads(json_str)
                
                if not data_list:
                    break
                    
                for row in data_list:
                    raw_code = str(row.get('symbol', ''))
                    pure_code = raw_code[-4:] if len(raw_code) == 5 else raw_code
                    if not pure_code.isdigit():
                        continue
                        
                    ticker = f"{int(pure_code):04d}.HK"
                    name_dict[pure_code] = row.get('name', '未知')
                    
                    trade = float(row.get('trade', 0))
                    turnover = float(row.get('amount', 0))
                    
                    # 股價 >= 1.0 且 當日成交額 >= 800萬 HKD
                    if trade >= 1.0 and turnover >= 8000000:
                        shortlist.append(ticker)
        except Exception as e:
            print(f"⚠️ 第 {page} 頁抓取失敗: {e}")
            continue
            
    shortlist = list(set(shortlist))
    
    if shortlist:
        print(f"✅ 成功獲取動態全港股股票池：共 {len(shortlist)} 檔標的")
    else:
        print("❌ 警告：全港股 API 抓取失敗，退回 12 支核心備用池！")
        backup_tickers = []
        core_list = [
            (1, "長江和記"), (5, "匯豐控股"), (388, "香港交易所"), (700, "騰訊控股"), 
            (941, "中國移動"), (1211, "比亞迪股份"), (1810, "小米集團-W"), (2015, "理想汽車-W"), 
            (2318, "中國平安"), (3690, "美團-W"), (9618, "京東集團-SW"), (9988, "阿里巴巴-W")
        ]
        for code, name in core_list:
            pure_code = f"{code:04d}"
            ticker = f"{pure_code}.HK"
            backup_tickers.append(ticker)
            if pure_code not in name_dict:
                name_dict[pure_code] = name
        return backup_tickers, name_dict
        
    return shortlist, name_dict

# ==========================================
# 📊 2. 技術指標與策略邏輯
# ==========================================
def calculate_kd(df, n=9):
    low_list = df['Low'].rolling(window=n).min()
    high_list = df['High'].rolling(window=n).max()
    rsv = (df['Close'] - low_list) / (high_list - low_list) * 100
    rsv = rsv.fillna(50)
    
    k = [50.0]
    d = [50.0]
    for r in rsv[1:]:
        k_val = (2/3) * k[-1] + (1/3) * r
        d_val = (2/3) * d[-1] + (1/3) * k_val
        k.append(k_val)
        d.append(d_val)
        
    df['K'] = k
    df['D'] = d
    return df

def run_strategies(shortlist, name_dict):
    print("📈 開始下載日 K 線資料並計算策略...")
    try:
        data = yf.download(shortlist, period="1y", group_by='ticker', threads=True)
    except Exception as e:
        print(f"yfinance 下載失敗: {e}")
        return {}

    results = {
        "strategy_1": [], # 低檔爆量股
        "strategy_2": [], # 三頻共振
        "strategy_3": [], # 蓄勢待發
        "strategy_4": []  # 帶量突破
    }

    for ticker in shortlist:
        try:
            pure_code = ticker.split('.')[0]
            name = name_dict.get(pure_code, "未知")
            
            df = data[ticker].dropna().copy() if len(shortlist) > 1 else data.dropna().copy()
            if len(df) < 120:  # 計算 120 日高低位階
                continue

            # 均線計算
            df['MA5'] = df['Close'].rolling(5).mean()
            df['MA10'] = df['Close'].rolling(10).mean()
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            df['Vol_MA5'] = df['Volume'].rolling(5).mean()

            # MACD & KD
            df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
            df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
            df['DIF'] = df['EMA12'] - df['EMA26']
            df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
            df['MACD'] = (df['DIF'] - df['DEA']) * 2
            df = calculate_kd(df)

            curr = df.iloc[-1]
            prev = df.iloc[-2]

            pct_change = ((curr['Close'] - prev['Close']) / prev['Close']) * 100
            
            info = {
                "code": pure_code,
                "name": name,
                "price": curr['Close'],
                "pct_change": pct_change
            }

            # ----------------------------------------------------
            # 💥 策略一：低檔爆量股 (半年位階 ≤ 30% × 成交量 ≥ 2.5倍5日均量 × 紅K)
            # ----------------------------------------------------
            low_120 = df['Low'].tail(120).min()
            high_120 = df['High'].tail(120).max()
            
            if high_120 > low_120:
                position_120 = (curr['Close'] - low_120) / (high_120 - low_120)
            else:
                position_120 = 1.0

            is_red_k = curr['Close'] > curr['Open']
            vol_surge = curr['Volume'] >= (prev['Vol_MA5'] * 2.5) if prev['Vol_MA5'] > 0 else False

            if position_120 <= 0.30 and vol_surge and is_red_k:
                results["strategy_1"].append(info)

            # ----------------------------------------------------
            # 🎯 策略二：三頻共振 (MACD多週期 × KD低金)
            # ----------------------------------------------------
            kd_golden = (prev['K'] < prev['D']) and (curr['K'] > curr['D']) and (curr['K'] < 50)
            macd_bull = curr['DIF'] > curr['DEA'] and curr['MACD'] > 0
            if kd_golden and macd_bull:
                results["strategy_2"].append(info)

            # ----------------------------------------------------
            # 🌀 策略三：蓄勢待發 (多週期均線同步糾結)
            # ----------------------------------------------------
            ma_list = [curr['MA5'], curr['MA10'], curr['MA20'], curr['MA60']]
            ma_max = max(ma_list)
            ma_min = min(ma_list)
            if ma_min > 0 and ((ma_max - ma_min) / ma_min) <= 0.02:
                results["strategy_3"].append(info)

            # ----------------------------------------------------
            # ⚡ 策略四：帶量突破 (關鍵均線突破 × 量能倍增)
            # ----------------------------------------------------
            break_ma = (prev['Close'] < prev['MA20'] and curr['Close'] > curr['MA20'])
            vol_double = curr['Volume'] >= (prev['Vol_MA5'] * 2.0) if prev['Vol_MA5'] > 0 else False
            if break_ma and vol_double:
                results["strategy_4"].append(info)

        except Exception as e:
            continue

    return results

# ==========================================
# 📱 3. 格式化 Telegram 報告訊息
# ==========================================
def format_telegram_report(results, report_date, target_strategy="all"):
    msg = f"📋【港股多週期核心策略綜合報告】 ({report_date})\n"
    msg += "=============================\n\n"

    if target_strategy in ["all", "strategy_1"]:
        msg += "💥 一、低檔爆量股：半年位階 ≤ 30% × 2.5倍量 × 紅K\n"
        if results.get("strategy_1"):
            for item in results["strategy_1"]:
                msg += f"📦 {item['code']} {item['name']}\n"
                msg += f"💰 價格：{item['price']:.2f} HKD ({item['pct_change']:+.2f}%)\n\n"
        else:
            msg += "👉 今日暫無符合標的。\n\n"
        msg += "-----------------------------\n\n"

    if target_strategy in ["all", "strategy_2"]:
        msg += "🎯 二、三頻共振：MACD多週期 × KD低金\n"
        if results.get("strategy_2"):
            for item in results["strategy_2"]:
                msg += f"📦 {item['code']} {item['name']}\n"
                msg += f"💰 價格：{item['price']:.2f} HKD ({item['pct_change']:+.2f}%)\n\n"
        else:
            msg += "👉 今日暫無符合標的。\n\n"
        msg += "-----------------------------\n\n"

    if target_strategy in ["all", "strategy_3"]:
        msg += "🌀 三、蓄勢待發：多週期均線同步糾結\n"
        if results.get("strategy_3"):
            for item in results["strategy_3"]:
                msg += f"📦 {item['code']} {item['name']}\n"
                msg += f"💰 價格：{item['price']:.2f} HKD ({item['pct_change']:+.2f}%)\n\n"
        else:
            msg += "👉 今日暫無符合標的。\n\n"
        msg += "-----------------------------\n\n"

    if target_strategy in ["all", "strategy_4"]:
        msg += "⚡ 四、帶量突破：關鍵均線突破 × 量能倍增\n"
        if results.get("strategy_4"):
            for item in results["strategy_4"]:
                msg += f"📦 {item['code']} {item['name']}\n"
                msg += f"💰 價格：{item['price']:.2f} HKD ({item['pct_change']:+.2f}%)\n\n"
        else:
            msg += "👉 今日暫無符合標的。\n\n"

    msg += "============================="
    return msg

# ==========================================
# 🚀 4. 主流程
# ==========================================
if __name__ == "__main__":
    # 解析傳入參數 (例如 python fetch_stock.py strategy_1)
    target_strategy = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    shortlist, name_dict = fetch_hk_shortlist_auto()
    results = run_strategies(shortlist, name_dict)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    report = format_telegram_report(results, today_str, target_strategy)
    
    # 推送到 Telegram
    send_telegram_message(report)
