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
# ⚡ 全港股極速粗篩（建立中文名稱對照表）
# ==========================================
def fetch_hk_shortlist_auto():
    print("🌐 正在抓取港股流動性數據並建立中文名稱字典...")
    shortlist = []
    name_dict = {}
    
    for page in range(1, 7):
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
                
                name_dict[pure_code] = row['name']
                trade = float(row['trade'])      
                turnover = float(row['amount'])  
                
                if trade >= 1.0 and turnover >= 8000000:
                    shortlist.append(ticker)
        except:
            continue
            
    shortlist = list(set(shortlist))
    
    if not shortlist:
        print("⚠️ 偵測到當前可能為休市期間（成交額為0），啟動核心活躍股回溯機制...")
        backup_tickers = []
        core_list = [
            (1, "長江和記"), (2, "中電控股"), (3, "中華煤氣"), (4, "九龍倉集團"), (5, "匯豐控股"), 
            (6, "電能實業"), (11, "恆生銀行"), (12, "恆基地產"), (16, "新鴻基地產"), (17, "新世界發展"), 
            (27, "銀河娛樂"), (66, "港鐵公司"), (175, "吉利汽車"), (241, "阿里健康"), (267, "中信股份"), 
            (288, "萬洲國際"), (386, "中國石油化工"), (388, "香港交易所"), (700, "騰訊控股"), (762, "中國聯通"), 
            (857, "中國石油股份"), (883, "中國海洋石油"), (941, "中國移動"), (960, "龍湖集團"), (981, "中芯國際"), 
            (992, "聯想集團"), (1024, "快手-W"), (1088, "中國神華"), (1093, "石藥集團"), (1109, "華潤置地"), 
            (1113, "長實集團"), (1177, "中國生物製藥"), (1211, "比亞迪股份"), (1299, "友邦保險"), (1398, "工商銀行"), 
            (1810, "小米集團-W"), (1928, "金沙中國有限公司"), (2015, "理想汽車-W"), (2020, "安踏體育"), 
            (2269, "藥明生物"), (2313, "申洲國際"), (2318, "中國平安"), (2319, "蒙牛乳業"), (2331, "李寧"), 
            (2333, "長城汽車"), (2382, "舜宇光學科技"), (2388, "中銀香港"), (2628, "中國人壽"), (3690, "美團-W"), 
            (3968, "招商銀行"), (3988, "中國銀行"), (6030, "中信證券"), (9618, "京東集團-SW"), (9868, "小鵬汽車-W"), 
            (9888, "百度集團-SW"), (9961, "攜程集團-S"), (9988, "阿里巴巴-W"), (9999, "網易-S")
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
# 🚀 第二階段：精準分析與發送
# ==========================================
def scan_all_hong_kong_market_fast():
    start_time = time.time()
    
    shortlist, name_dict = fetch_hk_shortlist_auto()
    
    print(f"\n🚀 【深度分析階段】正在分析 {len(shortlist)} 檔核心港股最近 2 個交易日的 K 線...")
    valid_active_stocks = []
    
    shortlist_str = " ".join(shortlist)
    try:
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
                
                if today_close >= 1.0 and turnover >= 8000000:
                    pure_code = ticker.split('.')[0]
                    stock_name = name_dict.get(pure_code, "未知名稱")
                    
                    valid_active_stocks.append({
                        "id": pure_code,
                        "name": stock_name,
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
    # 📊 策略篩選與整合單一訊息
    # ------------------------------------------
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    master_df = pd.DataFrame(valid_active_stocks)

    # 🔔 初始化整合型訊息內容
    full_report_msg = f"📋 *【港股量價策略盤後報告】* ({today_str})\n"
    full_report_msg += "========================\n\n"

    # 1. 處理策略一：爆量突破收最高
    breakout_cond = (master_df["change"] >= 5.0) & ((master_df["high"] - master_df["close"]) <= (master_df["close"] * 0.005))
    breakout_df = master_df[breakout_cond].sort_values(by="change", ascending=False).head(5)

    full_report_msg += "🚀 *一、突破警示：強勢收最高 Top 5*\n"
    if not breakout_df.empty:
        for _, row in breakout_df.iterrows():
            full_report_msg += f"📌 *{row['id']} {row['name']}*\n💰 價格：`{row['close']:.2f} HKD` (`+{row['change']:.2f}%`)\n📊 成交額：`{row['turnover']/1000000:.1f}M HKD`\n"
    else:
        full_report_msg += "👉 _今日暫無符合「強勢突破收最高」標的。_\n"
        
    full_report_msg += "\n========================\n\n"

    # 2. 處理策略二：成交額 Top 5
    volume_surge_df = master_df[master_df["change"] > 0.0].sort_values(by="turnover", ascending=False).head(5)
    
    full_report_msg += "📊 *二、資金聚焦：成交額 Top 5*\n"
    if not volume_surge_df.empty:
        for _, row in volume_surge_df.iterrows():
            full_report_msg += f"🔥 *{row['id']} {row['name']}*\n💰 收盤價：`{row['close']:.2f} HKD` (`+{row['change']:.2f}%`)\n💸 今日成交額：`{row['turnover']/1000000:.1f}M HKD`\n"
    else:
        full_report_msg += "👉 _今日暫無符合條件之標的。_\n"

    # 3. 一鍵發送整份報告
    send_tg(full_report_msg)
    print(f"🎉 整合版報告發送順利結束！總花費時間: {time.time() - start_time:.1f} 秒")

if __name__ == "__main__":
    scan_all_hong_kong_market_fast()
