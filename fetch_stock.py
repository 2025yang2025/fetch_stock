import os
import sys
import time
import json
import requests
import pandas as pd
import yfinance as yf

# ==========================================
# ⚙️ 設定檔 (同時支援兩種環境變數名稱，避免抓不到)
# ==========================================
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN") or "YOUR_TELEGRAM_BOT_TOKEN"
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "YOUR_TELEGRAM_CHAT_ID"

# ==========================================
# 📱 Telegram 推送模組
# ==========================================
def send_telegram_message(message, max_length=3500):
    if not TG_BOT_TOKEN or TG_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("⚠️ 未設定 Telegram Bot Token，僅在 Console 印出訊息：\n")
        print(message)
        return

    bot_token = str(TG_BOT_TOKEN).strip()
    chat_id = str(TG_CHAT_ID).strip()
    if bot_token.lower().startswith("bot"):
        bot_token = bot_token[3:]

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    lines = message.split("\n")
    chunks, current_chunk = [], ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_length:
            chunks.append(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk:
        chunks.append(current_chunk)

    for idx, chunk in enumerate(chunks):
        payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://vip.stock.finance.sina.com.cn/"
    }
    for page in range(1, 8):
        url = f"https://vip.stock.finance.sina.com.cn/hq/api/jsonp.php/IO.XSRV2.CallbackList['hk']/HK_Service.getMainMethodPageList?page={page}&num=80&sort=amount&asc=0"
        try:
            response = requests.get(url, headers=headers, timeout=5)
            text = response.text
            left_idx, right_idx = text.find("["), text.rfind("]")
            if left_idx != -1 and right_idx != -1:
                data_list = json.loads(text[left_idx:right_idx+1])
                if not data_list: break
                for row in data_list:
                    raw_code = str(row.get('symbol', ''))
                    pure_code = raw_code[-4:] if len(raw_code) == 5 else raw_code
                    if not pure_code.isdigit(): continue
                    ticker = f"{int(pure_code):04d}.HK"
                    DYNAMIC_STOCK_NAMES[ticker] = row.get('name', '未知')
                    trade, turnover = float(row.get('trade', 0)), float(row.get('amount', 0))
                    if trade >= 1.0 and turnover >= 8000000:
                        shortlist.append(ticker)
        except Exception:
            continue
            
    shortlist = sorted(list(set(shortlist)))
    return shortlist if shortlist else [f"{c:04d}.HK" for c in [1, 5, 388, 700, 941, 1211, 1810, 2015, 2318, 3690, 9618, 9988]]

# ==========================================
# 📊 2. 營收月增檢測
# ==========================================
def check_revenue_mom_growth(ticker):
    try:
        code = ticker.split('.')[0]
        url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id={code}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json().get("data", [])
            if len(data) >= 2:
                df_rev = pd.DataFrame(data).sort_values("date")
                revs = df_rev['revenue'].tolist()[-2:]
                r0, r1 = revs[-1], revs[-2]
                mom = ((r0 - r1) / r1) * 100 if r1 > 0 else 0
                if mom > 0: return True, round(mom, 1)
    except Exception:
        pass
    return False, 0.0

# ==========================================
# 📈 3. 技術面指標計算模組
# ==========================================
def calculate_macd(close_series):
    fast_ema = close_series.ewm(span=12, adjust=False).mean()
    slow_ema = close_series.ewm(span=26, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def calculate_kd(df_single):
    low_min = df_single['Low'].astype(float).rolling(window=9).min()
    high_max = df_single['High'].astype(float).rolling(window=9).max()
    close = df_single['Close'].astype(float)
    rsv = ((close - low_min) / (high_max - low_min) * 100).fillna(50)
    k_list, d_list = [50.0], [50.0]
    for i in range(1, len(rsv)):
        current_k = (k_list[-1] * 2 + rsv.iloc[i]) / 3
        current_d = (d_list[-1] * 2 + current_k) / 3
        k_list.append(current_k)
        d_list.append(current_d)
    return pd.Series(k_list, index=df_single.index), pd.Series(d_list, index=df_single.index)

def calculate_rsi(close_series, period=6):
    delta = close_series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return (100 - (100 / (1 + rs))).fillna(50)

# ==========================================
# 🎯 4. 核心策略檢測邏輯
# ==========================================
def check_macd_up_and_kd_gold(df_single):
    try:
        if df_single.empty or len(df_single) < 26: return False
        c = df_single['Close'].squeeze().astype(float)
        macd_line, _, hist = calculate_macd(c)
        if len(macd_line) < 2: return False
        macd_up = (macd_line.iloc[-1] > macd_line.iloc[-2]) and (macd_line.iloc[-1] >= 0 or (hist.iloc[-1] > hist.iloc[-2]))
        k_ser, d_ser = calculate_kd(df_single)
        if len(k_ser) < 2: return False
        kd_gold = (k_ser.iloc[-1] > d_ser.iloc[-1]) and (k_ser.iloc[-2] <= d_ser.iloc[-2])
        return macd_up and kd_gold
    except Exception:
        return False

def check_volume_breakout(df_daily):
    try:
        if df_daily.empty or len(df_daily) < 20: return False
        c_daily, v_daily = df_daily['Close'].squeeze().astype(float), df_daily['Volume'].squeeze().astype(float)
        ma20 = c_daily.rolling(window=20).mean()
        close_today, close_yesterday = c_daily.iloc[-1], c_daily.iloc[-2]
        if not ((close_today > ma20.iloc[-1]) and (close_yesterday <= ma20.iloc[-2] or (close_today - close_yesterday) / close_yesterday > 0.02)):
            return False
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
        c_daily, o_daily, v_daily = df_daily['Close'].squeeze().astype(float), df_daily['Open'].squeeze().astype(float), df_daily['Volume'].squeeze().astype(float)
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
# 🛠️ 高速分批下載函數
# ==========================================
def safe_batch_download(tickers, period, interval, chunk_size=80):
    all_dfs = []
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            df = yf.download(chunk, period=period, interval=interval, progress=False, auto_adjust=True, threads=True)
            if not df.empty:
                all_dfs.append(df)
        except Exception:
            pass
    return pd.concat(all_dfs, axis=1) if all_dfs else pd.DataFrame()

# ==========================================
# 🚀 5. 主程式流程 (全策略執行)
# ==========================================
if __name__ == "__main__":
    now_hk = pd.Timestamp.now(tz='UTC').tz_convert('Asia/Hong_Kong')
    hk_time_str = now_hk.strftime('%Y-%m-%d %H:%M:%S')

    print("🚀 啟動【港股盤後全策略篩選報告】...")
    
    strat1_matches, strat2_matches, strat3_matches, strat4_matches = [], [], [], []
    strat5_matches, strat6_matches, strat7_matches, strat8_matches = [], [], [], []
    tech_candidates_union = set()

    tech_scan_pool = fetch_hk_shortlist_auto()
    if not tech_scan_pool:
        sys.exit()

    print("⏳ 步驟 1: 下載全市場日 K 數據...")
    full_df_daily = safe_batch_download(tech_scan_pool, period="1y", interval="1d")
    
    qualified_tickers = []
    if not full_df_daily.empty:
        for ticker in tech_scan_pool:
            try:
                df_ticker = full_df_daily.xs(ticker, axis=1, level=1) if len(tech_scan_pool) > 1 else full_df_daily
                if len(df_ticker['Volume'].squeeze()) >= 20:
                    qualified_tickers.append(ticker)
            except Exception:
                continue

    print(f"🎯 通過門檻股票共 {len(qualified_tickers)} 檔。")

    if qualified_tickers:
        print("⏳ 步驟 2: 下載 30m, 60m, Weekly 多週期 K 線...")
        full_df_30m = safe_batch_download(qualified_tickers, period="1mo", interval="30m")
        full_df_60m = safe_batch_download(qualified_tickers, period="1mo", interval="60m")
        full_df_weekly = safe_batch_download(qualified_tickers, period="1y", interval="1wk")

        print("⏳ 步驟 3: 執行全策略運算 (策略 1~7)...")
        for ticker in qualified_tickers:
            try:
                df_d = full_df_daily.xs(ticker, axis=1, level=1) if len(qualified_tickers) > 1 else full_df_daily
                df_m30 = full_df_30m.xs(ticker, axis=1, level=1) if not full_df_30m.empty else pd.DataFrame()
                df_m60 = full_df_60m.xs(ticker, axis=1, level=1) if not full_df_60m.empty else pd.DataFrame()
                df_w = full_df_weekly.xs(ticker, axis=1, level=1) if not full_df_weekly.empty else pd.DataFrame()

                name_zh = DYNAMIC_STOCK_NAMES.get(ticker, "")
                stock_label = f"<code>{ticker}</code>(<i>{name_zh}</i>)" if name_zh else f"<code>{ticker}</code>"

                # 策略一
                if not df_m30.empty and not df_m60.empty:
                    if check_macd_up_and_kd_gold(df_m30) and check_macd_up_and_kd_gold(df_m60):
                        strat1_matches.append(stock_label)
                        tech_candidates_union.add(ticker)

                # 策略二
                if not df_m60.empty and not df_d.empty:
                    if check_macd_up_and_kd_gold(df_m60) and check_macd_up_and_kd_gold(df_d):
                        strat2_matches.append(stock_label)
                        tech_candidates_union.add(ticker)

                # 策略三
                if not df_d.empty and not df_w.empty:
                    if check_macd_up_and_kd_gold(df_d) and check_macd_up_and_kd_gold(df_w):
                        strat3_matches.append(stock_label)
                        tech_candidates_union.add(ticker)

                # 策略四
                if not df_d.empty:
                    v_break = check_volume_breakout(df_d)
                    if v_break:
                        strat4_matches.append(f"{stock_label}[量比:{v_break[1]:.1f}倍]")
                        tech_candidates_union.add(ticker)

                # 策略五
                if not df_d.empty:
                    if check_extreme_drop_volume_up(df_d):
                        strat5_matches.append(stock_label)
                        tech_candidates_union.add(ticker)

                # 策略六
                if not df_m60.empty and not df_d.empty and not df_w.empty:
                    if check_multi_timeframe_tangling(df_m60, df_d, df_w):
                        strat6_matches.append(stock_label)
                        tech_candidates_union.add(ticker)

                # 策略七
                if not df_d.empty:
                    low_vol = check_low_position_volume_surge(df_d)
                    if low_vol:
                        strat7_matches.append(f"{stock_label}[位階:{low_vol[1]}%|量比:{low_vol[2]}倍]")
                        tech_candidates_union.add(ticker)

            except Exception:
                continue

    # 策略八
    if tech_candidates_union:
        print(f"⏳ 步驟 4: 執行【策略八】(針對 {len(tech_candidates_union)} 檔技術標的檢測)...")
        for ticker in sorted(tech_candidates_union):
            is_mom_pass, mom_val = check_revenue_mom_growth(ticker)
            if is_mom_pass:
                name_zh = DYNAMIC_STOCK_NAMES.get(ticker, "")
                label = f"<code>{ticker}</code>(<i>{name_zh}</i>)[月增:{mom_val}%]" if name_zh else f"<code>{ticker}</code>[月增:{mom_val}%]"
                strat8_matches.append(label)

    # 📝 建構 Telegram 報告訊息
    hk_msg = f"🇭🇰 <b>【港股盤後全策略選股報告】</b>\n"
    hk_msg += f"⏰ 時間: {hk_time_str}\n───────────────────\n\n"
    hk_msg += "📈 <b>【策略一】30分K & 60分K 共振</b>\n↳ " + (", ".join(strat1_matches) if strat1_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "📈 <b>【策略二】60分K & 日K 共振</b>\n↳ " + (", ".join(strat2_matches) if strat2_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "📈 <b>【策略三】日K & 週K 共振</b>\n↳ " + (", ".join(strat3_matches) if strat3_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "⚡ <b>【策略四】帶量突破</b>\n↳ " + (", ".join(strat4_matches) if strat4_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "🔥 <b>【策略五】恐慌止跌 (極限超賣爆量)</b>\n↳ " + (", ".join(strat5_matches) if strat5_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "💎 <b>【策略六】全週期同步糾結</b>\n↳ " + (", ".join(strat6_matches) if strat6_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "💥 <b>【策略七】低檔爆量股</b>\n↳ " + (", ".join(strat7_matches) if strat7_matches else "今日無符合標的。 💤") + "\n\n"
    hk_msg += "🏆 <b>【策略八】技術精選 × 營收月增</b>\n↳ " + (", ".join(strat8_matches) if strat8_matches else "無符合營收月增之標的。 💤") + "\n"

    send_telegram_message(hk_msg)
    print("✅ 全策略選股報告發送完畢！")
