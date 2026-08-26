import os
import sys
import time
import json
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime

# ==========================================
# 📱 Telegram 推送模組 (自動切分長訊息)
# ==========================================
def send_telegram_message(message, max_length=3500):
    bot_token = os.environ.get("TG_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")

    if not bot_token or bot_token == "YOUR_TELEGRAM_BOT_TOKEN":
        print("⚠️ 未設定 Telegram Bot Token，僅印出訊息：\n")
        print(message)
        return

    bot_token = str(bot_token).strip()
    chat_id = str(chat_id).strip()
    if bot_token.lower().startswith("bot"):
        bot_token = bot_token[3:]

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    lines = message.split("\n")
    chunks = []
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_length:
            chunks.append(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk:
        chunks.append(current_chunk)

    for idx, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML"
        }
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                print(f"✅ Telegram 訊息推播成功 ({idx+1}/{len(chunks)})")
            else:
                print(f"❌ Telegram 推播失敗: {res.status_code}, {res.text}")
        except Exception as e:
            print(f"❌ Telegram 發送異常: {e}")
        time.sleep(0.5)

# ==========================================
# ⚡ 1. 全港股股票池抓取
# ==========================================
DYNAMIC_STOCK_NAMES = {}

def fetch_hk_shortlist_auto():
    print("🌐 正在抓取港股流動性數據並建立中文名稱字典...")
    shortlist = []
    
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
                    DYNAMIC_STOCK_NAMES[ticker] = row.get('name', '未知')
                    
                    trade = float(row.get('trade', 0))
                    turnover = float(row.get('amount', 0))
                    
                    # 股價 >= 1.0 且 當日成交額 >= 800萬 HKD
                    if trade >= 1.0 and turnover >= 8000000:
                        shortlist.append(ticker)
        except Exception as e:
            print(f"⚠️ 第 {page} 頁抓取失敗: {e}")
            continue
            
    shortlist = sorted(list(set(shortlist)))
    
    if shortlist:
        print(f"✅ 成功獲取動態全港股股票池：共 {len(shortlist)} 檔標的")
    else:
        print("❌ 警告：全港股 API 抓取失敗，退回 12 支核心備用池！")
        core_list = [
            (1, "長江和記"), (5, "匯豐控股"), (388, "香港交易所"), (700, "騰訊控股"), 
            (941, "中國移動"), (1211, "比亞迪股份"), (1810, "小米集團-W"), (2015, "理想汽車-W"), 
            (2318, "中國平安"), (3690, "美團-W"), (9618, "京東集團-SW"), (9988, "阿里巴巴-W")
        ]
        for code, name in core_list:
            ticker = f"{code:04d}.HK"
            shortlist.append(ticker)
            DYNAMIC_STOCK_NAMES[ticker] = name
            
    return shortlist

# ==========================================
# 📊 2. 營收月增檢測 (FinMind API)
# ==========================================
def check_revenue_mom_growth(ticker):
    """
    針對 1~7 策略篩選出的標的檢測營收月增 (MoM > 0%)
    """
    try:
        code = ticker.split('.')[0]
        url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id={code}"
        res = requests.get(url, timeout=5)
        
        if res.status_code == 200:
            data = res.json().get("data", [])
            if len(data) >= 2:
                df_rev = pd.DataFrame(data).sort_values("date")
                revs = df_rev['revenue'].tolist()[-2:]
                
                r0, r1 = revs[-1], revs[-2]
                mom = ((r0 - r1) / r1) * 100 if r1 > 0 else 0
                
                if mom > 0:
                    return True, round(mom, 1)
    except Exception:
        pass
    return False, 0.0

# ==========================================
# 📈 3. 技術面指標計算模組
# ==========================================
def calculate_macd(close_series, fast=12, slow=26, signal=9):
    fast_ema = close_series.ewm(span=fast, adjust=False).mean()
    slow_ema = close_series.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def calculate_kd(df_single, n=9, m1=3, m2=3):
    low_min = df_single['Low'].astype(float).rolling(window=n).min()
    high_max = df_single['High'].astype(float).rolling(window=n).max()
    close = df_single['Close'].astype(float)
    
    rsv = ((close - low_min) / (high_max - low_min)) * 100
    rsv = rsv.fillna(50)
    
    k_list, d_list = [50.0], [50.0]
    for i in range(1, len(rsv)):
        current_k = (k_list[-1] * (m1 - 1) + rsv.iloc[i]) / m1
        current_d = (d_list[-1] * (m2 - 1) + current_k) / m2
        k_list.append(current_k)
        d_list.append(current_d)
        
    return pd.Series(k_list, index=df_single.index), pd.Series(d_list, index=df_single.index)

def calculate_rsi(close_series, period=6):
    delta = close_series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

# ==========================================
# 🎯 4. 核心策略檢測邏輯 (1~7)
# ==========================================
def check_macd_up_and_kd_gold(df_single):
    try:
        if df_single.empty or len(df_single) < 26: return False
        c = df_single['Close'].squeeze().astype(float)
        
        macd_line, signal_line, hist = calculate_macd(c)
        if len(macd_line) < 2: return False
        
        macd_up = (macd_line.iloc[-1] > macd_line.iloc[-2]) and (
            macd_line.iloc[-1] >= 0 or (hist.iloc[-1] > hist.iloc[-2])
        )
        
        k_ser, d_ser = calculate_kd(df_single)
        if len(k_ser) < 2: return False
        
        kd_gold = (k_ser.iloc[-1] > d_ser.iloc[-1]) and (k_ser.iloc[-2] <= d_ser.iloc[-2])
        return macd_up and kd_gold
    except Exception:
        return False

def check_strat1_resonance(df_30m, df_60m):
    return check_macd_up_and_kd_gold(df_30m) and check_macd_up_and_kd_gold(df_60m)

def check_strat2_resonance(df_60m, df_daily):
    return check_macd_up_and_kd_gold(df_60m) and check_macd_up_and_kd_gold(df_daily)

def check_strat3_resonance(df_daily, df_weekly):
    return check_macd_up_and_kd_gold(df_daily) and check_macd_up_and_kd_gold(df_weekly)

def check_volume_breakout(df_daily):
    try:
        if df_daily.empty or len(df_daily) < 20: return False
        c_daily = df_daily['Close'].squeeze().astype(float)
        v_daily = df_daily['Volume'].squeeze().astype(float)
        
        ma20 = c_daily.rolling(window=20).mean()
        close_today, close_yesterday = c_daily.iloc[-1], c_daily.iloc[-2]
        ma20_today, ma20_yesterday = ma20.iloc[-1], ma20.iloc[-2]
        
        price_break = (close_today > ma20_today) and (close_yesterday <= ma20_yesterday or (close_today - close_yesterday) / close_yesterday > 0.02)
        if not price_break: return False
        
        v_ma5 = v_daily.rolling(window=5).mean().iloc[-1]
        volume_today = v_daily.iloc[-1]
        if volume_today <= (v_ma5 * 1.5): return False
        
        k_series, d_series = calculate_kd(df_daily)
        if (k_series.iloc[-1] > d_series.iloc[-1]) and (k_series.iloc[-1] < 75):
            return True, volume_today / v_ma5 if v_ma5 > 0 else 1.0
    except Exception:
        pass
    return False

def check_extreme_drop_volume_up(df_daily):
    try:
        if df_daily.empty or len(df_daily) < 20: return False
        c_daily = df_daily['Close'].squeeze().astype(float)
        o_daily = df_daily['Open'].squeeze().astype(float)
        v_daily = df_daily['Volume'].squeeze().astype(float)
        
        rsi6 = calculate_rsi(c_daily, period=6).iloc[-1]
        v_ma5 = v_daily.rolling(window=5).mean().iloc[-1]
        
        if rsi6 < 20 and c_daily.iloc[-1] > o_daily.iloc[-1] and v_daily.iloc[-1] > v_ma5:
            return True
    except Exception:
        pass
    return False

def check_multi_timeframe_tangling(df_60m, df_daily, df_weekly):
    try:
        c_60m, c_daily, c_weekly = df_60m['Close'].squeeze().astype(float), df_daily['Close'].squeeze().astype(float), df_weekly['Close'].squeeze().astype(float)
        if len(c_60m) < 20 or len(c_daily) < 20 or len(c_weekly) < 20: return False
        
        m60_t = (max(c_60m.rolling(5).mean().iloc[-1], c_60m.rolling(10).mean().iloc[-1], c_60m.rolling(20).mean().iloc[-1]) - min(c_60m.rolling(5).mean().iloc[-1], c_60m.rolling(10).mean().iloc[-1], c_60m.rolling(20).mean().iloc[-1])) / c_60m.rolling(20).mean().iloc[-1]
        d_t = (max(c_daily.rolling(5).mean().iloc[-1], c_daily.rolling(10).mean().iloc[-1], c_daily.rolling(20).mean().iloc[-1]) - min(c_daily.rolling(5).mean().iloc[-1], c_daily.rolling(10).mean().iloc[-1], c_daily.rolling(20).mean().iloc[-1])) / c_daily.rolling(20).mean().iloc[-1]
        w_t = (max(c_weekly.rolling(5).mean().iloc[-1], c_weekly.rolling(10).mean().iloc[-1], c_weekly.rolling(20).mean().iloc[-1]) - min(c_weekly.rolling(5).mean().iloc[-1], c_weekly.rolling(10).mean().iloc[-1], c_weekly.rolling(20).mean().iloc[-1])) / c_weekly.rolling(20).mean().iloc[-1]
        
        if m60_t < 0.025 and d_t < 0.03 and w_t < 0.035 and c_daily.iloc[-1] > c_daily.rolling(20).mean().iloc[-1]:
            return True
    except Exception:
        pass
    return False

def check_low_position_volume_surge(df_daily):
    try:
        if df_daily.empty or len(df_daily) < 120: return False
        c_daily, o_daily = df_daily['Close'].squeeze().astype(float), df_daily['Open'].squeeze().astype(float)
        h_daily, l_daily = df_daily['High'].squeeze().astype(float), df_daily['Low'].squeeze().astype(float)
        v_daily = df_daily['Volume'].squeeze().astype(float)
        
        if c_daily.iloc[-1] <= o_daily.iloc[-1]: return False
        
        v_ma5 = v_daily.rolling(window=5).mean().iloc[-1]
        if v_ma5 == 0 or v_daily.iloc[-1] < (v_ma5 * 2.5): return False
        
        high_120, low_120 = h_daily.iloc[-120:].max(), l_daily.iloc[-120:].min()
        if high_120 == low_120: return False
        
        pos = (c_daily.iloc[-1] - low_120) / (high_120 - low_120)
        if pos <= 0.30:
            return True, round(pos * 100, 1), round(v_daily.iloc[-1] / v_ma5, 1)
    except Exception:
        pass
    return False

# ==========================================
# 🚀 5. 主程式流程
# ==========================================
if __name__ == "__main__":
    now_hk = pd.Timestamp.now(tz='UTC').tz_convert('Asia/Hong_Kong')
    hk_time_str = now_hk.strftime('%Y-%m-%d %H:%M:%S')

    print("🚀 啟動【港股 8 大策略全方位篩選報告】...")
    tech_scan_pool = fetch_hk_shortlist_auto()
    if not tech_scan_pool:
        sys.exit()

    print("⏳ 步驟 1: 下載全市場日 K 數據 (過濾流動性門檻)...")
    full_df_daily = yf.download(tech_scan_pool, period="1y", interval="1d", progress=False, auto_adjust=True)
    
    qualified_tickers = []
    for ticker in tech_scan_pool:
        try:
            df_ticker = full_df_daily.xs(ticker, axis=1, level=1) if len(tech_scan_pool) > 1 else full_df_daily
            v_daily = df_ticker['Volume'].squeeze()
            if len(v_daily) >= 20:
                qualified_tickers.append(ticker)
        except Exception:
            continue

    print(f"🎯 通過門檻股票共 {len(qualified_tickers)} 檔。")
    
    strat1_matches, strat2_matches, strat3_matches, strat4_matches, strat5_matches, strat6_matches, strat7_matches, strat8_matches = [], [], [], [], [], [], [], []
    tech_candidates_union = set()

    if qualified_tickers:
        print("⏳ 步驟 2: 批次下載多週期 K 線資料 (30m, 60m, Weekly)...")
        full_df_30m = yf.download(qualified_tickers, period="1mo", interval="30m", progress=False, auto_adjust=True)
        full_df_60m = yf.download(qualified_tickers, period="1mo", interval="60m", progress=False, auto_adjust=True)
        full_df_weekly = yf.download(qualified_tickers, period="2y", interval="1wk", progress=False, auto_adjust=True)

        print("⏳ 步驟 3: 執行策略 1~7 技術面檢測...")
        for ticker in qualified_tickers:
            try:
                df_d = full_df_daily.xs(ticker, axis=1, level=1) if len(qualified_tickers) > 1 else full_df_daily
                df_m30 = full_df_30m.xs(ticker, axis=1, level=1) if len(qualified_tickers) > 1 else full_df_30m
                df_m60 = full_df_60m.xs(ticker, axis=1, level=1) if len(qualified_tickers) > 1 else full_df_60m
                df_w = full_df_weekly.xs(ticker, axis=1, level=1) if len(qualified_tickers) > 1 else full_df_weekly

                if df_d.empty or df_m30.empty or df_m60.empty or df_w.empty:
                    continue

                name_zh = DYNAMIC_STOCK_NAMES.get(ticker, "")
                stock_label = f"<code>{ticker}</code>(<i>{name_zh}</i>)" if name_zh else f"<code>{ticker}</code>"

                # 策略一
                if check_strat1_resonance(df_m30, df_m60):
                    strat1_matches.append(stock_label)
                    tech_candidates_union.add(ticker)
                    
                # 策略二
                if check_strat2_resonance(df_m60, df_d):
                    strat2_matches.append(stock_label)
                    tech_candidates_union.add(ticker)

                # 策略三
                if check_strat3_resonance(df_d, df_w):
                    strat3_matches.append(stock_label)
                    tech_candidates_union.add(ticker)

                # 策略四
                v_break = check_volume_breakout(df_d)
                if v_break:
                    strat4_matches.append(f"{stock_label}[量比:{v_break[1]:.1f}倍]")
                    tech_candidates_union.add(ticker)

                # 策略五
                if check_extreme_drop_volume_up(df_d):
                    strat5_matches.append(stock_label)
                    tech_candidates_union.add(ticker)

                # 策略六
                if check_multi_timeframe_tangling(df_m60, df_d, df_w):
                    strat6_matches.append(stock_label)
                    tech_candidates_union.add(ticker)

                # 策略七
                low_vol = check_low_position_volume_surge(df_d)
                if low_vol:
                    strat7_matches.append(f"{stock_label}[位階:{low_vol[1]}%|量比:{low_vol[2]}倍]")
                    tech_candidates_union.add(ticker)

            except Exception:
                continue

    # --------------------------------------------------------------------------
    # 🔍 步驟 4: 執行【策略八】(針對 1~7 策略出的標的過濾營收月增 MoM > 0%)
    # --------------------------------------------------------------------------
    print(f"⏳ 步驟 4: 執行【策略八】(針對 1~7 策略共 {len(tech_candidates_union)} 檔技術標的檢測)...")
    for ticker in sorted(tech_candidates_union):
        is_mom_pass, mom_val = check_revenue_mom_growth(ticker)
        time.sleep(0.1)

        if is_mom_pass:
            name_zh = DYNAMIC_STOCK_NAMES.get(ticker, "")
            label = f"<code>{ticker}</code>(<i>{name_zh}</i>)[月增:{mom_val}%]" if name_zh else f"<code>{ticker}</code>[月增:{mom_val}%]"
            strat8_matches.append(label)

    # 📝 建立 8 大策略完整 Telegram 報告
    hk_msg = f"🇭🇰 <b>【港股盤後 8 大策略選股報告】</b>\n"
    hk_msg += f"⏰ 時間: {hk_time_str}\n───────────────────\n\n"
    
    hk_msg += "📈 <b>【策略一】30分K & 60分K 共振</b>\n↳ " + (", ".join(strat1_matches) if strat1_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "📈 <b>【策略二】60分K & 日K 共振</b>\n↳ " + (", ".join(strat2_matches) if strat2_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "📈 <b>【策略三】日K & 週K 共振</b>\n↳ " + (", ".join(strat3_matches) if strat3_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "⚡ <b>【策略四】帶量突破</b>\n↳ " + (", ".join(strat4_matches) if strat4_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "🔥 <b>【策略五】恐慌止跌 (極限超賣爆量)</b>\n↳ " + (", ".join(strat5_matches) if strat5_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "💎 <b>【策略六】全週期同步糾結</b>\n↳ " + (", ".join(strat6_matches) if strat6_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "💥 <b>【策略七】低檔爆量股</b>\n↳ " + (", ".join(strat7_matches) if strat7_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "🏆 <b>【策略八】技術精選 × 營收月增 (策略1~7標的中 月增&gt;0%)</b>\n↳ " + (", ".join(strat8_matches) if strat8_matches else "無符合營收月增之標的。 💤") + "\n"

    send_telegram_message(hk_msg)
    print("✅ 8 大策略選股報告發送完畢！")
