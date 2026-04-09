print("APP.PY LOADED")

from flask import (
    Flask, flash, render_template, request,
    redirect, session, send_from_directory
)
import os
import tempfile
from datetime import datetime
import httpx
from dotenv import load_dotenv
import psycopg2
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import pandas as pd
from flask import send_file
from hrms.leave.routes import leave_bp
from utils.auth import login_required
from utils.db import get_db, release_db
from utils import supabase_rest
from hrms.attendance.routes import attendance_bp
from hrms.payroll.routes import payroll_bp
from hrms.salary.routes import salary_bp




# =========================
# HRMS BLUEPRINTS
# =========================
from hrms.employees.routes import employees_bp
from hrms.roles.routes import roles_bp

load_dotenv()

# =========================
# APP CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")
app.register_blueprint(attendance_bp)
app.register_blueprint(payroll_bp)
app.register_blueprint(salary_bp)
app.register_blueprint(leave_bp)

# Vercel runtime is read-only except for /tmp, so use /tmp there.
if os.getenv("VERCEL") == "1":
    UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), "uploads", "resumes")
else:
    UPLOAD_FOLDER = os.path.join(app.root_path, "uploads", "resumes")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SUPABASE_RESUME_BUCKET = os.getenv("SUPABASE_RESUME_BUCKET", "resumes")


def _supabase_headers(use_service=False):
    key = os.getenv("SERVICE_KEY") if use_service else os.getenv("SUPABASE_KEY")
    if not key:
        return None
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _supabase_rest_base_url():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    return f"{url}/rest/v1" if url else None


def _supabase_auth_base_url():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    return f"{url}/auth/v1" if url else None


def _fallback_login_via_supabase(email, password, role):
    """Fallback login when DATABASE_URL is missing/unreachable.
    Validates email/password with Supabase Auth and reads role from employees+roles.
    """
    auth_base = _supabase_auth_base_url()
    rest_base = _supabase_rest_base_url()
    anon_headers = _supabase_headers(use_service=False)
    service_headers = _supabase_headers(use_service=True)

    if not auth_base or not rest_base or not anon_headers or not service_headers:
        return None

    # 1) Validate password against Supabase Auth
    token_url = f"{auth_base}/token?grant_type=password"
    token_resp = httpx.post(
        token_url,
        headers=anon_headers,
        json={"email": email, "password": password},
        timeout=20.0,
    )
    if token_resp.status_code != 200:
        return None

    # 2) Fetch employee row by email
    emp_url = f"{rest_base}/employees"
    emp_resp = httpx.get(
        emp_url,
        headers=service_headers,
        params={"select": "id,first_name,last_name,email,role_id", "email": f"eq.{email}"},
        timeout=20.0,
    )
    if emp_resp.status_code != 200:
        return None
    employees = emp_resp.json() or []
    if not employees:
        return None

    emp = employees[0]
    role_id = emp.get("role_id")
    if not role_id:
        return None

    # 3) Resolve role name
    role_url = f"{rest_base}/roles"
    role_resp = httpx.get(
        role_url,
        headers=service_headers,
        params={"select": "name", "id": f"eq.{role_id}"},
        timeout=20.0,
    )
    if role_resp.status_code != 200:
        return None
    roles = role_resp.json() or []
    if not roles:
        return None

    role_name = str(roles[0].get("name") or "").strip()
    if role_name.lower() != role.lower():
        return {"error": "Unauthorized Role Access"}

    full_name = f"{(emp.get('first_name') or '').strip()} {(emp.get('last_name') or '').strip()}".strip()
    return {
        "id": emp.get("id"),
        "email": emp.get("email"),
        "employee_id": emp.get("id"),
        "role_name": role_name,
        "employee_name": full_name or None,
    }


def upload_resume_to_supabase(file_storage):
    """Upload resume file to Supabase Storage and return public URL."""
    if not file_storage or not file_storage.filename:
        return None

    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("Supabase credentials are missing")

    safe_name = secure_filename(file_storage.filename)
    timestamp = int(datetime.now().timestamp())
    object_key = f"applications/{timestamp}_{safe_name}"

    file_storage.stream.seek(0)
    file_bytes = file_storage.read()
    file_storage.stream.seek(0)

    content_type = file_storage.mimetype or "application/octet-stream"
    upload_url = f"{supabase_url}/storage/v1/object/{SUPABASE_RESUME_BUCKET}/{object_key}"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": content_type,
        "x-upsert": "false"
    }

    response = httpx.post(upload_url, content=file_bytes, headers=headers, timeout=30.0)
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Supabase upload failed with status {response.status_code}")

    return f"{supabase_url}/storage/v1/object/public/{SUPABASE_RESUME_BUCKET}/{object_key}"


# =========================
# REGISTER BLUEPRINTS
# =========================
app.register_blueprint(employees_bp)
app.register_blueprint(roles_bp)


# =========================
# =========================
# AUTHENTICATION
# =========================

@app.route("/")
def role_select():
    return render_template("role_select.html")



@app.route("/login/<role>", methods=["GET", "POST"])
def login(role):

    if request.method == "POST":

        email = request.form["email"].strip().lower()
        password = request.form["password"]

        # Primary login path (legacy schema): users + system_roles
        try:
            conn, cur = get_db(True)

            cur.execute("""
                SELECT u.id,
                       u.email,
                       u.employee_id,
                       u.password,
                       r.role_name
                FROM users u
                JOIN system_roles r
                  ON u.system_role_id = r.id
                WHERE u.email=%s
            """, (email,))

            user = cur.fetchone()

            if not user:
                release_db(conn, cur)
                flash("Invalid Email or Password", "error")
                return redirect(request.url)

            stored_password = user["password"] or ""
            password_ok = (
                check_password_hash(stored_password, password)
                if stored_password.startswith("pbkdf2:") or stored_password.startswith("scrypt:")
                else stored_password == password
            )

            if not password_ok:
                release_db(conn, cur)
                flash("Invalid Email or Password", "error")
                return redirect(request.url)

            if str(user["role_name"]).lower() != role.lower():
                release_db(conn, cur)
                flash("Unauthorized Role Access", "error")
                return redirect(request.url)

            # SESSION SETUP
            session.clear()
            session["user_id"] = user["id"]
            session["email"] = user["email"]
            session["employee_id"] = user["employee_id"]
            session["role"] = user["role_name"]

            if user["employee_id"]:
                cur.execute(
                    "SELECT full_name FROM hrms_employees WHERE id=%s",
                    (user["employee_id"],)
                )
                emp = cur.fetchone()
                if emp:
                    session["employee_name"] = emp["full_name"]

            release_db(conn, cur)
            flash("Login Successful", "success")
            return redirect("/dashboard")

        except psycopg2.OperationalError:
            # Fallback for projects using only Supabase REST/Auth + new schema
            fallback_user = _fallback_login_via_supabase(email, password, role)
            if not fallback_user:
                flash("Invalid Email or Password", "error")
                return redirect(request.url)
            if fallback_user.get("error"):
                flash(fallback_user["error"], "error")
                return redirect(request.url)

            session.clear()
            session["user_id"] = fallback_user["id"]
            session["email"] = fallback_user["email"]
            session["employee_id"] = fallback_user["employee_id"]
            session["role"] = fallback_user["role_name"]
            if fallback_user.get("employee_name"):
                session["employee_name"] = fallback_user["employee_name"]

            flash("Login Successful", "success")
            return redirect("/dashboard")

    return render_template("login.html", role=role)

        

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
@login_required
def dashboard():

    role = session.get("role")

    if role == "Employee":
        return render_template("employee_dashboard.html")

    total_jobs = 0
    total_applications = 0

    try:
        conn, cur = get_db(True)

        cur.execute("SELECT COUNT(*) AS total FROM jobs")
        total_jobs = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM applications")
        total_applications = cur.fetchone()["total"]

        release_db(conn, cur)
    except Exception:
        # Keep dashboard usable even when legacy tables are absent.
        total_jobs = 0
        total_applications = 0

    return render_template(
        "dashboard.html",
        total_jobs=total_jobs,
        total_applications=total_applications
    )

# =========================
# JOB MANAGEMENT
# =========================
@app.route("/jobs", methods=["GET", "POST"])
@login_required
def jobs():
    try:
        conn, cur = get_db(True)

        if request.method == "POST":
            cur.execute("""
                INSERT INTO jobs (title, description, location, job_type)
                VALUES (%s, %s, %s, %s)
            """, (
                request.form["title"],
                request.form["description"],
                request.form["location"],
                request.form["job_type"]
            ))
            conn.commit()

        cur.execute("SELECT * FROM jobs ORDER BY id DESC")
        jobs = cur.fetchall()

        release_db(conn, cur)
        return render_template("jobs.html", jobs=jobs)
    except Exception:
        # Without legacy jobs table, render an empty list instead of crashing.
        if request.method == "POST":
            flash("Jobs module is not configured in the new schema yet.", "error")
        return render_template("jobs.html", jobs=[])


@app.route("/delete-job/<int:job_id>")
@login_required
def delete_job(job_id):
    conn, cur = get_db()
    cur.execute("DELETE FROM jobs WHERE id=%s", (job_id,))
    conn.commit()
    release_db(conn, cur)
    return redirect("/jobs")


@app.route("/edit-job/<int:job_id>", methods=["GET", "POST"])
@login_required
def edit_job(job_id):
    conn, cur = get_db(True)

    if request.method == "POST":
        cur.execute("""
            UPDATE jobs
            SET title=%s, description=%s, location=%s, job_type=%s
            WHERE id=%s
        """, (
            request.form["title"],
            request.form["description"],
            request.form["location"],
            request.form["job_type"],
            job_id
        ))
        conn.commit()
        release_db(conn, cur)
        return redirect("/jobs")

    cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
    job = cur.fetchone()

    release_db(conn, cur)

    if not job:
        return "Job not found", 404

    return render_template("edit_job.html", job=job)


# =========================
# JOB APPLICATION
# =========================
@app.route("/apply/<int:job_id>", methods=["GET", "POST"])
def apply(job_id):
    conn, cur = get_db(True)

    cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
    job = cur.fetchone()

    if not job:
        release_db(conn, cur)
        return "Job not found", 404

    if request.method == "POST":
        resume = request.files.get("resume")
        resume_url = None

        if resume and resume.filename:
            try:
                resume_url = upload_resume_to_supabase(resume)
            except Exception:
                release_db(conn, cur)
                flash("Resume upload failed. Please try again in a moment.", "error")
                return redirect(request.url)

        cur.execute("""
            INSERT INTO applications
            (job_id, applicant_name, email, phone, resume_url)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            job_id,
            request.form["name"],
            request.form["email"],
            request.form["phone"],
            resume_url
        ))

        conn.commit()
        release_db(conn, cur)

        flash("Application submitted successfully!", "success")
        return redirect("/jobs")

    release_db(conn, cur)

    return render_template("apply.html", job=job)


# =========================
# RESUME SERVE
# =========================
@app.route("/uploads/resumes/<path:filename>")
def serve_resume(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# =========================
# APPLICATIONS & SETTINGS
# =========================
@app.route("/applications")
@login_required
def applications():

    selected_job = request.args.get("job_id")

    try:
        conn, cur = get_db(True)

        cur.execute("SELECT id, title FROM jobs ORDER BY id DESC")
        jobs = cur.fetchall()

        if selected_job:
            cur.execute("""
                SELECT
                    a.id,
                    j.title AS job_title,
                    a.applicant_name,
                    a.email,
                    a.phone,
                    a.resume_url
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                WHERE a.job_id = %s
                ORDER BY a.id DESC
            """, (selected_job,))
        else:
            cur.execute("""
                SELECT
                    a.id,
                    j.title AS job_title,
                    a.applicant_name,
                    a.email,
                    a.phone,
                    a.resume_url
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                ORDER BY a.id DESC
            """)

        applications = cur.fetchall()
        release_db(conn, cur)
    except Exception:
        jobs = []
        applications = []

    # Normalize stored resume URLs so legacy rows still resolve correctly.
    for row in applications:
        resume_url = row.get("resume_url")
        if not resume_url:
            continue

        normalized = str(resume_url).strip()
        if normalized.startswith("http://") or normalized.startswith("https://"):
            row["resume_url"] = normalized
        elif normalized.startswith("/uploads/resumes/"):
            row["resume_url"] = normalized
        elif normalized.startswith("uploads/resumes/"):
            row["resume_url"] = f"/{normalized}"
        else:
            row["resume_url"] = f"/uploads/resumes/{os.path.basename(normalized)}"

    return render_template(
        "applications.html",
        applications=applications,
        jobs=jobs,
        selected_job=selected_job
    )


@app.route("/applications/delete/<int:application_id>", methods=["POST"])
@login_required
def delete_application(application_id):
    conn, cur = get_db(True)

    cur.execute("SELECT id FROM applications WHERE id=%s", (application_id,))
    row = cur.fetchone()

    if not row:
        release_db(conn, cur)
        flash("Application not found", "error")
        return redirect("/applications")

    cur.execute("DELETE FROM applications WHERE id=%s", (application_id,))
    conn.commit()
    release_db(conn, cur)

    flash("Application deleted successfully", "success")

    selected_job = (request.form.get("job_id") or "").strip()
    if selected_job:
        return redirect(f"/applications?job_id={selected_job}")

    return redirect("/applications")


@app.route("/download-excel")
@login_required
def download_excel():

    selected_job = request.args.get("job_id")
    conn, cur = get_db()

    base_query = """
        SELECT
            j.title AS Job,
            a.applicant_name AS Applicant,
            a.email AS Email,
            a.phone AS Phone,
            a.resume_url AS Resume_URL
        FROM applications a
        JOIN jobs j ON a.job_id = j.id
    """

    if selected_job:
        query = base_query + " WHERE a.job_id = %s ORDER BY a.id DESC"
        df = pd.read_sql(query, conn, params=(selected_job,))
        file_path = f"applications_job_{selected_job}.xlsx"
    else:
        query = base_query + " ORDER BY a.id DESC"
        df = pd.read_sql(query, conn)
        file_path = "applications.xlsx"

    df.to_excel(file_path, index=False)
    release_db(conn, cur)

    return send_file(file_path, as_attachment=True)

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    message = None
    message_type = "success"
    
    if request.method == "POST":
        old_password = request.form.get("old_password", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        
        # Validation
        if not old_password or not new_password or not confirm_password:
            message = "All fields are required"
            message_type = "error"
        elif new_password != confirm_password:
            message = "New passwords do not match"
            message_type = "error"
        elif len(new_password) < 6:
            message = "Password must be at least 6 characters"
            message_type = "error"
        else:
            user_id = session.get("user_id")
            conn, cur = get_db(True)

            cur.execute("SELECT password, email FROM users WHERE id = %s", (user_id,))
            user = cur.fetchone()

            # Some legacy rows may store plain text; accept once and upgrade to hash.
            is_old_password_valid = False
            if user:
                stored_password = user["password"] or ""
                is_old_password_valid = (
                    check_password_hash(stored_password, old_password)
                    if stored_password.startswith("pbkdf2:") or stored_password.startswith("scrypt:")
                    else stored_password == old_password
                )

            if user and is_old_password_valid:
                # Password is correct, update it
                hashed_password = generate_password_hash(new_password)
                cur.execute(
                    "UPDATE users SET password = %s WHERE id = %s",
                    (hashed_password, user_id)
                )
                conn.commit()
                message = "Password updated successfully!"
                message_type = "success"
            else:
                message = "Old password is incorrect"
                message_type = "error"
            
            release_db(conn, cur)
    
    return render_template("settings.html", message=message, message_type=message_type)

@app.route("/salary-records")
@login_required
def salary_records():
    try:
        conn, cur = get_db(True)

        cur.execute("""
            SELECT es.id,
                   e.full_name AS employee_name,
                   CASE
                       WHEN es.monthly_salary IS NOT NULL
                           THEN CONCAT('Manual Salary (', es.monthly_salary, ')')
                       ELSE COALESCE(s.name, 'Not Assigned')
                   END AS structure_name,
                   es.effective_from::text AS effective_from
            FROM employee_salary es
            JOIN hrms_employees e ON es.employee_id = e.id
            LEFT JOIN salary_structures s ON es.structure_id = s.id
            ORDER BY es.effective_from DESC
        """)

        records = cur.fetchall()
        release_db(conn, cur)
    except Exception:
        records = supabase_rest.list_salary_records()

    return render_template("salary_records.html", records=records)

@app.route("/download-salary-records")
@login_required
def download_salary_records():

    conn, _ = get_db()

    query = """
        SELECT 
            e.full_name AS Employee,
            CASE
                WHEN es.monthly_salary IS NOT NULL
                    THEN CONCAT('Manual Salary (', es.monthly_salary, ')')
                ELSE COALESCE(s.name, 'Not Assigned')
            END AS Salary_Structure,
            es.effective_from::text AS Effective_From
        FROM employee_salary es
        JOIN hrms_employees e ON es.employee_id = e.id
        LEFT JOIN salary_structures s ON es.structure_id = s.id
        ORDER BY es.effective_from DESC
    """

    df = pd.read_sql(query, conn)

    file_path = "salary_records.xlsx"
    df.to_excel(file_path, index=False)

    return send_file(file_path, as_attachment=True)


# =========================
# RUN SERVER
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)