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
        if conn:
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
    except Exception as e:
        current_app.logger.warning(f"Database connection failed in candidate pipeline, using REST fallback: {e}")
    finally:
        if conn:
            release_db(conn, cur)

    # --- REST API FALLBACK ---
    try:
        from utils import supabase_rest
        raw_apps = supabase_rest.get_rows("applications", {"order": "applied_at.desc"}) or []
        jobs_map = {}
        for j in (supabase_rest.get_rows("jobs", {"select": "id,title"}) or []):
            jobs_map[str(j.get("id"))] = j.get("title")

        candidates = []
        for app in raw_apps:
            st = app.get("status")
            if st and st not in ["Pending", "Pending (Default)", ""]:
                app["job_title"] = jobs_map.get(str(app.get("job_id")), "")
                candidates.append(app)

        users = supabase_rest.get_rows("hrms_employees", {"status": "eq.Active", "select": "id,full_name"}) or []
        return render_template("hrms/candidates.html", candidates=candidates, users=users)
    except Exception as rest_err:
        current_app.logger.error(f"REST fallback failed for candidate pipeline: {rest_err}")
        flash("Database connection unavailable. Please check database configuration.", "error")
        return render_template("hrms/candidates.html", candidates=[], users=[])

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
            return jsonify({"exists": exists})
    except Exception as e:
        print("Error checking candidate email duplication via DB, trying REST fallback:", e)
    finally:
        if conn:
            release_db(conn, cur)

    # --- REST API FALLBACK ---
    try:
        from utils import supabase_rest
        apps = supabase_rest.get_rows("applications", {"email": f"ilike.{email}"})
        if apps:
            exists = True
        else:
            offers = supabase_rest.get_rows("employee_offers", {"candidate_email": f"ilike.{email}"})
            if offers:
                exists = True
    except Exception as rest_err:
        print("REST fallback for check_email failed:", rest_err)

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
        if conn:
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
            return redirect(url_for("candidates.pipeline"))
    except Exception as e:
        if conn:
            conn.rollback()
        current_app.logger.warning(f"Failed to add candidate via DB, attempting REST fallback: {e}")
    finally:
        if conn:
            release_db(conn, cur)

    # --- REST API FALLBACK ---
    try:
        from utils import supabase_rest
        payload = {
            "name": name,
            "email": email,
            "phone": phone,
            "status": status,
            "owner": owner,
            "notes": notes,
            "resume_url": resume_url
        }
        res = supabase_rest.insert_row("applications", payload)
        if res:
            flash("Candidate added to pipeline.", "success")
        else:
            flash("Failed to add candidate.", "error")
    except Exception as rest_err:
        current_app.logger.error(f"REST fallback for add candidate failed: {rest_err}")
        flash("Failed to add candidate.", "error")

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
        if conn:
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
        current_app.logger.warning(f"Failed to update status via DB, attempting REST fallback: {e}")
    finally:
        if conn:
            release_db(conn, cur)

    # --- REST API FALLBACK ---
    try:
        from utils import supabase_rest
        res = supabase_rest.update_rows("applications", {"id": f"eq.{application_id}"}, {"status": new_status})
        if res is not None:
            return jsonify({"success": True})
        return jsonify({"error": "Failed to update status"}), 500
    except Exception as rest_err:
        current_app.logger.error(f"REST fallback for update status failed: {rest_err}")
        return jsonify({"error": "Failed to update status"}), 500

@candidates_bp.route("/<uuid:application_id>/delete", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def delete_candidate(application_id):
    from hrms.approvals.routes import create_approval_request
    
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
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
        current_app.logger.warning(f"Failed to delete candidate via DB, attempting REST fallback: {e}")
    finally:
        if conn:
            release_db(conn, cur)

    # --- REST API FALLBACK ---
    try:
        from utils import supabase_rest
        rows = supabase_rest.get_rows("applications", {"id": f"eq.{application_id}"})
        if not rows:
            return jsonify({"error": "Candidate not found"}), 404
        row = rows[0]

        if session.get("role") == "Admin":
            supabase_rest.delete_rows("applications", {"id": f"eq.{application_id}"})
            create_approval_request(
                action_type="delete_candidate",
                target_table="applications",
                target_id=str(application_id),
                payload_before=row,
                payload_after=None,
                auto_approve=True
            )
            return jsonify({"success": True})
        else:
            create_approval_request(
                action_type="delete_candidate",
                target_table="applications",
                target_id=str(application_id),
                payload_before=row,
                payload_after=None
            )
            return jsonify({"success": True, "message": "Deletion submitted for Admin approval."})
    except Exception as rest_err:
        current_app.logger.error(f"REST fallback for delete candidate failed: {rest_err}")
        return jsonify({"error": "Failed to delete candidate"}), 500

@candidates_bp.route("/<uuid:application_id>/move-to-offer", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def move_to_offer(application_id):
    return redirect(url_for('offers.new_ui', application_id=application_id))

