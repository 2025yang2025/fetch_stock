import os
import requests

def get_stock_data():
    # 這裡放入你的股市篩選邏輯 (例如呼叫 API 或進行量化策略計算)
    # 範例純文字訊息
    message = "🔔 【股市策略提醒】\n📈 標的：XX 股票\n條件：符合突破訊號！"
    return message

def send_telegram_message(text):
    # 從環境變數讀取安全憑證
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown" # 支援粗體、換行等排版
    }
    
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print("訊息發送成功！")
    else:
        print(f"發送失敗：{response.text}")

if __name__ == "__main__":
    content = get_stock_data()
    send_telegram_message(content)
