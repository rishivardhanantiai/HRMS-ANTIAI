import os
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.security import generate_password_hash
from utils.auth import login_required, role_required
from utils.db import get_db, release_db
from utils.audit import log_action
from hrms.offers.routes import _get_company, _update_company_settings

admin_bp = Blueprint("admin", __name__, url_prefix="/hrms/admin")

@admin_bp.route("/users", methods=["GET"])
@login_required
@role_required(["Admin"])
def users_list():
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            flash("Database connection failed", "error")
            return redirect("/dashboard")
            
        # Fetch all roles
        cur.execute("SELECT id, role_name FROM hrms_roles")
        roles = cur.fetchall()
        
        # Fetch all active employees to connect them to logins (optional link)
        cur.execute("SELECT id, full_name, email FROM hrms_employees WHERE status = 'Active'")
        employees = cur.fetchall()
        
        # Fetch users with their role and employee name
        cur.execute("""
            SELECT u.id, u.email, u.role_id, u.employee_id, r.role_name, e.full_name AS employee_name
            FROM hrms_users u
            LEFT JOIN hrms_roles r ON u.role_id = r.id
            LEFT JOIN hrms_employees e ON u.employee_id = e.id
            ORDER BY u.email ASC
        """)
        users = cur.fetchall()
        
        return render_template("hrms/admin_users.html", users=users, roles=roles, employees=employees)
    except Exception as e:
        print(f"Error in users_list: {e}")
        flash("Failed to retrieve users.", "error")
        return redirect("/dashboard")
    finally:
        if conn:
            release_db(conn, cur)

@admin_bp.route("/users/add", methods=["POST"])
@login_required
@role_required(["Admin"])
def add_user():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    role_id = request.form.get("role_id")
    employee_id = request.form.get("employee_id") or None
    
    if not email or not password or not role_id:
        flash("Email, password, and role are required.", "error")
        return redirect(url_for("admin.users_list"))
        
    hashed = generate_password_hash(password)
    
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            # Check duplicate email
            cur.execute("SELECT id FROM hrms_users WHERE LOWER(email) = %s", (email,))
            if cur.fetchone():
                flash(f"User with email '{email}' already exists.", "error")
                return redirect(url_for("admin.users_list"))
                
            cur.execute("""
                INSERT INTO hrms_users (email, password, role_id, employee_id)
                VALUES (%s, %s, %s, %s) RETURNING id
            """, (email, hashed, role_id, employee_id))
            user_id = cur.fetchone()["id"]
            
            # Fetch role name for details
            cur.execute("SELECT role_name FROM hrms_roles WHERE id = %s", (role_id,))
            role_row = cur.fetchone()
            role_name = role_row["role_name"] if role_row else "Unknown"
            
            conn.commit()
            
            log_action(session.get("email") or "Admin", "user_created", "hrms_users", user_id, 
                       {"email": email, "role": role_name, "employee_id": employee_id})
                       
            flash(f"Successfully added user '{email}'.", "success")
    except Exception as e:
        print(f"Error in add_user: {e}")
        if conn: conn.rollback()
        flash("Failed to create user.", "error")
    finally:
        if conn:
            release_db(conn, cur)
            
    return redirect(url_for("admin.users_list"))

@admin_bp.route("/users/edit", methods=["POST"])
@login_required
@role_required(["Admin"])
def edit_user():
    user_id = request.form.get("user_id")
    role_id = request.form.get("role_id")
    employee_id = request.form.get("employee_id") or None
    password = request.form.get("password", "")
    
    if not user_id or not role_id:
        flash("User ID and role are required.", "error")
        return redirect(url_for("admin.users_list"))
        
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            # Fetch before state for details
            cur.execute("SELECT email, role_id, employee_id FROM hrms_users WHERE id = %s", (user_id,))
            before = cur.fetchone()
            if not before:
                flash("User not found.", "error")
                return redirect(url_for("admin.users_list"))
                
            fields = {"role_id": role_id, "employee_id": employee_id}
            details = {
                "email": before["email"],
                "role_before": before["role_id"],
                "role_after": role_id,
                "employee_before": before["employee_id"],
                "employee_after": employee_id
            }
            
            if password:
                fields["password"] = generate_password_hash(password)
                details["password_changed"] = True
                
            set_clause = ", ".join(f"{k}=%s" for k in fields)
            cur.execute(f"UPDATE hrms_users SET {set_clause} WHERE id=%s", list(fields.values()) + [user_id])
            conn.commit()
            
            log_action(session.get("email") or "Admin", "user_updated", "hrms_users", user_id, details)
            flash("User updated successfully.", "success")
    except Exception as e:
        print(f"Error in edit_user: {e}")
        if conn: conn.rollback()
        flash("Failed to update user.", "error")
    finally:
        if conn:
            release_db(conn, cur)
            
    return redirect(url_for("admin.users_list"))

@admin_bp.route("/users/delete/<user_id>", methods=["POST"])
@login_required
@role_required(["Admin"])
def delete_user(user_id):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            # Fetch user email for logs
            cur.execute("SELECT email FROM hrms_users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            if not user:
                return jsonify({"error": "User not found"}), 404
                
            email = user["email"]
            cur.execute("DELETE FROM hrms_users WHERE id = %s", (user_id,))
            conn.commit()
            
            log_action(session.get("email") or "Admin", "user_deleted", "hrms_users", user_id, {"email": email})
            return jsonify({"success": True, "message": f"Successfully deleted login for {email}"})
    except Exception as e:
        print(f"Error in delete_user: {e}")
        if conn: conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            release_db(conn, cur)
            
    return redirect(url_for("admin.users_list"))

@admin_bp.route("/settings", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def settings_page():
    company = _get_company()
    return render_template("hrms/admin_settings.html", company=company)

@admin_bp.route("/settings/save", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def save_settings():
    fields = {}
    for form_key, col in [
        ("company_name", "company_name"),
        ("company_address", "company_address"),
        ("company_contact", "company_contact"),
        ("company_email", "company_email"),
        ("company_website", "company_website"),
        ("watermark_opacity", "offer_watermark_opacity"),
        ("watermark_width_cm", "offer_watermark_width_cm"),
        ("logo_width_px", "offer_logo_width_px"),
        ("candidate_retention_months", "candidate_retention_months"),
    ]:
        val = request.form.get(form_key)
        if val is not None:
            if col in ("offer_watermark_opacity", "offer_watermark_width_cm", "offer_logo_width_px", "candidate_retention_months"):
                try:
                    if col == "candidate_retention_months":
                        fields[col] = int(val) if val else 12
                    else:
                        fields[col] = float(val) if val else None
                except ValueError: pass
            else:
                fields[col] = val.strip()

    logo_file = request.files.get("logo_file")
    if logo_file and logo_file.filename:
        import base64
        fields["offer_logo_wordmark_b64"] = base64.b64encode(logo_file.read()).decode()
        
    watermark_file = request.files.get("watermark_file")
    if watermark_file and watermark_file.filename:
        import base64
        fields["offer_watermark_b64"] = base64.b64encode(watermark_file.read()).decode()

    if not fields:
        flash("No fields to update.", "warning")
        return redirect(url_for("admin.settings_page"))

    from hrms.approvals.routes import create_approval_request
    
    current_company = _get_company()
    payload_before = dict(current_company) if current_company else {}
    
    # Clean datetime from payload_before because it's not JSON serializable directly
    for k, v in list(payload_before.items()):
        if isinstance(v, datetime):
            payload_before[k] = v.isoformat()

    if session.get("role") == "Admin":
        if not _update_company_settings(fields):
            flash("Failed to update company settings.", "error")
            return redirect(url_for("admin.settings_page"))
            
        create_approval_request("company_settings_change", "company_settings", None, payload_before, fields, auto_approve=True)
        
        log_action(session.get("email") or "Admin", "company_settings_updated", "company_settings", None, fields)
        flash("Company settings updated successfully.", "success")
    else:
        create_approval_request("company_settings_change", "company_settings", None, payload_before, fields)
        
        log_action(session.get("email") or "HR", "company_settings_change_proposed", "company_settings", None, fields)
        flash("Company settings updates submitted for Admin approval.", "success")
        
    return redirect(url_for("admin.settings_page"))

@admin_bp.route("/audit-logs", methods=["GET"])
@login_required
@role_required(["Admin"])
def audit_logs():
    page = request.args.get("page", 1, type=int)
    limit = 25
    offset = (page - 1) * limit
    
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            # Count total
            cur.execute("SELECT COUNT(*) FROM audit_log")
            total = cur.fetchone()["count"]
            
            # Fetch page
            cur.execute("""
                SELECT id, actor, action, target_table, target_id, details, created_at
                FROM audit_log
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))
            logs = cur.fetchall()
            
            total_pages = (total + limit - 1) // limit
            
            return render_template("hrms/admin_audit_logs.html", 
                                   logs=logs, 
                                   page=page, 
                                   total_pages=total_pages,
                                   total=total)
    except Exception as e:
        print(f"Error in audit_logs: {e}")
        flash("Failed to load audit logs.", "error")
    finally:
        if conn:
            release_db(conn, cur)
            
    return render_template("hrms/admin_audit_logs.html", logs=[], page=1, total_pages=1, total=0)


@admin_bp.route("/dashboards", methods=["GET"])
@login_required
@role_required(["Admin"])
def dashboards():
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            flash("Database connection failed", "error")
            return redirect("/dashboard")
            
        # 1. Quota & System Usage
        # Gmail daily sends
        cur.execute("SELECT COUNT(*) FROM outbound_messages WHERE status = 'Sent' AND sent_at >= CURRENT_DATE")
        emails_sent_today = cur.fetchone()["count"]
        email_quota_max = 500
        email_quota_pct = min(100.0, (emails_sent_today / email_quota_max) * 100.0)
        
        # Document Hub count of stored files
        cur.execute("SELECT COUNT(*) FROM employee_offers WHERE final_pdf_url IS NOT NULL")
        offers_pdf_count = cur.fetchone()["count"]
        
        cur.execute("SELECT COUNT(*) FROM employee_ndas WHERE final_pdf_url IS NOT NULL")
        ndas_pdf_count = cur.fetchone()["count"]
        
        # Check if table employee_policy_signatures exists first
        cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'employee_policy_signatures')")
        has_policies_table = cur.fetchone()["exists"]
        policies_pdf_count = 0
        if has_policies_table:
            cur.execute("SELECT COUNT(*) FROM employee_policy_signatures WHERE pdf_url IS NOT NULL")
            policies_pdf_count = cur.fetchone()["count"]
            
        total_docs_count = offers_pdf_count + ndas_pdf_count + policies_pdf_count
        
        # Database sizes (approx rows as storage proxy)
        cur.execute("SELECT SUM(n_live_tup) FROM pg_stat_user_tables")
        total_db_rows = cur.fetchone()["sum"] or 0
        
        # 2. Hiring Analytics
        # Total Candidates
        cur.execute("SELECT COUNT(*) FROM applications")
        total_candidates = cur.fetchone()["count"]
        
        # Funnel stage counts
        cur.execute("SELECT status, COUNT(*) FROM applications GROUP BY status")
        funnel_rows = cur.fetchall()
        funnel_stats = {r["status"]: r["count"] for r in funnel_rows}
        
        # Ensure all standard stages exist in mapping
        stages_list = [
            ("Screening", "Screening"),
            ("Interviewing", "Interviewing"),
            ("Selected", "Selected"),
            ("Backup", "Backup"),
            ("Future Reference", "Future Reference"),
            ("Rejected", "Rejected"),
            ("Pending", "Inbox / Pending")
        ]
        funnel_data = []
        for stage_val, stage_label in stages_list:
            # Aggregate status values
            count = 0
            for k, v in funnel_stats.items():
                if k == stage_val or (stage_val == "Pending" and "pending" in str(k).lower()):
                    count += v
            funnel_data.append({"label": stage_label, "count": count})
            
        # Offer Acceptance Rate
        cur.execute("SELECT status, COUNT(*) FROM employee_offers GROUP BY status")
        offer_rows = cur.fetchall()
        offer_stats = {r["status"]: r["count"] for r in offer_rows}
        
        extended = 0
        accepted = 0
        for k, v in offer_stats.items():
            if k in ("Sent", "Signed", "Countersigned"):
                extended += v
            if k in ("Signed", "Countersigned"):
                accepted += v
                
        acceptance_rate = 0.0
        if extended > 0:
            acceptance_rate = round((accepted / extended) * 100.0, 1)
            
        # Average Time-to-Hire
        cur.execute("""
            SELECT AVG(EXTRACT(EPOCH FROM (o.created_at - a.applied_at))/86400) AS avg_days 
            FROM employee_offers o 
            JOIN applications a ON o.application_id = a.id
        """)
        row = cur.fetchone()
        avg_days = row["avg_days"] if row and row["avg_days"] is not None else None
        
        if avg_days is None:
            cur.execute("""
                SELECT AVG(EXTRACT(EPOCH FROM (joining_date - created_at))/86400) AS avg_days 
                FROM hrms_employees 
                WHERE joining_date IS NOT NULL
            """)
            row = cur.fetchone()
            avg_days = row["avg_days"] if row and row["avg_days"] is not None else 14.5
            
        avg_time_to_hire = round(float(avg_days), 1)
        
        # Recent activity log (latest 5 audit records)
        cur.execute("""
            SELECT actor, action, created_at 
            FROM audit_log 
            ORDER BY created_at DESC 
            LIMIT 5
        """)
        recent_activities = cur.fetchall()
        
        return render_template("hrms/admin_dashboards.html",
                               emails_sent_today=emails_sent_today,
                               email_quota_max=email_quota_max,
                               email_quota_pct=email_quota_pct,
                               offers_pdf_count=offers_pdf_count,
                               ndas_pdf_count=ndas_pdf_count,
                               policies_pdf_count=policies_pdf_count,
                               total_docs_count=total_docs_count,
                               total_db_rows=total_db_rows,
                               total_candidates=total_candidates,
                               funnel_data=funnel_data,
                               extended_offers=extended,
                               accepted_offers=accepted,
                               acceptance_rate=acceptance_rate,
                               avg_time_to_hire=avg_time_to_hire,
                               recent_activities=recent_activities)
                               
    except Exception as e:
        print(f"Error loading dashboards: {e}")
        flash("Failed to retrieve dashboard metrics.", "error")
        return redirect("/dashboard")
    finally:
        if conn:
            release_db(conn, cur)


# =========================
# GOOGLE CALENDAR SYNC (TASK 6)
# =========================

@admin_bp.route("/calendar/setup", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def calendar_setup():
    user_email = session.get("email") or "hr@company.com"
    from utils.google_calendar import get_credentials
    creds = get_credentials(user_email)
    connected = creds is not None
    return render_template("hrms/admin_calendar.html", connected=connected, email=user_email)


@admin_bp.route("/calendar/auth", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def calendar_auth():
    from utils.google_calendar import get_oauth_flow
    try:
        redirect_uri = url_for("admin.calendar_oauth_callback", _external=True)
        if request.headers.get("X-Forwarded-Proto") == "https":
            redirect_uri = redirect_uri.replace("http://", "https://")
            
        flow = get_oauth_flow(redirect_uri=redirect_uri)
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            prompt='consent',
        )
        session['oauth_state'] = state
        
        # Save PKCE code_verifier if the library generated one (requests-oauthlib >= 1.3)
        try:
            cv = flow.oauth2session._client.code_verifier
            if cv:
                session['pkce_code_verifier'] = cv
                print(f"[CALENDAR AUTH] Saved PKCE code_verifier to session.")
        except AttributeError:
            pass
        
        return redirect(authorization_url)
    except Exception as e:
        print(f"Calendar auth initialization error: {e}")
        flash("Google Calendar client_secrets.json is missing or invalid. Please check configuration.", "error")
        return redirect(url_for("admin.calendar_setup"))


@admin_bp.route("/calendar/oauth2callback", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def calendar_oauth_callback():
    import traceback
    from utils.google_calendar import get_oauth_flow, save_credentials
    try:
        redirect_uri = url_for("admin.calendar_oauth_callback", _external=True)
        if request.headers.get("X-Forwarded-Proto") == "https":
            redirect_uri = redirect_uri.replace("http://", "https://")
        
        print(f"[CALENDAR CB] redirect_uri={redirect_uri}")
        print(f"[CALENDAR CB] request.url={request.url}")
        
        flow = get_oauth_flow(redirect_uri=redirect_uri)
        
        auth_response = request.url
        if redirect_uri.startswith("http://") and auth_response.startswith("https://"):
            auth_response = auth_response.replace("https://", "http://", 1)
        
        # Restore PKCE code_verifier if it was saved during the auth step
        code_verifier = session.pop('pkce_code_verifier', None)
        if code_verifier:
            print(f"[CALENDAR CB] Restoring PKCE code_verifier from session.")
            flow.oauth2session._client.code_verifier = code_verifier
        
        flow.fetch_token(authorization_response=auth_response)
            
        credentials = flow.credentials
        user_email = session.get("email") or "hr@company.com"
        save_credentials(user_email, credentials)
        
        from utils.audit import log_action
        log_action(user_email, "connect_calendar", details={"message": "Google Calendar OAuth connected successfully."})
        
        flash("Google Calendar connected successfully!", "success")
        return redirect(url_for("admin.calendar_setup"))
    except Exception as e:
        print(f"[CALENDAR CB] FULL ERROR: {traceback.format_exc()}")
        flash(f"Failed to authenticate with Google: {str(e)}", "error")
        return redirect(url_for("admin.calendar_setup"))


@admin_bp.route("/calendar/disconnect", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def calendar_disconnect():
    user_email = session.get("email") or "hr@company.com"
    from utils.google_calendar import delete_credentials
    delete_credentials(user_email)
    
    from utils.audit import log_action
    log_action(user_email, "disconnect_calendar", details={"message": "Google Calendar disconnected by user."})
    
    flash("Google Calendar disconnected successfully.", "success")
    return redirect(url_for("admin.calendar_setup"))
