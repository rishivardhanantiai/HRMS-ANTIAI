from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from utils.db import get_db, release_db
from utils.mailer import send_email, COMPANY_NAME

def process_email_queue(app):
    """
    Worker loop to process queued announcements.
    Pulls up to 10 'Queued' messages at a time and sends them via Gmail SMTP.
    Limits to 10 per cycle (every 30s) to avoid spamming the SMTP server or hitting the 500/day limit too fast.
    """
    with app.app_context():
        conn, cur = None, None
        try:
            conn, cur = get_db(True)
            if not conn:
                return
                
            cur.execute("""
                SELECT id, subject, body_html, recipient_email 
                FROM outbound_messages 
                WHERE status = 'Queued' 
                ORDER BY created_at ASC 
                LIMIT 10
            """)
            messages = cur.fetchall()
            
            if not messages:
                return
                
            print(f"APScheduler: Processing {len(messages)} queued messages...")
            
            for msg in messages:
                try:
                    # Format body in case there's simple {{company_name}} remaining
                    final_body = msg['body_html'].replace("{{company_name}}", COMPANY_NAME)
                    
                    from utils.mailer import _wrap_html
                    wrapped_body = _wrap_html(
                        title=msg['subject'],
                        preheader=msg['subject'],
                        body_html=final_body
                    )
                    
                    success = send_email(msg['recipient_email'], msg['subject'], wrapped_body)
                    
                    status = 'Sent' if success else 'Failed'
                    cur.execute("""
                        UPDATE outbound_messages 
                        SET status = %s, sent_at = %s 
                        WHERE id = %s
                    """, (status, datetime.utcnow(), msg['id']))
                    conn.commit()
                except Exception as e:
                    print(f"Error sending queued message {msg['id']}: {e}")
                    cur.execute("UPDATE outbound_messages SET status = 'Failed' WHERE id = %s", (msg['id'],))
                    conn.commit()
                    
        except Exception as e:
            print(f"Error in APScheduler process_email_queue: {e}")
        finally:
            if conn:
                release_db(conn, cur)

def start_scheduler(app):
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=process_email_queue, args=[app], trigger="interval", seconds=30)
    scheduler.start()
    return scheduler
