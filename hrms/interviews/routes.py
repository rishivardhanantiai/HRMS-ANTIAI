from flask import Blueprint, render_template, request, jsonify, session, redirect
from datetime import datetime, timedelta
import uuid
import pytz
from icalendar import Calendar, Event, vCalAddress, vText
import json

from utils.auth import login_required, role_required
from utils.db import get_db, release_db
from utils.mailer import send_meeting_invite, SENDER_EMAIL, COMPANY_NAME
from hrms.notifications.routes import create_notification
from utils.google_calendar import get_credentials, sync_calendar_event, cancel_calendar_event

interviews_bp = Blueprint("interviews", __name__, url_prefix="/hrms/interviews")

def _generate_ics(uid, sequence, dtstart, dtend, summary, location, method="REQUEST"):
    cal = Calendar()
    cal.add('prodid', f'-//{COMPANY_NAME} HRMS//EN')
    cal.add('version', '2.0')
    cal.add('method', method)

    event = Event()
    event.add('uid', uid)
    event.add('dtstamp', datetime.utcnow().replace(tzinfo=pytz.UTC))
    event.add('dtstart', dtstart)
    event.add('dtend', dtend)
    event.add('summary', summary)
    event.add('location', location)
    event.add('sequence', sequence)
    event.add('status', 'CONFIRMED' if method == 'REQUEST' else 'CANCELLED')

    organizer = vCalAddress(f'MAILTO:{SENDER_EMAIL}')
    organizer.params['cn'] = vText(f"{COMPANY_NAME} HR")
    event['organizer'] = organizer

    cal.add_component(event)
    return cal.to_ical()


@interviews_bp.route("/", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def index():
    conn, cur = None, None
    interviews = []
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("""
                SELECT ci.*, 
                       COALESCE(e.full_name, a.name) as candidate_name, 
                       COALESCE(e.email, a.email) as candidate_email, 
                       COALESCE(e.designation, j.title) as job_title
                FROM candidate_interviews ci
                LEFT JOIN hrms_employees e ON ci.employee_id = e.id
                LEFT JOIN applications a ON ci.application_id = a.id
                LEFT JOIN jobs j ON a.job_id = j.id
                ORDER BY ci.scheduled_at ASC
            """)
            interviews = cur.fetchall()
    except Exception as e:
        print("Error fetching interviews via direct DB, trying Supabase REST fallback:", e)
        try:
            import utils.supabase_rest as supabase_rest
            ci_rows = supabase_rest.get_rows("candidate_interviews", {"order": "scheduled_at.asc"})
            employees = {str(emp['id']): emp for emp in supabase_rest.get_rows("hrms_employees")}
            applications = {str(app['id']): app for app in supabase_rest.get_rows("applications")}
            jobs = {str(job['id']): job for job in supabase_rest.get_rows("jobs")}
            
            interviews = []
            for ci in ci_rows:
                emp_id = str(ci.get("employee_id")) if ci.get("employee_id") else None
                app_id = str(ci.get("application_id")) if ci.get("application_id") else None
                
                candidate_name = "-"
                candidate_email = "-"
                job_title = "-"
                
                if emp_id and emp_id in employees:
                    candidate_name = employees[emp_id].get("full_name") or "-"
                    candidate_email = employees[emp_id].get("email") or "-"
                    job_title = employees[emp_id].get("designation") or "Employee"
                elif app_id and app_id in applications:
                    candidate_name = applications[app_id].get("name") or "-"
                    candidate_email = applications[app_id].get("email") or "-"
                    job_id = str(applications[app_id].get("job_id")) if applications[app_id].get("job_id") else None
                    if job_id and job_id in jobs:
                        job_title = jobs[job_id].get("title") or "-"
                
                from utils.supabase_rest import _safe_parse_iso
                scheduled_at = _safe_parse_iso(ci.get("scheduled_at"))
                
                interviews.append({
                    "id": ci.get("id"),
                    "employee_id": ci.get("employee_id"),
                    "application_id": ci.get("application_id"),
                    "scheduled_at": scheduled_at,
                    "duration_minutes": ci.get("duration_minutes") or 30,
                    "location": ci.get("location") or "Virtual",
                    "ics_uid": ci.get("ics_uid"),
                    "ics_sequence": ci.get("ics_sequence") or 0,
                    "status": ci.get("status") or "Scheduled",
                    "scheduled_by": ci.get("scheduled_by"),
                    "candidate_name": candidate_name,
                    "candidate_email": candidate_email,
                    "job_title": job_title
                })
        except Exception as rest_err:
            print("Supabase REST fallback for interviews failed:", rest_err)
    finally:
        if conn:
            release_db(conn, cur)
            
    return render_template("hrms/interviews.html", interviews=interviews)


@interviews_bp.route("/schedule", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def schedule_interview():
    employee_id = request.form.get("employee_id")
    application_id = request.form.get("application_id")
    date_str = request.form.get("date")
    time_str = request.form.get("time")
    duration = int(request.form.get("duration_minutes", 30))
    location = request.form.get("location", "Virtual")
    notes = request.form.get("notes", "").strip()
    
    if not (employee_id or application_id) or not all([date_str, time_str]):
        return jsonify({"error": "Missing required fields."}), 400

    candidate_name = None
    candidate_email = None

    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            if application_id:
                cur.execute("SELECT name, email FROM applications WHERE id = %s", (application_id,))
            else:
                cur.execute("SELECT full_name as name, email FROM hrms_employees WHERE id = %s", (employee_id,))
                
            candidate = cur.fetchone()
            if candidate:
                candidate_name = candidate["name"]
                candidate_email = candidate["email"]
    except Exception as db_err:
        print("Database connection failed during candidate retrieval, trying Supabase REST fallback:", db_err)
    finally:
        if conn:
            release_db(conn, cur)

    # REST Fallback for candidate details
    if not candidate_name or not candidate_email:
        try:
            import utils.supabase_rest as supabase_rest
            if application_id:
                app_row = supabase_rest.get_first_row("applications", {"id": f"eq.{application_id}"})
                if app_row:
                    candidate_name = app_row.get("name")
                    candidate_email = app_row.get("email")
            else:
                emp_row = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{employee_id}"})
                if emp_row:
                    candidate_name = emp_row.get("full_name")
                    candidate_email = emp_row.get("email")
        except Exception as rest_err:
            print("Supabase REST candidate fallback failed:", rest_err)

    if not candidate_name or not candidate_email:
        return jsonify({"error": "Candidate not found or database unavailable."}), 404
            
    dtstart_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    local_tz = pytz.timezone('Asia/Kolkata')
    dtstart = local_tz.localize(dtstart_naive).astimezone(pytz.UTC)
    dtend = dtstart + timedelta(minutes=duration)
    
    uid = f"{uuid.uuid4().hex}@{COMPANY_NAME.replace(' ', '').lower()}.local"
    summary = f"Interview: {candidate_name} & {COMPANY_NAME}"
    
    google_event_id = None
    user_email = session.get("email") or "hr@company.com"
    
    # Try Google Calendar Sync but handle errors gracefully
    try:
        creds = get_credentials(user_email)
        if creds:
            print("Google Calendar connected. Syncing event...")
            google_event_id = sync_calendar_event(
                user_email=user_email,
                summary=summary,
                description=notes or "Interview scheduled via HRMS.",
                start_time=dtstart,
                end_time=dtend,
                attendees=[candidate_email]
            )
    except Exception as cal_err:
        print("Google Calendar sync failed, will rely on SMTP:", cal_err)
        google_event_id = None
        
    # ALWAYS send the custom SMTP invitation email to candidate to guarantee email delivery
    print("Sending SMTP invitation email to candidate...")
    ics_bytes = _generate_ics(uid, 0, dtstart, dtend, summary, location)
    notes_paragraph = f"<p><strong>Note:</strong> {notes}</p>" if notes else ""
    body_html = f"""
        <p>Hi {candidate_name},</p>
        <p>We would like to invite you for an interview.</p>
        {notes_paragraph}
        <p><strong>When:</strong> {dtstart_naive.strftime('%A, %B %d, %Y at %I:%M %p')}</p>
        <p><strong>Duration:</strong> {duration} minutes</p>
        <p><strong>Location/Link:</strong> {location}</p>
        <p>Please find the calendar invite attached. You can RSVP directly from your email client.</p>
        <p>Looking forward to speaking with you!</p>
    """
    success = send_meeting_invite(candidate_email, candidate_name, summary, body_html, ics_bytes)
    if not success:
        return jsonify({"error": "Failed to send email invite."}), 500
            
    # Insert record into database
    db_success = False
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("""
                INSERT INTO candidate_interviews 
                (employee_id, application_id, scheduled_at, duration_minutes, location, ics_uid, ics_sequence, status, scheduled_by, google_event_id)
                VALUES (%s, %s, %s, %s, %s, %s, 0, 'Scheduled', %s, %s)
            """, (employee_id or None, application_id or None, dtstart, duration, location, uid, session.get("email") or session.get("role"), google_event_id))
            conn.commit()
            db_success = True
    except Exception as db_err:
        print("Direct database insert failed, trying Supabase REST fallback:", db_err)
    finally:
        if conn:
            release_db(conn, cur)

    # REST Fallback for DB Insertion
    if not db_success:
        try:
            import utils.supabase_rest as supabase_rest
            payload = {
                "employee_id": employee_id or None,
                "application_id": application_id or None,
                "scheduled_at": dtstart.isoformat(),
                "duration_minutes": duration,
                "location": location,
                "ics_uid": uid,
                "ics_sequence": 0,
                "status": "Scheduled",
                "scheduled_by": session.get("email") or session.get("role"),
                "google_event_id": google_event_id
            }
            res = supabase_rest.insert_row("candidate_interviews", payload)
            if res:
                db_success = True
        except Exception as rest_err:
            print("Supabase REST insert fallback failed:", rest_err)

    if not db_success:
        return jsonify({"error": "Failed to record interview in database."}), 500

    return jsonify({"success": True})


@interviews_bp.route("/<interview_id>/reschedule", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def reschedule_interview(interview_id):
    date_str = request.form.get("date")
    time_str = request.form.get("time")
    duration = int(request.form.get("duration_minutes", 30))
    location = request.form.get("location", "Virtual")
    
    interview = None
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("""
                SELECT ci.*, 
                       COALESCE(e.full_name, a.name) as candidate_name, 
                       COALESCE(e.email, a.email) as candidate_email 
                FROM candidate_interviews ci
                LEFT JOIN hrms_employees e ON ci.employee_id = e.id
                LEFT JOIN applications a ON ci.application_id = a.id
                WHERE ci.id = %s
            """, (interview_id,))
            interview = cur.fetchone()
    except Exception as db_err:
        print("Database select failed during reschedule, trying Supabase REST fallback:", db_err)
    finally:
        if conn:
            release_db(conn, cur)

    # REST Fallback for fetch
    if not interview:
        try:
            import utils.supabase_rest as supabase_rest
            ci_row = supabase_rest.get_first_row("candidate_interviews", {"id": f"eq.{interview_id}"})
            if ci_row:
                candidate_name = "-"
                candidate_email = "-"
                emp_id = ci_row.get("employee_id")
                app_id = ci_row.get("application_id")
                if emp_id:
                    emp = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{emp_id}"})
                    if emp:
                        candidate_name = emp.get("full_name") or "-"
                        candidate_email = emp.get("email") or "-"
                elif app_id:
                    app = supabase_rest.get_first_row("applications", {"id": f"eq.{app_id}"})
                    if app:
                        candidate_name = app.get("name") or "-"
                        candidate_email = app.get("email") or "-"
                
                interview = {
                    "id": ci_row.get("id"),
                    "ics_uid": ci_row.get("ics_uid"),
                    "ics_sequence": ci_row.get("ics_sequence") or 0,
                    "google_event_id": ci_row.get("google_event_id"),
                    "location": ci_row.get("location"),
                    "scheduled_at": ci_row.get("scheduled_at"),
                    "candidate_name": candidate_name,
                    "candidate_email": candidate_email
                }
        except Exception as rest_err:
            print("Supabase REST fallback failed during reschedule lookup:", rest_err)

    if not interview:
        return jsonify({"error": "Interview not found."}), 404
        
    dtstart_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    local_tz = pytz.timezone('Asia/Kolkata')
    dtstart = local_tz.localize(dtstart_naive).astimezone(pytz.UTC)
    dtend = dtstart + timedelta(minutes=duration)
    
    new_seq = (interview['ics_sequence'] or 0) + 1
    summary = f"UPDATED Interview: {interview['candidate_name']} & {COMPANY_NAME}"
    
    google_event_id = interview.get('google_event_id')
    user_email = session.get("email") or "hr@company.com"
    
    # Try Google Calendar Reschedule with try-except wrapper
    try:
        creds = get_credentials(user_email)
        if creds:
            print("Google Calendar connected. Rescheduling/updating event...")
            google_event_id = sync_calendar_event(
                user_email=user_email,
                summary=summary,
                description="Interview rescheduled via HRMS.",
                start_time=dtstart,
                end_time=dtend,
                attendees=[interview['candidate_email']],
                event_id=google_event_id
            )
    except Exception as cal_err:
        print("Google Calendar reschedule failed, using SMTP fallback:", cal_err)
        google_event_id = None
        
    # ALWAYS send the SMTP reschedule invitation email to candidate to guarantee email delivery
    print("Sending SMTP reschedule invitation email...")
    ics_bytes = _generate_ics(interview['ics_uid'], new_seq, dtstart, dtend, summary, location)
    body_html = f"""
        <p>Hi {interview['candidate_name']},</p>
        <p>Your interview has been rescheduled.</p>
        <p><strong>New Time:</strong> {dtstart_naive.strftime('%A, %B %d, %Y at %I:%M %p')}</p>
        <p><strong>Duration:</strong> {duration} minutes</p>
        <p><strong>Location/Link:</strong> {location}</p>
        <p>Please find the updated calendar invite attached.</p>
    """
    success = send_meeting_invite(interview['candidate_email'], interview['candidate_name'], summary, body_html, ics_bytes)
    if not success:
        return jsonify({"error": "Failed to send updated invite."}), 500
            
    # Update Database record
    db_success = False
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("""
                UPDATE candidate_interviews 
                SET scheduled_at = %s, duration_minutes = %s, location = %s, ics_sequence = %s, status = 'Rescheduled', google_event_id = %s
                WHERE id = %s
            """, (dtstart, duration, location, new_seq, google_event_id, interview_id))
            conn.commit()
            db_success = True
    except Exception as db_err:
        print("Direct database update failed during reschedule, trying Supabase REST fallback:", db_err)
    finally:
        if conn:
            release_db(conn, cur)

    # REST Fallback for DB update
    if not db_success:
        try:
            import utils.supabase_rest as supabase_rest
            payload = {
                "scheduled_at": dtstart.isoformat(),
                "duration_minutes": duration,
                "location": location,
                "ics_sequence": new_seq,
                "status": "Rescheduled",
                "google_event_id": google_event_id
            }
            res = supabase_rest.update_rows("candidate_interviews", {"id": f"eq.{interview_id}"}, payload)
            if res:
                db_success = True
        except Exception as rest_err:
            print("Supabase REST reschedule update fallback failed:", rest_err)

    if not db_success:
        return jsonify({"error": "Failed to update reschedule in database."}), 500

    return jsonify({"success": True})


@interviews_bp.route("/<interview_id>/cancel", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def cancel_interview(interview_id):
    interview = None
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("""
                SELECT ci.*, 
                       COALESCE(e.full_name, a.name) as candidate_name, 
                       COALESCE(e.email, a.email) as candidate_email 
                FROM candidate_interviews ci
                LEFT JOIN hrms_employees e ON ci.employee_id = e.id
                LEFT JOIN applications a ON ci.application_id = a.id
                WHERE ci.id = %s
            """, (interview_id,))
            interview = cur.fetchone()
    except Exception as db_err:
        print("Database select failed during cancellation, trying Supabase REST fallback:", db_err)
    finally:
        if conn:
            release_db(conn, cur)

    # REST Fallback for fetch
    if not interview:
        try:
            import utils.supabase_rest as supabase_rest
            ci_row = supabase_rest.get_first_row("candidate_interviews", {"id": f"eq.{interview_id}"})
            if ci_row:
                candidate_name = "-"
                candidate_email = "-"
                emp_id = ci_row.get("employee_id")
                app_id = ci_row.get("application_id")
                if emp_id:
                    emp = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{emp_id}"})
                    if emp:
                        candidate_name = emp.get("full_name") or "-"
                        candidate_email = emp.get("email") or "-"
                elif app_id:
                    app = supabase_rest.get_first_row("applications", {"id": f"eq.{app_id}"})
                    if app:
                        candidate_name = app.get("name") or "-"
                        candidate_email = app.get("email") or "-"
                
                interview = {
                    "id": ci_row.get("id"),
                    "ics_uid": ci_row.get("ics_uid"),
                    "ics_sequence": ci_row.get("ics_sequence") or 0,
                    "google_event_id": ci_row.get("google_event_id"),
                    "location": ci_row.get("location"),
                    "scheduled_at": ci_row.get("scheduled_at"),
                    "candidate_name": candidate_name,
                    "candidate_email": candidate_email
                }
        except Exception as rest_err:
            print("Supabase REST fallback failed during cancellation lookup:", rest_err)

    if not interview:
        return jsonify({"error": "Interview not found."}), 404
        
    new_seq = (interview['ics_sequence'] or 0) + 1
    summary = f"CANCELLED Interview: {interview['candidate_name']} & {COMPANY_NAME}"
    
    google_event_id = interview.get('google_event_id')
    user_email = session.get("email") or "hr@company.com"
    
    # Try Google Calendar Cancellation with try-except wrapper
    try:
        creds = get_credentials(user_email)
        if creds and google_event_id:
            print("Google Calendar connected. Cancelling calendar event...")
            cancel_calendar_event(user_email, google_event_id)
    except Exception as cal_err:
        print("Google Calendar cancellation failed, will rely on SMTP:", cal_err)
        
    # ALWAYS send the SMTP cancellation invitation email to candidate to guarantee email delivery
    print("Sending SMTP cancellation email to candidate...")
    sched_time = interview['scheduled_at']
    if isinstance(sched_time, str):
        from utils.supabase_rest import _safe_parse_iso
        sched_time = _safe_parse_iso(sched_time)
        
    ics_bytes = _generate_ics(interview['ics_uid'], new_seq, sched_time, sched_time, summary, interview['location'], method="CANCEL")
    body_html = f"""
        <p>Hi {interview['candidate_name']},</p>
        <p>We are writing to let you know that your scheduled interview has been cancelled.</p>
        <p>Your calendar event should update automatically from the attached file.</p>
    """
    send_meeting_invite(interview['candidate_email'], interview['candidate_name'], summary, body_html, ics_bytes, method="CANCEL")
        
    # Update Database record
    db_success = False
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("""
                UPDATE candidate_interviews 
                SET ics_sequence = %s, status = 'Cancelled', google_event_id = NULL
                WHERE id = %s
            """, (new_seq, interview_id))
            conn.commit()
            db_success = True
    except Exception as db_err:
        print("Direct database update failed during cancel, trying Supabase REST fallback:", db_err)
    finally:
        if conn:
            release_db(conn, cur)

    # REST Fallback for DB update
    if not db_success:
        try:
            import utils.supabase_rest as supabase_rest
            payload = {
                "ics_sequence": new_seq,
                "status": "Cancelled",
                "google_event_id": None
            }
            res = supabase_rest.update_rows("candidate_interviews", {"id": f"eq.{interview_id}"}, payload)
            if res:
                db_success = True
        except Exception as rest_err:
            print("Supabase REST cancel update fallback failed:", rest_err)

    if not db_success:
        return jsonify({"error": "Failed to cancel interview in database."}), 500

    return jsonify({"success": True})
