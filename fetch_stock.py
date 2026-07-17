import os
import sys
import datetime
import time
import requests
import pandas as pd
import yfinance as yf

# ==========================================
# ⚙️ 系統基本設定 (安全動態讀取環境變數)
# ==========================================
# 請在環境變數中設定 TELEGRAM_TOKEN 與 TELEGRAM_CHAT_ID
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 🎯 港股核心科技、網聯、半導體與 AI 概念股名單 (對標原先的 AI 價值清單)
HK_TECH_PORTFOLIO = {
    "0700.HK": "騰訊控股",
    "3690.HK": "美團-W",
    "9988.HK": "阿里巴巴-W",
    "1810.HK": "小米集團-W",
    "9618.HK": "京東集團-SW",
    "9999.HK": "網易-S",
    "0981.HK": "中芯國際",
    "1347.HK": "華虹半導體",
    "0992.HK": "聯想集團",
    "2411.HK": "百川智能", # 示意港股AI
    "2015.HK": "理想汽車-W",
    "9868.HK": "小鵬汽車-W",
    "9866.HK": "蔚來-SW",
    "2859.HK": "易方達恆生科技ETF" # 亦可監控科技ETF作為基期參考
}

# 🌐 港股主要監控全市場清單 (熱門大型港股，若要掃描全市場可用此當基礎)
GLOBAL_HK_TICKERS = list(HK_TECH_PORTFOLIO.keys()) + [
    "0005.HK", "1299.HK", "0939.HK", "1398.HK", "3988.HK", "2318.HK", "2628.HK", "0388.HK"
]

def send_tg(text):
    """發送 Telegram 訊息的通用函式"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ 錯誤：未設定 TELEGRAM_TOKEN 或 TELEGRAM_CHAT_ID 環境變數。")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Telegram 發送失敗: {e}")
        return False

# ==========================================
# 🚀 策略一：港股日K線強勢突破掃描 (爆量收最高)
# ==========================================
def scan_strategy_1_breakout():
    print("🚀 啟動 [策略一：港股日K線強勢突破掃描]...")
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    triggered_stocks = []
    
    # 使用 yfinance 批次獲取港股核心科技股當日即時與昨日歷史數據
    tickers_str = " ".join(GLOBAL_HK_TICKERS)
    try:
        # 獲取最近兩天的日K資料，以便計算漲跌幅
        df = yf.download(tickers_str, period="2d", group_by="ticker", progress=False)
        if df.empty:
            print("⚠️ 無法從 Yahoo Finance 獲取即時資料。")
            return
            
        for ticker in GLOBAL_HK_TICKERS:
            try:
                if ticker not in df.columns.levels[0]:
                    continue
                sub_df = df[ticker].dropna()
                if len(sub_df) < 2:
                    continue
                
                # 昨日與今日價格
                prev_close = sub_df["Close"].iloc[-2]
                today_open = sub_df["Open"].iloc[-1]
                today_high = sub_df["High"].iloc[-1]
                today_close = sub_df["Close"].iloc[-1]
                today_volume = sub_df["Volume"].iloc[-1]
                
                # 計算漲跌幅 (%)
                change_percent = ((today_close - prev_close) / prev_close) * 100
                
                # 港股篩選標準調整：
                # 1. 股價 >= 5 HKD (避開仙股/細股)
                # 2. 單日漲幅 >= 4.0%
                # 3. 日成交量 > 1,000,000 股 (港股流動性集中在頭部股)
                # 4. 強勢收最高 (收盤距離最高價 < 0.5%)
                if today_close >= 5.0 and change_percent >= 4.0 and today_volume >= 1000000:
                    if (today_high - today_close) <= (today_close * 0.005):
                        pure_code = ticker.split('.')[0]
                        name = HK_TECH_PORTFOLIO.get(ticker, f"港股 {pure_code}")
                        triggered_stocks.append({
                            "id": pure_code,
                            "name": name,
                            "close": round(today_close, 2),
                            "change": round(change_percent, 2),
                            "volume": int(today_volume)
                        })
            except Exception as e:
                print(f"解析 {ticker} 失敗: {e}")
                continue
                
        if triggered_stocks:
            msg = f"🚀 *【策略一：港股 K 線強勢突破警示】* ({today_str})\n系統已掃描港股科技板塊，今日符合「爆量長紅且強勢收最高」突破訊號：\n\n"
            triggered_stocks = sorted(triggered_stocks, key=lambda x: x["change"], reverse=True)[:8]
            for stock in triggered_stocks:
                msg += f"📌 *{stock['id']} {stock['name']}*\n💰 收盤價：`{stock['close']} HKD` (`+{stock['change']}%`)\n📊 成交量：`{stock['volume']:,}` 股\n------------------------\n"
        else:
            msg = f"🔍 *【策略一：港股 K 線動態突破】* ({today_str})\n今日監控港股中暫無符合「爆量收最高」的強勢突破訊號。"
            
        send_tg(msg)
    except Exception as e:
        send_tg(f"❌ 港股策略一執行中斷錯誤: {e}")

# ==========================================
# 📊 策略二：港股南向資金 (大市籌碼流向)
# ==========================================
def scan_strategy_2_chips():
    """港股沒有台灣的法人買賣超，但港股最關鍵的籌碼指標是「北水 (南向資金)」流入。"""
    print("📊 啟動 [策略二：港股南向資金與大單監控]...")
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # 港股無公開的即時個股南向資金免費 OpenAPI，此處利用 yfinance 分析頭部外資與機構持股比例變動，
    # 或者是透過抓取主流港股的成交額佔比（Turnover Ratio）來判定主力吸籌。
    triggered_stocks = []
    tickers_str = " ".join(GLOBAL_HK_TICKERS)
    
    try:
        df = yf.download(tickers_str, period="5d", group_by="ticker", progress=False)
        for ticker in GLOBAL_HK_TICKERS:
            try:
                sub_df = df[ticker].dropna()
                if len(sub_df) < 5:
                    continue
                
                # 計算 5 日平均成交量
                avg_vol_5d = sub_df["Volume"].mean()
                today_vol = sub_df["Volume"].iloc[-1]
                today_close = sub_df["Close"].iloc[-1]
                
                # 量比大於 1.5 倍 且 今日收紅，視為主力異常吸籌（跟單訊號）
                volume_ratio = today_vol / avg_vol_5d if avg_vol_5d else 0
                if volume_ratio >= 1.5 and today_close > sub_df["Close"].iloc[-2]:
                    pure_code = ticker.split('.')[0]
                    name = HK_TECH_PORTFOLIO.get(ticker, f"港股 {pure_code}")
                    triggered_stocks.append({
                        "id": pure_code,
                        "name": name,
                        "close": round(today_close, 2),
                        "ratio": round(volume_ratio, 2),
                        "volume": int(today_vol)
                    })
            except:
                continue
                
        msg = f"📊 *【策略二：港股主力異常吸籌跟單】* ({today_str})\n🕵️ 篩選標準：今日成交量 > 5日均量 1.5 倍 + 收紅盤\n------------------------\n"
        if triggered_stocks:
            triggered_stocks = sorted(triggered_stocks, key=lambda x: x["ratio"], reverse=True)[:5]
            for s in triggered_stocks:
                msg += f"🔥 `{s['id']} {s['name']}`\n💰 收盤價：`{s['close']} HKD`\n📈 今日量比：`{s['ratio']}` 倍 (量能顯著異常放大)\n📊 成交量：`{s['volume']:,}` 股\n------------------------\n"
        else:
            msg += "今日港股監控名單暫無主力顯著異常吸籌標的。\n"
            
        send_tg(msg)
    except Exception as e:
        send_tg(f"❌ 港股策略二執行中斷錯誤: {e}")

# ==========================================
# 📈 策略三：港股科技板塊基期回檔價值股 (PE 篩選)
# ==========================================
def scan_strategy_3_fundamental():
    print("📈 啟動 [策略三：港股科技板塊基期回檔價值股]...")
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    triggered_stocks = []
    
    try:
        # yfinance 可以一次拿個股的 Info（包含本益比 PE）
        for ticker, name in HK_TECH_PORTFOLIO.items():
            try:
                t = yf.Ticker(ticker)
                info = t.info
                
                pe = info.get("trailingPE", None)
                close_price = info.get("currentPrice", None) or info.get("regularMarketPreviousClose", None)
                volume = info.get("regularMarketVolume", 0)
                
                if pe is None or close_price is None:
                    continue
                
                # 港股科技股價值篩選標準：
                # 1. 歷史滾動 PE <= 25 倍 (對於龍頭科技股如騰訊、阿里等是相對安全基期)
                # 2. 估值有安全邊際且非仙股 (PE > 0)
                if 0 < pe <= 25.0:
                    pure_code = ticker.split('.')[0]
                    triggered_stocks.append({
                        "id": pure_code,
                        "name": name,
                        "close": round(close_price, 2),
                        "pe": round(pe, 2),
                        "volume": int(volume)
                    })
                time.sleep(0.5) # 稍微緩衝，避免請求頻繁被 Yahoo 阻擋
            except:
                continue
                
        msg = f"🤖 *【策略三：港股 AI 與科技估值修正價值股】* ({today_str})\n篩選標準：科技龍頭 + 歷史 PE ≤ 25倍 (具備估值安全邊際)：\n\n"
        if triggered_stocks:
            triggered_stocks = sorted(triggered_stocks, key=lambda x: x["pe"])[:6]
            for stock in triggered_stocks:
                msg += f"📌 *{stock['id']} {stock['name']}*\n💰 當前股價：`{stock['close']} HKD`\n📊 目前本益比：`{stock['pe']}` 倍\n📈 今日成交量：`{stock['volume']:,}` 股\n💡 評語：巨頭基本面優勢，估值已修正至合理區間。\n------------------------\n"
        else:
            msg += "今日港股科技股中，暫無符合「PE ≤ 25 且數據完整」的標的。"
            
        send_tg(msg)
    except Exception as e:
        send_tg(f"❌ 港股策略三執行中斷錯誤: {e}")

# ==========================================
# 🏁 程式進入點
# ==========================================
if __name__ == "__main__":
    print("🤖 啟動香港股市科技/AI 策略掃描排程...")
    
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
        
        print("⏳ 正在執行策略一 (強勢突破)...")
        try: scan_strategy_1_breakout()
        except Exception as e: send_tg(f"❌ 策略一執行中斷錯誤: {e}")
            
        time.sleep(5) 
        
        print("⏳ 正在執行策略二 (主力吸籌)...")
        try: scan_strategy_2_chips()
        except Exception as e: send_tg(f"❌ 策略二執行中斷錯誤: {e}")
            
        time.sleep(5)
        
        print("⏳ 正在執行策略三 (低估值價值股)...")
        try: scan_strategy_3_fundamental()
        except Exception as e: send_tg(f"❌ 策略三執行中斷錯誤: {e}")
            
        print("✨ 港股策略掃描流程全數執行完畢。")
