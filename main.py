import os
import re
import json
import time
from datetime import datetime
from fastapi import FastAPI, Request
import httpx
from apscheduler.schedulers.background import BackgroundScheduler

app = FastAPI()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DATA_FILE = "bank_data.json" 

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"income": 0, "expense": 0, "balance": 0}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def extract_amount(text):
    match = re.search(r'(?:입금|출금).*?([\d,]+)원', text)
    if match:
        return int(match.group(1).replace(",", ""))
    return 0

def send_to_telegram(text_message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text_message}
    
    for attempt in range(3):
        try:
            with httpx.Client() as client:
                response = client.post(url, json=payload, timeout=20.0)
                if response.status_code == 200:
                    return
                else:
                    print(f"텔레그램 응답 오류: {response.text}")
                    
        except httpx.ReadTimeout:
            print("⏳ 텔레그램 서버 응답 지연 (메시지는 정상 전송되었을 수 있으므로 중복 방지를 위해 재시도 취소)")
            return 
            
        except Exception as e:
            print(f"발송 실패 (시도 {attempt+1}/3): {e}")
            
        time.sleep(1)
        
    print("🚨 3회 재시도 후에도 텔레그램 발송에 최종 실패했습니다.")

def send_daily_report():
    data = load_data()
    today_str = datetime.now().strftime("%m월 %d일")
    
    income = data["income"]
    if income < 60000000:
        fee = 430000
    else:
        fee = int(income * 0.007)
        
    message = (
        f"{today_str} 정산\n\n"
        f"입금액 : {income:,}원\n"
        f"출금액 : {data['expense']:,}원\n\n"
        f"수수료 : {fee:,}원\n\n"
        f"현재 잔액 : {data['balance']:,}원\n\n"
    )
    
    send_to_telegram(message)
    
    data["income"] = 0
    data["expense"] = 0
    save_data(data)

scheduler = BackgroundScheduler(timezone="Asia/Seoul")
scheduler.add_job(send_daily_report, 'cron', hour=23, minute=50)
scheduler.start()

@app.post("/webhook")
async def handle_sms(request: Request):
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode('utf-8'), strict=False)
    except Exception as e:
        return {"status": "error"}
        
    sms_message = payload.get("message", "")
    sms_number = payload.get("number", "알수없음")
    
    if not sms_message:
        return {"status": "error"}
        
    if "[sms_message]" in sms_message:
        return {"status": "success"}
        
    amount = extract_amount(sms_message)
    data = load_data()
    
    balance_match = re.search(r'잔액\s*([\d,]+)', sms_message)
    if balance_match:
        data["balance"] = int(balance_match.group(1).replace(",", ""))
        
    trans_type = "입금" if "입금" in sms_message else "출금" if "출금" in sms_message else ""
    
    if trans_type:
        date_match = re.search(r'(\d{2}/\d{2}\s\d{2}:\d{2}(?::\d{2})?)', sms_message)
        trans_date = date_match.group(1) if date_match else datetime.now().strftime("%m/%d %H:%M:%S")
        
        customer_name = "알 수 없음"
        
        # 🛠️ 우리은행 전용 이름 추출
        # 패턴 A: 우리은행 앱 방식 ([입금] 허진희 2,500,000)
        name_match_app = re.search(r'(?:입금|출금)\]?\s+([가-힣A-Za-z]+)\s+[\d,]+', sms_message)
        # 패턴 B: 우리은행 일반 문자 방식 (금액 ~원 뒤, 잔액 앞에 위치)
        name_match_sms = re.search(r'원\s+(.+?)\s+잔액', sms_message)
        
        if name_match_app:
            customer_name = name_match_app.group(1).strip()
        elif name_match_sms:
            customer_name = name_match_sms.group(1).strip()

        formatted_alert = (
            f"[우리은행 이*지 입출금 알림]\n\n"
            f"[일시] {trans_date}\n"
            f"[고객명] {customer_name}\n"
            f"[{trans_type} 금액] {amount:,}원\n"
            f"[잔액] {data['balance']:,}원"
        )
        
        if trans_type == "입금":
            data["income"] += amount
            send_to_telegram(formatted_alert)
            
        elif trans_type == "출금":
            data["expense"] += amount
            send_to_telegram(formatted_alert)
            
            expense_alert = (
                "출금 알람\n\n"
                f"현재 출금액 {amount:,}원\n\n"
                f"총 합계 {amount:,}원 / {data['expense']:,}원"
            )
            send_to_telegram(expense_alert)
            
        save_data(data)
            
    return {"status": "success"}

@app.get("/")
def read_root():
    return {"status": "Server is running"}
