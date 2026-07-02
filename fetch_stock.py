import os
import sys
import requests
# import yfinance as yf  # 視需要安裝
# from FinMind.data import DataLoader

def send_tg(text):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

# === 策略 1：盤中突破 (技術面) ===
def check_intraday_breakout():
    # 範例邏輯：讀取自訂清單，比對 K 線
    msg = "🔔 *【策略一：盤中動態突破】*\n"
    msg += "📈 標的：`2330 台積電` 突破關鍵壓力位！\n"
    msg += "💡 現價：1020 | 觸發條件：股價站上 ATR 上軌"
    send_tg(msg)

# === 策略 2：盤後籌碼 (法人跟單) ===
def check_afterhours_chips():
    # 範例邏輯：串接 FinMind 篩選今日投信剛轉買的標的
    msg = "📊 *【策略二：盤後籌碼集中股】*\n"
    msg += "🔥 *投信連續買超前 3 名：*\n"
    msg += "1. `XXXX` (連買 3 天，今日買超 1500 張)\n"
    msg += "2. `YYYY` (連買 2 天)\n"
    msg += "⚠️ 備註：籌碼集中度大於 20%，注意主力分點鎖股。"
    send_tg(msg)

# === 策略 3：基本面篩選 (月營收/財報) ===
def check_fundamental_growth():
    # 範例邏輯：每月營收公布後，篩選營收年增與創新高的標的
    msg = "📑 *【策略三：基本面營收新高股】*\n"
    msg += "🚀 *最新月營收雙增 (月增+年增) 標的：*\n"
    msg += "▪️ `ZZZZ`：營收創 12 個月新高，年增率 +35%\n"
    msg += "🍀 適合納入中長線策略觀察清單。"
    send_tg(msg)

if __name__ == "__main__":
    # 從指令列參數判斷要跑哪一個策略
    if len(sys.argv) < 2:
        print("請指定策略參數 (strategy_1 / strategy_2 / strategy_3)")
        sys.exit(1)
        
    strategy = sys.argv[1]
    
    if strategy == "strategy_1":
        check_intraday_breakout()
    elif strategy == "strategy_2":
        check_afterhours_chips()
    elif strategy == "strategy_3":
        check_fundamental_growth()
