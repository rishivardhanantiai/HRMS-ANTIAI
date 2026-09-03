from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session, current_app, flash
from utils.db import get_db, release_db
from utils.auth import login_required, role_required
import psycopg2
from psycopg2.extras import DictCursor
import os
import uuid
import time
from utils.supabase_rest import upload_file_bytes

candidates_bp = Blueprint("candidates", __name__, url_prefix="/hrms/candidates")

@candidates_bp.route("/", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def pipeline():
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise psycopg2.OperationalError("Database connection failed")
            
        # We only want applications that have entered the ATS pipeline (not Pending)
        cur.execute("""
            SELECT a.*, j.title as job_title 
            FROM applications a
            LEFT JOIN jobs j ON a.job_id = j.id
            WHERE a.status IS NOT NULL 
              AND a.status != 'Pending'
              AND a.status != 'Pending (Default)'
              AND a.status != ''
            ORDER BY a.applied_at DESC
        """)
        candidates = cur.fetchall()
        
        cur.execute("SELECT id, full_name FROM hrms_employees WHERE status = 'Active'")
        users = cur.fetchall()
        
        return render_template("hrms/candidates.html", candidates=candidates, users=users)
    finally:
        if conn:
            release_db(conn, cur)

@candidates_bp.route("/check-email", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def check_email():
    email = request.args.get("email", "").strip().lower()
    if not email:
        return jsonify({"exists": False})
        
    conn, cur = None, None
    exists = False
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("SELECT id FROM applications WHERE LOWER(email) = %s", (email,))
            if cur.fetchone():
                exists = True
            else:
                cur.execute("SELECT id FROM employee_offers WHERE LOWER(candidate_email) = %s", (email,))
                if cur.fetchone():
                    exists = True
    except Exception as e:
        print("Error checking candidate email duplication:", e)
    finally:
        if conn:
            release_db(conn, cur)
            
    return jsonify({"exists": exists})


@candidates_bp.route("/add", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def add_candidate():
    name = request.form.get("name")
    email = request.form.get("email")
    phone = request.form.get("phone")
    status = request.form.get("status", "Screening")
    owner = request.form.get("owner")
    notes = request.form.get("notes")
    
    resume_file = request.files.get("resume")
    resume_url = None
    if resume_file and resume_file.filename:
        try:
            file_bytes = resume_file.read()
            ext = os.path.splitext(resume_file.filename)[1]
            object_key = f"resumes/{int(time.time())}_{uuid.uuid4().hex}{ext}"
            resume_url = upload_file_bytes(file_bytes, object_key)
        except Exception as e:
            current_app.logger.error(f"Failed to upload resume: {e}")
            flash("Failed to upload resume.", "error")
            return redirect(url_for("candidates.pipeline"))
            
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise psycopg2.OperationalError("Database connection failed")
            
        # Duplicate Check (non-blocking warning flash)
        is_duplicate = False
        if email:
            email_lower = email.strip().lower()
            cur.execute("SELECT id FROM applications WHERE LOWER(email) = %s", (email_lower,))
            if cur.fetchone():
                is_duplicate = True
            else:
                cur.execute("SELECT id FROM employee_offers WHERE LOWER(candidate_email) = %s", (email_lower,))
                if cur.fetchone():
                    is_duplicate = True
            
        cur.execute("""
            INSERT INTO applications (name, email, phone, status, owner, notes, resume_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (name, email, phone, status, owner, notes, resume_url))
        cand_id = cur.fetchone()["id"]
        conn.commit()
        
        from utils.audit import log_action
        log_action(session.get("email") or "HR", "candidate_added", "applications", cand_id, {"name": name, "email": email, "status": status})
        
        if is_duplicate:
            flash(f"Warning: A candidate or employee with email '{email}' already exists in applications or offers.", "warning")
        else:
            flash("Candidate added to pipeline.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        current_app.logger.error(f"Failed to add candidate: {e}")
        flash("Failed to add candidate.", "error")
    finally:
        if conn:
            release_db(conn, cur)
            
    return redirect(url_for("candidates.pipeline"))

@candidates_bp.route("/<uuid:application_id>/update-status", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def update_status(application_id):
    data = request.get_json() or {}
    new_status = data.get("status")
    
    if not new_status:
        return jsonify({"error": "Missing status"}), 400
        
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise psycopg2.OperationalError("Database connection failed")
            
        cur.execute("SELECT name, email, status FROM applications WHERE id = %s", (str(application_id),))
        cand = cur.fetchone()
        cur.execute("UPDATE applications SET status = %s WHERE id = %s", (new_status, str(application_id)))
        conn.commit()
        
        from utils.audit import log_action
        log_action(session.get("email") or "HR", "candidate_stage_updated", "applications", application_id, 
                   {"name": cand["name"] if cand else None, "email": cand["email"] if cand else None, 
                    "status_before": cand["status"] if cand else None, "status_after": new_status})
        
        return jsonify({"success": True})
    except Exception as e:
        if conn:
            conn.rollback()
        current_app.logger.error(f"Failed to update candidate status: {e}")
        return jsonify({"error": "Failed to update status"}), 500
    finally:
        if conn:
            release_db(conn, cur)

@candidates_bp.route("/<uuid:application_id>/delete", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def delete_candidate(application_id):
    from hrms.approvals.routes import create_approval_request
    
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise psycopg2.OperationalError("Database connection failed")
            
        cur.execute("SELECT * FROM applications WHERE id = %s", (str(application_id),))
        row = cur.fetchone()
        
        if not row:
            return jsonify({"error": "Candidate not found"}), 404
            
        if session.get("role") == "Admin":
            cur.execute("DELETE FROM applications WHERE id = %s", (str(application_id),))
            conn.commit()
            create_approval_request(
                action_type="delete_candidate",
                target_table="applications",
                target_id=str(application_id),
                payload_before=dict(row),
                payload_after=None,
                auto_approve=True
            )
            from utils.audit import log_action
            log_action(session.get("email") or "Admin", "candidate_deleted", "applications", application_id, dict(row) if row else {})
            return jsonify({"success": True})
        else:
            create_approval_request(
                action_type="delete_candidate",
                target_table="applications",
                target_id=str(application_id),
                payload_before=dict(row),
                payload_after=None
            )
            return jsonify({"success": True, "message": "Deletion submitted for Admin approval."})
            
    except Exception as e:
        if conn:
            conn.rollback()
        current_app.logger.error(f"Failed to process delete request: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            release_db(conn, cur)

@candidates_bp.route("/<uuid:application_id>/move-to-offer", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def move_to_offer(application_id):
    return redirect(url_for('offers.new_ui', application_id=application_id))
