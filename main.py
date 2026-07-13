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

daily_data = {"income": 0, "expense": 0, "balance": 0}

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
                response = client.post(url, json=payload, timeout=10.0)
                if response.status_code == 200:
                    return
                else:
                    print(f"텔레그램 응답 오류: {response.text}")
        except Exception as e:
            print(f"발송 실패 (시도 {attempt+1}/3): {e}")
            
        time.sleep(1)
        
    print("🚨 3회 재시도 후에도 텔레그램 발송에 최종 실패했습니다.")

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
    
    daily_data["income"] = 0
    daily_data["expense"] = 0

scheduler = BackgroundScheduler(timezone="Asia/Seoul")
scheduler.add_job(send_daily_report, 'cron', hour=23, minute=50)
scheduler.start()

@app.post("/webhook")
async def handle_sms(request: Request):
    global daily_data
    
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
    
    balance_match = re.search(r'잔액\s*([\d,]+)', sms_message)
    if balance_match:
        daily_data["balance"] = int(balance_match.group(1).replace(",", ""))
        
    # 거래 종류 파악 (입금 or 출금)
    trans_type = "입금" if "입금" in sms_message else "출금" if "출금" in sms_message else ""
    
    # 입금/출금 단어가 존재할 때만 아래 로직 실행
    if trans_type:
        
        # 1. 일시 추출 (알림 내용에 날짜가 있으면 가져오고, 없으면 서버의 현재 시간 기록)
        date_match = re.search(r'(\d{2}/\d{2}\s\d{2}:\d{2}(?::\d{2})?)', sms_message)
        trans_date = date_match.group(1) if date_match else datetime.now().strftime("%m/%d %H:%M:%S")
        
        # 2. 고객명 추출 (입금/출금 글자 뒤에 있는 사람 이름 추출. 문자 방식이라 이름이 안 올 경우 '알 수 없음'으로 표기)
        name_match = re.search(r'(?:입금|출금)\]?\s+([가-힣A-Za-z]+(?:\s+[가-힣A-Za-z]+)*)\s+[\d,]+원', sms_message)
        customer_name = name_match.group(1) if name_match else "알 수 없음"
        
        # 3. 🎨 유저님이 요청하신 텔레그램 최종 포맷 조립
        formatted_alert = (
            f"[우리은행 이*지 입출금 알림]\n\n"
            f"[일시] {trans_date}\n"
            f"[고객명] {customer_name}\n"
            f"[{trans_type} 금액] {amount:,}원\n"
            f"[잔액] {daily_data['balance']:,}원"
        )
        
        if trans_type == "입금":
            daily_data["income"] += amount
            send_to_telegram(formatted_alert)
            
        elif trans_type == "출금":
            daily_data["expense"] += amount
            send_to_telegram(formatted_alert)
            
            # 기존 출금 누적 합계 알람은 그대로 유지합니다.
            expense_alert = (
                "출금 알람\n\n"
                f"현재 출금액 {amount:,}원\n\n"
                f"총 합계 {amount:,}원 / {daily_data['expense']:,}원"
            )
            send_to_telegram(expense_alert)
            
    return {"status": "success"}

@app.get("/")
def read_root():
    return {"status": "Server is running"}
