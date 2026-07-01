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

# 서버 메모리에 데이터 저장 (잔액 변수 추가)
daily_data = {"income": 0, "expense": 0, "balance": 0}

# 💰 IM뱅크 전용 금액 추출기
def extract_amount(text):
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

# 밤 23:59 일일 정산 발송 함수
def send_daily_report():
    global daily_data
    
    # 📅 오늘 날짜 (예: 07월 01일)
    today_str = datetime.now().strftime("%m월 %d일")
    
    # 💸 수수료 자동 계산 로직
    income = daily_data["income"]
    if income < 60000000:
        fee = 430000
    else:
        fee = int(income * 0.007)
        
    # 📝 정산표 양식
    message = (
        f"{today_str} 정산\n\n"
        f"입금액 : {income:,}원\n"
        f"출금액 : {daily_data['expense']:,}원\n\n"
        f"수수료 : {fee:,}원\n\n"
        f"현재 잔액 : {daily_data['balance']:,}원\n\n"
        "우리 01023531107 이민지"
    )
    
    send_to_telegram(message)
    
    # ★ 핵심 포인트: 입출금액만 0원으로 리셋하고, 잔액(balance)은 어제 기록 그대로 살려둡니다!
    daily_data["income"] = 0
    daily_data["expense"] = 0

scheduler = BackgroundScheduler(timezone="Asia/Seoul")
scheduler.add_job(send_daily_report, 'cron', hour=23, minute=59)
scheduler.start()

@app.post("/webhook")
async def handle_sms(request: Request):
    global daily_data
    
    # 500 에러 완벽 방어 코드
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode('utf-8'), strict=False)
    except Exception as e:
        print(f"JSON 에러: {e}")
        return {"status": "error"}
        
    sms_message = payload.get("message", "")
    sms_number = payload.get("number", "알수없음")
    
    if not sms_message:
        return {"status": "error"}
        
    if "[sms_message]" in sms_message:
        test_alert = f"✅ 동작 테스트 성공\n번호: {sms_number}\n내용: {sms_message}"
        send_to_telegram(test_alert)
        return {"status": "success"}
        
    amount = extract_amount(sms_message)
    
    # 🏦 문자에 찍힌 '잔액'을 실시간 업데이트 (오늘 문자가 없으면 어제 기억해 둔 잔액이 유지됨)
    balance_match = re.search(r'잔액\s*([\d,]+)', sms_message)
    if balance_match:
        daily_data["balance"] = int(balance_match.group(1).replace(",", ""))
    
    if "입금" in sms_message:
        daily_data["income"] += amount
        realtime_alert = f"{sms_number}\n{sms_message}"
        send_to_telegram(realtime_alert)
        
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
        
    return {"status": "success"}

@app.get("/")
def read_root():
    return {"status": "Server is running"}
