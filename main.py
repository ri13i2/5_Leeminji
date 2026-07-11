import os
import re
import json
from datetime import datetime
from fastapi import FastAPI, Request
import httpx
from apscheduler.schedulers.background import BackgroundScheduler

app = FastAPI()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

daily_data = {"income": 0, "expense": 0, "balance": 0}

def extract_amount(text):
    # '원' 앞의 숫자와 콤마를 추출합니다.
    match = re.search(r'(?:입금|출금)\s*([\d,]+)', text)
    if match:
        return int(match.group(1).replace(",", ""))
    return 0

def send_to_telegram(text_message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text_message}
    try:
        with httpx.Client() as client:
            client.post(url, json=payload)
    except Exception as e:
        print(f"발송 실패: {e}")

def send_daily_report():
    global daily_data
    
    today_str = datetime.now().strftime("%m월 %d일")
    
    income = daily_data["income"]
    if income < 60000000:
        fee = 430000
    else:
        fee = int(income * 0.007)
        
    message = (
        f"{today_str} 정산\n\n"
        f"입금액 : {income:,}원\n"
        f"출금액 : {daily_data['expense']:,}원\n\n"
        f"수수료 : {fee:,}원\n\n"
        f"현재 잔액 : {daily_data['balance']:,}원\n\n"
    )
    
    send_to_telegram(message)
    
    # 자정이 되면 초기화
    daily_data["income"] = 0
    daily_data["expense"] = 0
    daily_data["balance"] = 0

scheduler = BackgroundScheduler(timezone="Asia/Seoul")
scheduler.add_job(send_daily_report, 'cron', hour=23, minute=50)
scheduler.start()

@app.post("/webhook")
async def handle_sms(request: Request):
    global daily_data
    
    raw_body = await request.body()
    
    # 🔍 스마트폰이 보낸 원본 데이터를 무조건 출력해서 확인합니다.
    print(f"\n--- [수신된 원본 데이터 확인] ---")
    print(raw_body.decode('utf-8'))
    print(f"--------------------------------\n")
    
    try:
        payload = json.loads(raw_body.decode('utf-8'), strict=False)
    except Exception as e:
        print(f"JSON 에러: {e}")
        return {"status": "error"}
        
    sms_message = payload.get("message", "")
    sms_number = payload.get("number", "알수없음")
    
    if not sms_message:
        print("🚨 [경고] 문자 내용(message)이 텅 비어있습니다!")
        return {"status": "error"}
        
    # 1️⃣ [수정] 테스트 문구 차단 로직보다 실제 입/출금 단어 검사를 최우선으로 진행합니다.
    amount = extract_amount(sms_message)
    
    balance_match = re.search(r'잔액\s*([\d,]+)', sms_message)
    if balance_match:
        daily_data["balance"] = int(balance_match.group(1).replace(",", ""))
    
    if "입금" in sms_message:
        daily_data["income"] += amount
        realtime_alert = f"{sms_number}\n{sms_message}"
        send_to_telegram(realtime_alert)
        print(f"✅ 입금 알림 전송 완료 (추출된 금액: {amount})")
        return {"status": "success"}
        
    elif "출금" in sms_message or "결제" in sms_message:
        daily_data["expense"] += amount
        
        realtime_alert = f"{sms_number}\n{sms_message}"
        send_to_telegram(realtime_alert)
        
        expense_alert = (
            "출금 알람\n\n"
            f"현재 출금액 {amount:,}원\n"
            f"총 출금액 {daily_data['expense']:,}원\n\n"
            f"총 합계 {amount:,}원 / {daily_data['expense']:,}원"
        )
        send_to_telegram(expense_alert)
        print(f"✅ 출금 알림 전송 완료 (추출된 금액: {amount})")
        return {"status": "success"}
        
    # 2️⃣ 입/출금 단어가 없는데 [sms_message] 텍스트가 섞여 들어온 경우에만 테스트 성공 문구 발송
    elif "[sms_message]" in sms_message:
        test_alert = f"✅ 동작 테스트 성공\n번호: {sms_number}\n내용: {sms_message}"
        send_to_telegram(test_alert)
        return {"status": "success"}
        
    else:
        print(f"🚨 [경고] '{sms_message}' 내용 안에 '입금'이나 '출금' 단어가 없어서 무시되었습니다.")
        
    return {"status": "success"}

@app.get("/")
def read_root():
    return {"status": "Server is running"}
