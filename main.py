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

# Debug environment variables (referenced from scripts/send-notifications.js lines 5-7)
print('Environment variables check:')
print('SUPABASE_URL:', os.getenv('SUPABASE_URL'))
print('SUPABASE_ANON_KEY:', os.getenv('SUPABASE_ANON_KEY'))

if not os.getenv('SUPABASE_URL') or not os.getenv('SUPABASE_ANON_KEY'):
    print('Missing required environment variables')
    exit(1)

app = FastAPI()
scheduler = AsyncIOScheduler()

# Initialize Supabase client
supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_ANON_KEY')
)

# Email configuration (referenced from app/api/send-notifications/route.js lines 6-13)
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
    return {"status": "healthy"}

@app.post("/send-notifications")
async def send_notifications():
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

        print('Notification results:', notification_results)
        return {"results": notification_results}

    except Exception as e:
        print('Error processing notifications:', str(e))
        raise HTTPException(status_code=500, detail=str(e))

# Schedule daily notifications (referenced from .github/workflows/cron.yml lines 4-5)
@app.on_event("startup")
async def startup_event():
    scheduler.add_job(send_notifications, CronTrigger(hour=8))  # Run at 8 AM daily
    scheduler.start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))