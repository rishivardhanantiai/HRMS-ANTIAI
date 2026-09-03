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
                    
                    success = send_email(msg['recipient_email'], msg['subject'], wrapped_body, log_email=False)
                    
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

def run_daily_reminders(app):
    """
    Worker job to check active employee milestones:
    - Probation period (3 months / 90 days) ending in exactly 7 days.
    - Work anniversary (1+ years) in exactly 7 days.
    Fires in-app notifications to HR and Admin roles.
    """
    with app.app_context():
        from hrms.notifications.routes import create_notification
        conn, cur = None, None
        try:
            conn, cur = get_db(True)
            if not conn:
                return
                
            from datetime import date, timedelta
            today = date.today()
            
            # 1. Check Probation ending in 7 days (joined exactly 83 days ago)
            probation_join_target = today - timedelta(days=83)
            cur.execute("""
                SELECT id, full_name, joining_date 
                FROM hrms_employees 
                WHERE status = 'Active' AND joining_date = %s
            """, (probation_join_target,))
            probation_emps = cur.fetchall()
            
            for emp in probation_emps:
                end_date = emp['joining_date'] + timedelta(days=90)
                msg = f"Probation period for {emp['full_name']} ends in 7 days (on {end_date.strftime('%Y-%m-%d')})."
                
                # Deduplicate check (prevent multiple reminders for the same event on same day)
                cur.execute("""
                    SELECT id FROM notifications 
                    WHERE type = 'probation_reminder' AND message = %s AND created_at >= CURRENT_DATE
                """, (msg,))
                if not cur.fetchone():
                    create_notification("HR", "probation_reminder", msg, "/hrms/employees/ui")
                    create_notification("Admin", "probation_reminder", msg, "/hrms/employees/ui")
                    
            # 2. Check Work Anniversary in 7 days
            target_anniv = today + timedelta(days=7)
            cur.execute("""
                SELECT id, full_name, joining_date 
                FROM hrms_employees 
                WHERE status = 'Active' 
                  AND EXTRACT(MONTH FROM joining_date) = %s 
                  AND EXTRACT(DAY FROM joining_date) = %s
                  AND joining_date <= %s
            """, (target_anniv.month, target_anniv.day, today - timedelta(days=365)))
            anniv_emps = cur.fetchall()
            
            for emp in anniv_emps:
                years = target_anniv.year - emp['joining_date'].year
                if years <= 0:
                    continue
                msg = f"{emp['full_name']}'s {years}-year work anniversary is in 7 days (on {target_anniv.strftime('%Y-%m-%d')})."
                
                # Deduplicate check
                cur.execute("""
                    SELECT id FROM notifications 
                    WHERE type = 'anniversary_reminder' AND message = %s AND created_at >= CURRENT_DATE
                """, (msg,))
                if not cur.fetchone():
                    create_notification("HR", "anniversary_reminder", msg, "/hrms/employees/ui")
                    create_notification("Admin", "anniversary_reminder", msg, "/hrms/employees/ui")
                    
            conn.commit()
        except Exception as e:
            print(f"Error in run_daily_reminders: {e}")
        finally:
            if conn:
                release_db(conn, cur)

def run_candidate_pii_purge(app):
    """
    Auto-purge/anonymize PII for rejected candidates older than the configured threshold (in months).
    """
    with app.app_context():
        conn, cur = None, None
        try:
            conn, cur = get_db(True)
            if not conn:
                return

            # Fetch candidate_retention_months from company_settings (default: 12)
            cur.execute("SELECT candidate_retention_months FROM company_settings LIMIT 1")
            row = cur.fetchone()
            retention_months = row["candidate_retention_months"] if row and row["candidate_retention_months"] is not None else 12

            # Calculate cutoff date
            from datetime import datetime, timedelta
            # We use roughly 30 days per month
            cutoff_date = datetime.now() - timedelta(days=retention_months * 30)

            # Query candidates to purge: status = 'Rejected', applied_at < cutoff_date, email is not null and not anonymized
            cur.execute("""
                SELECT id, name, email, phone, resume_url, applied_at 
                FROM applications 
                WHERE status = 'Rejected' 
                  AND applied_at < %s 
                  AND email IS NOT NULL
                  AND email NOT LIKE 'anonymized-%%'
            """, (cutoff_date,))
            candidates_to_purge = cur.fetchall()

            if candidates_to_purge:
                print(f"APScheduler: Purging PII for {len(candidates_to_purge)} rejected candidate(s)...")
                from utils.audit import log_action
                for cand in candidates_to_purge:
                    # Log to audit_log before deleting
                    log_action(
                        actor="System",
                        action="candidate_pii_purged",
                        target_table="applications",
                        target_id=cand["id"],
                        details={
                            "email": cand["email"],
                            "applied_at": cand["applied_at"].isoformat() if cand["applied_at"] else None,
                            "retention_months": retention_months
                        }
                    )
                    
                    # Delete the resume file from Supabase storage if it exists
                    if cand["resume_url"]:
                        try:
                            import os
                            bucket = os.getenv("SUPABASE_RESUME_BUCKET", "resumes")
                            public_marker = f"/public/{bucket}/"
                            if public_marker in cand["resume_url"]:
                                parts = cand["resume_url"].split(public_marker)
                                if len(parts) > 1:
                                    object_key = parts[1]
                                    from utils.supabase_rest import delete_file
                                    delete_file(object_key)
                        except Exception as storage_err:
                            print(f"Error purging candidate storage file: {storage_err}")

                    # Nullify PII fields
                    cur.execute("""
                        UPDATE applications 
                        SET name = 'Anonymized', 
                            email = 'anonymized-' || id || '@example.com', 
                            phone = NULL, 
                            notes = NULL, 
                            resume_url = NULL 
                        WHERE id = %s
                    """, (cand["id"],))
                conn.commit()
                print("APScheduler: Purge completed successfully.")
        except Exception as e:
            print(f"Error in run_candidate_pii_purge: {e}")
            if conn:
                try: conn.rollback()
                except Exception: pass
        finally:
            if conn:
                release_db(conn, cur)

def start_scheduler(app):
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=process_email_queue, args=[app], trigger="interval", seconds=30)
    
    # Run daily reminders immediately on startup and then every 24 hours
    from datetime import datetime
    scheduler.add_job(func=run_daily_reminders, args=[app], trigger="interval", days=1, next_run_time=datetime.now())
    
    # Run candidate PII purge daily
    scheduler.add_job(func=run_candidate_pii_purge, args=[app], trigger="interval", days=1, next_run_time=datetime.now())
    
    scheduler.start()
    return scheduler
