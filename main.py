from fastapi import FastAPI, HTTPException
from datetime import datetime
import os
from dotenv import load_dotenv
from supabase import create_client
import smtplib
from email.mime.text import MIMEText
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

load_dotenv()

app = FastAPI()
scheduler = AsyncIOScheduler()

# Initialize Supabase client
supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_ANON_KEY')
)

def send_email(to_email: str, subject: str, body: str) -> bool:
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = os.getenv('EMAIL_FROM')
    msg['To'] = to_email

    try:
        with smtplib.SMTP(os.getenv('EMAIL_SERVER'), 587) as server:
            server.starttls()
            server.login(os.getenv('EMAIL_FROM'), os.getenv('EMAIL_PASSWORD'))
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

@app.get("/")
async def root():
    return {"status": "running"}

async def scheduled_notifications():
    try:
        response = supabase.table('students').select('*').eq('payment_status', 'active').execute()
        students = response.data

        today = datetime.now()
        notification_results = []

        for student in students:
            due_date = datetime.strptime(student['next_due_date'], '%Y-%m-%d')
            days_diff = (due_date - today).days

            notification_type = None
            if days_diff in [7, 3, 1]:
                notification_type = 'reminder'
            elif days_diff == 0:
                notification_type = 'due'
            elif days_diff in [-1, -3, -7]:
                notification_type = 'overdue'

            if notification_type:
                email_body = f"Dear {student['parent_name']},\n\nThis is a {notification_type} notification for {student['name']}'s payment due on {student['next_due_date']}."
                
                if send_email(student['email'], f"Payment {notification_type} for {student['name']}", email_body):
                    supabase.table('notifications').insert({
                        'student_id': student['id'],
                        'type': notification_type,
                        'sent_date': today.isoformat()
                    }).execute()

                    notification_results.append({
                        'success': True,
                        'student': student['name'],
                        'type': notification_type
                    })
                else:
                    notification_results.append({
                        'success': False,
                        'student': student['name'],
                        'error': 'Failed to send email'
                    })

        return {'results': notification_results}

    except Exception as e:
        print(f"Scheduled task error: {str(e)}")

@app.post("/send-notifications")
async def send_notifications():
    try:
        return await scheduled_notifications()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("startup")
async def startup_event():
    scheduler.add_job(
        scheduled_notifications,
        CronTrigger(hour=9, minute=0),  # Runs daily at 9:00 AM
        id="send_notifications",
        name="Send payment notifications"
    )
    scheduler.start()

@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
