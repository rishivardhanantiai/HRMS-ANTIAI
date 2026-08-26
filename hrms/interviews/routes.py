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
                SELECT ci.*, e.full_name as candidate_name, e.email as candidate_email, e.job_title
                FROM candidate_interviews ci
                JOIN hrms_employees e ON ci.employee_id = e.id
                ORDER BY ci.scheduled_at ASC
            """)
            interviews = cur.fetchall()
    except Exception as e:
        print("Error fetching interviews:", e)
    finally:
        if conn:
            release_db(conn, cur)
            
    return render_template("hrms/interviews.html", interviews=interviews)


@interviews_bp.route("/schedule", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def schedule_interview():
    employee_id = request.form.get("employee_id")
    date_str = request.form.get("date")
    time_str = request.form.get("time")
    duration = int(request.form.get("duration_minutes", 30))
    location = request.form.get("location", "Virtual")
    
    if not all([employee_id, date_str, time_str]):
        return jsonify({"error": "Missing required fields."}), 400

    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
            
        cur.execute("SELECT full_name as name, email FROM hrms_employees WHERE id = %s", (employee_id,))
        candidate = cur.fetchone()
        if not candidate:
            return jsonify({"error": "Candidate not found."}), 404
            
        dtstart_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        # Assume input is local time (IST), convert to UTC for the .ics
        # For simplicity, assuming the local timezone is IST (UTC+5:30) 
        # A more robust solution would pass the timezone from the frontend
        local_tz = pytz.timezone('Asia/Kolkata')
        dtstart = local_tz.localize(dtstart_naive).astimezone(pytz.UTC)
        dtend = dtstart + timedelta(minutes=duration)
        
        uid = f"{uuid.uuid4().hex}@{COMPANY_NAME.replace(' ', '').lower()}.local"
        summary = f"Interview: {candidate['name']} & {COMPANY_NAME}"
        
        ics_bytes = _generate_ics(uid, 0, dtstart, dtend, summary, location)
        
        body_html = f"""
            <p>Hi {candidate['name']},</p>
            <p>We would like to invite you for an interview.</p>
            <p><strong>When:</strong> {dtstart_naive.strftime('%A, %B %d, %Y at %I:%M %p')}</p>
            <p><strong>Duration:</strong> {duration} minutes</p>
            <p><strong>Location/Link:</strong> {location}</p>
            <p>Please find the calendar invite attached. You can RSVP directly from your email client.</p>
            <p>Looking forward to speaking with you!</p>
        """
        
        success = send_meeting_invite(candidate['email'], candidate['name'], summary, body_html, ics_bytes)
        if not success:
            return jsonify({"error": "Failed to send email invite."}), 500
            
        cur.execute("""
            INSERT INTO candidate_interviews 
            (employee_id, scheduled_at, duration_minutes, location, ics_uid, ics_sequence, status, scheduled_by)
            VALUES (%s, %s, %s, %s, %s, 0, 'Scheduled', %s)
        """, (employee_id, dtstart, duration, location, uid, session.get("user")))
        
        conn.commit()
        return jsonify({"success": True})
        
    except Exception as e:
        print(f"Error scheduling interview: {e}")
        return jsonify({"error": "Server error."}), 500
    finally:
        if conn:
            release_db(conn, cur)


@interviews_bp.route("/<interview_id>/reschedule", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def reschedule_interview(interview_id):
    date_str = request.form.get("date")
    time_str = request.form.get("time")
    duration = int(request.form.get("duration_minutes", 30))
    location = request.form.get("location", "Virtual")
    
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
            
        cur.execute("""
            SELECT ci.*, e.full_name as candidate_name, e.email as candidate_email 
            FROM candidate_interviews ci
            JOIN hrms_employees e ON ci.employee_id = e.id
            WHERE ci.id = %s
        """, (interview_id,))
        interview = cur.fetchone()
        
        if not interview:
            return jsonify({"error": "Interview not found."}), 404
            
        dtstart_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        local_tz = pytz.timezone('Asia/Kolkata')
        dtstart = local_tz.localize(dtstart_naive).astimezone(pytz.UTC)
        dtend = dtstart + timedelta(minutes=duration)
        
        new_seq = interview['ics_sequence'] + 1
        summary = f"UPDATED Interview: {interview['candidate_name']} & {COMPANY_NAME}"
        
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
            
        cur.execute("""
            UPDATE candidate_interviews 
            SET scheduled_at = %s, duration_minutes = %s, location = %s, ics_sequence = %s, status = 'Rescheduled'
            WHERE id = %s
        """, (dtstart, duration, location, new_seq, interview_id))
        
        conn.commit()
        return jsonify({"success": True})
        
    except Exception as e:
        print(f"Error rescheduling interview: {e}")
        return jsonify({"error": "Server error."}), 500
    finally:
        if conn:
            release_db(conn, cur)


@interviews_bp.route("/<interview_id>/cancel", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def cancel_interview(interview_id):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
            
        cur.execute("""
            SELECT ci.*, e.full_name as candidate_name, e.email as candidate_email 
            FROM candidate_interviews ci
            JOIN hrms_employees e ON ci.employee_id = e.id
            WHERE ci.id = %s
        """, (interview_id,))
        interview = cur.fetchone()
        
        if not interview:
            return jsonify({"error": "Interview not found."}), 404
            
        new_seq = interview['ics_sequence'] + 1
        summary = f"CANCELLED Interview: {interview['candidate_name']} & {COMPANY_NAME}"
        
        # for cancellation, we just reuse the old start time in the ics
        ics_bytes = _generate_ics(interview['ics_uid'], new_seq, interview['scheduled_at'], interview['scheduled_at'], summary, interview['location'], method="CANCEL")
        
        body_html = f"""
            <p>Hi {interview['candidate_name']},</p>
            <p>We are writing to let you know that your scheduled interview has been cancelled.</p>
            <p>Your calendar event should update automatically from the attached file.</p>
        """
        
        send_meeting_invite(interview['candidate_email'], interview['candidate_name'], summary, body_html, ics_bytes, method="CANCEL")
            
        cur.execute("""
            UPDATE candidate_interviews 
            SET ics_sequence = %s, status = 'Cancelled'
            WHERE id = %s
        """, (new_seq, interview_id))
        
        conn.commit()
        return jsonify({"success": True})
        
    except Exception as e:
        print(f"Error cancelling interview: {e}")
        return jsonify({"error": "Server error."}), 500
    finally:
        if conn:
            release_db(conn, cur)
