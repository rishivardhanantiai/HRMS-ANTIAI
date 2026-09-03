from flask import Blueprint, render_template, request, jsonify, session
from datetime import datetime
import json
import uuid
import re

from utils.auth import login_required, role_required
from utils.db import get_db, release_db
from utils import supabase_rest
from hrms.approvals.routes import create_approval_request

announcements_bp = Blueprint("announcements", __name__, url_prefix="/hrms/announcements")

def hr_admin_required():
    return session.get("role") in ["HR", "Admin"]

def _get_templates():
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn: raise Exception("No db")
        cur.execute("SELECT * FROM message_templates ORDER BY id")
        return cur.fetchall()
    except Exception as e:
        print("Error fetching templates via DB, trying REST:", e)
        try:
            return supabase_rest.get_rows("message_templates", {"order": "id.asc"})
        except Exception as rest_err:
            print("REST fallback for templates failed:", rest_err)
            return []
    finally:
        if conn: release_db(conn, cur)

def _get_departments():
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn: raise Exception("No db")
        cur.execute("SELECT department, count(*) as c FROM hrms_employees WHERE department IS NOT NULL AND TRIM(department) != '' AND status='Active' GROUP BY department ORDER BY department")
        return [{"name": r['department'].strip(), "count": r['c']} for r in cur.fetchall()]
    except Exception as e:
        print("Error fetching departments via DB, trying REST:", e)
        try:
            rows = supabase_rest.get_rows("hrms_employees", {"select": "department", "status": "eq.Active"})
            counts = {}
            for r in rows:
                dept = (r.get("department") or "").strip()
                if dept:
                    counts[dept] = counts.get(dept, 0) + 1
            res = [{"name": k, "count": v} for k, v in counts.items()]
            res.sort(key=lambda x: x["name"])
            return res
        except Exception as rest_err:
            print("REST fallback for departments failed:", rest_err)
            return []
    finally:
        if conn: release_db(conn, cur)

def _get_history():
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn: raise Exception("No db")
        # Group by subject and created_at roughly, or just show last 20 messages
        cur.execute("SELECT * FROM outbound_messages ORDER BY created_at DESC LIMIT 50")
        return cur.fetchall()
    except Exception as e:
        print("Error fetching outbound messages via DB, trying REST:", e)
        try:
            return supabase_rest.get_rows("outbound_messages", {"order": "created_at.desc", "limit": 50})
        except Exception as rest_err:
            print("REST fallback for history failed:", rest_err)
            return []
    finally:
        if conn: release_db(conn, cur)

def _get_active_employees_count():
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn: raise Exception("No db")
        cur.execute("SELECT count(*) as c FROM hrms_employees WHERE status='Active'")
        return cur.fetchone()['c']
    except Exception as e:
        print("Error fetching active count via DB, trying REST:", e)
        try:
            return supabase_rest.get_count("hrms_employees", {"status": "eq.Active"})
        except Exception as rest_err:
            print("REST fallback for active count failed:", rest_err)
            return 0
    finally:
        if conn: release_db(conn, cur)

def _get_all_employees():
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn: raise Exception("No db")
        cur.execute("SELECT id, full_name, email FROM hrms_employees WHERE status != 'Deleted' AND email IS NOT NULL ORDER BY full_name")
        return cur.fetchall()
    except Exception as e:
        print("Error fetching employees via DB, trying REST:", e)
        try:
            return supabase_rest.get_rows("hrms_employees", {"select": "id,full_name,email", "status": "neq.Deleted", "email": "not.is.null", "order": "full_name.asc"})
        except Exception as rest_err:
            print("REST fallback for employees failed:", rest_err)
            return []
    finally:
        if conn: release_db(conn, cur)

@announcements_bp.route("/", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def ui():
    templates = _get_templates()
    departments = _get_departments()
    history = _get_history()
    active_count = _get_active_employees_count()
    
    # Check pending bulk sends and calculate quota
    conn, cur = None, None
    pending_approvals = []
    quota_used = 0
    try:
        conn, cur = get_db(True)
        if not conn: raise Exception("No db")
        cur.execute("SELECT * FROM admin_approval_queue WHERE action_type='bulk_send' AND status='Pending' ORDER BY created_at DESC")
        pending_approvals = cur.fetchall()
        
        # Estimate daily quota used
        cur.execute("SELECT count(*) as c FROM outbound_messages WHERE DATE(created_at) = CURRENT_DATE AND status IN ('Sent', 'Queued')")
        quota_used = cur.fetchone()['c'] or 0
    except Exception as e:
        print("Error in ui DB, trying REST:", e)
        try:
            pending_approvals = supabase_rest.get_rows("admin_approval_queue", {"action_type": "eq.bulk_send", "status": "eq.Pending", "order": "created_at.desc"})
            
            # For quota_used, REST API doesn't easily support DATE(created_at) = CURRENT_DATE.
            # We fetch today's date and use >=
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            c1 = supabase_rest.get_count("outbound_messages", {"created_at": f"gte.{today_str}", "status": "eq.Sent"})
            c2 = supabase_rest.get_count("outbound_messages", {"created_at": f"gte.{today_str}", "status": "eq.Queued"})
            quota_used = c1 + c2
        except Exception as rest_err:
            pass
    finally:
        if conn: release_db(conn, cur)
        
    employees = _get_all_employees()
    quota_limit = 500
    quota_remaining = max(0, quota_limit - quota_used)
        
    return render_template("hrms/announcements.html", 
        templates=templates, 
        departments=departments, 
        history=history,
        active_count=active_count,
        pending_approvals=pending_approvals,
        employees=employees,
        quota_used=quota_used,
        quota_limit=quota_limit,
        quota_remaining=quota_remaining)


@announcements_bp.route("/templates/<template_id>", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def get_template(template_id):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn: raise Exception("No db")
        cur.execute("SELECT * FROM message_templates WHERE id=%s", (template_id,))
        tpl = cur.fetchone()
        if tpl: return jsonify(tpl)
        return jsonify({"error": "Not found"}), 404
    except Exception as e:
        print("Error in get_template DB, trying REST:", e)
        try:
            tpl = supabase_rest.get_first_row("message_templates", {"id": f"eq.{template_id}"})
            if tpl: return jsonify(tpl)
            return jsonify({"error": "Not found"}), 404
        except Exception as rest_err:
            return jsonify({"error": str(rest_err)}), 500
    finally:
        if conn: release_db(conn, cur)


@announcements_bp.route("/templates/<template_id>", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def save_template(template_id):
    subject = request.form.get("subject", "")
    body_html = request.form.get("body_html", "")
    
    if not subject or not body_html:
        return jsonify({"error": "Subject and Body are required."}), 400
        
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn: raise Exception("No db")
        cur.execute("""
            UPDATE message_templates 
            SET subject=%s, body_html=%s, updated_at=NOW() 
            WHERE id=%s
        """, (subject, body_html, template_id))
        if cur.rowcount == 0:
            cur.execute("""
                INSERT INTO message_templates (id, subject, body_html) 
                VALUES (%s, %s, %s)
            """, (template_id, subject, body_html))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        print("Error in save_template DB, trying REST:", e)
        try:
            # Check if exists
            existing = supabase_rest.get_first_row("message_templates", {"id": f"eq.{template_id}"})
            if existing:
                supabase_rest.update_rows("message_templates", {"id": f"eq.{template_id}"}, {"subject": subject, "body_html": body_html, "updated_at": datetime.utcnow().isoformat()})
            else:
                supabase_rest.insert_row("message_templates", {"id": template_id, "subject": subject, "body_html": body_html})
            return jsonify({"success": True})
        except Exception as rest_err:
            return jsonify({"error": str(rest_err)}), 500
    finally:
        if conn: release_db(conn, cur)


@announcements_bp.route("/send", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def send_message():
    subject = request.form.get("subject", "")
    body_html = request.form.get("body_html", "")
    
    send_to_all = request.form.get("send_to_all") == "true"
    departments = request.form.getlist("departments")
    individual_emails = request.form.getlist("individual_emails")
    custom_emails_text = request.form.get("custom_emails", "")
    
    if not subject or not body_html:
        return jsonify({"error": "Subject and body are required."}), 400

    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn: return jsonify({"error": "No db"}), 500
        
        email_map = {} # deduplication map: email -> name
        
        if send_to_all:
            cur.execute("SELECT email, full_name FROM hrms_employees WHERE status='Active' AND email IS NOT NULL")
            for r in cur.fetchall():
                email_map[r["email"]] = r["full_name"]
        else:
            if departments:
                # Use ANY for array check if using psycopg2, or dynamically build IN clause
                format_strings = ','.join(['%s'] * len(departments))
                cur.execute(f"SELECT email, full_name FROM hrms_employees WHERE status='Active' AND department IN ({format_strings}) AND email IS NOT NULL", tuple(departments))
                for r in cur.fetchall():
                    email_map[r["email"]] = r["full_name"]
                    
            if individual_emails:
                format_strings = ','.join(['%s'] * len(individual_emails))
                cur.execute(f"SELECT email, full_name FROM hrms_employees WHERE email IN ({format_strings})", tuple(individual_emails))
                for r in cur.fetchall():
                    email_map[r["email"]] = r["full_name"]
                    
            if custom_emails_text:
                raw_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', custom_emails_text)
                for em in set(raw_emails):
                    if em not in email_map:
                        email_map[em] = em.split('@')[0]
                        
        emails = [{"email": e, "name": n} for e, n in email_map.items()]
            
        if not emails:
            return jsonify({"error": "No valid recipients found."}), 400
        
        # Optional: trim to first N recipients (used by "Send within quota" button)
        limit_to = request.form.get("limit_to")
        if limit_to:
            try:
                limit_to = int(limit_to)
                emails = emails[:limit_to]
            except (ValueError, TypeError):
                pass
            
        # Hard cap: never exceed 500 in a single send call
        if len(emails) > 500:
            return jsonify({"error": "Cannot send to more than 500 recipients at once."}), 400
            
        is_admin = (session.get("role") == "Admin")
        
        # If it's a bulk send (> 1 recipient) and user is not Admin, route to Approval Queue
        if len(emails) > 1 and not is_admin:
            payload_after = {
                "subject": subject,
                "body_html": body_html,
                "recipients": emails
            }
            # Task 2 integration
            # We don't have a target_id because it's bulk
            create_approval_request(
                action_type="bulk_send",
                target_table="outbound_messages",
                target_id=None,
                payload_before=None,
                payload_after=payload_after
            )
            return jsonify({"success": True, "status": "Pending Approval", "message": f"Bulk send request for {len(emails)} recipients submitted for Admin approval."})
            
        # If single recipient and no approval needed, send immediately
        if len(emails) == 1:
            rcpt = emails[0]
            personalized_body = body_html.replace("{{candidate_name}}", rcpt["name"]).replace("{{employee_name}}", rcpt["name"])
            
            from utils.mailer import send_email, COMPANY_NAME, _wrap_html
            final_body = personalized_body.replace("{{company_name}}", COMPANY_NAME)
            
            wrapped_body = _wrap_html(
                title=subject,
                preheader=subject,
                body_html=final_body
            )
            
            # Send immediately
            success = send_email(rcpt["email"], subject, wrapped_body)
            status = 'Sent' if success else 'Failed'
            
            cur.execute("""
                INSERT INTO outbound_messages (subject, body_html, recipient_email, status, created_by, sent_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (subject, personalized_body, rcpt["email"], status, session.get("user"), datetime.utcnow() if success else None))
            conn.commit()
            
            if success:
                return jsonify({"success": True, "status": "Sent", "message": "Message sent immediately."})
            else:
                return jsonify({"error": "Failed to send email right now."}), 500
                
        # If it's a bulk send (> 1 recipient) and user is Admin, queue it directly
        for rcpt in emails:
            personalized_body = body_html.replace("{{candidate_name}}", rcpt["name"]).replace("{{employee_name}}", rcpt["name"])
            
            cur.execute("""
                INSERT INTO outbound_messages (subject, body_html, recipient_email, status, created_by)
                VALUES (%s, %s, %s, 'Queued', %s)
            """, (subject, personalized_body, rcpt["email"], session.get("user")))
        conn.commit()
        
        return jsonify({"success": True, "status": "Queued", "message": f"{len(emails)} messages queued for sending."})
        
    except Exception as e:
        print(f"Error in send_message: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: release_db(conn, cur)


@announcements_bp.route("/feed", methods=["GET"])
@login_required
def feed():
    email = session.get("email")
    conn, cur = None, None
    messages = []
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB Connection")
        cur.execute("""
            SELECT subject, body_html, sent_at, created_by
            FROM outbound_messages
            WHERE recipient_email = %s AND status = 'Sent'
            ORDER BY sent_at DESC
        """, (email,))
        messages = cur.fetchall()
        release_db(conn, cur)
    except Exception as e:
        print("Error fetching announcements feed via DB, trying REST fallback:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            messages = supabase_rest.get_rows("outbound_messages", {
                "recipient_email": f"eq.{email}",
                "status": "eq.Sent",
                "order": "sent_at.desc"
            })
        except Exception as rest_err:
            print("REST fallback for announcements feed failed:", rest_err)
            
    return render_template("hrms/announcements_feed.html", messages=messages)
