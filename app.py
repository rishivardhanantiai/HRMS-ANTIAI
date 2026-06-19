print("APP.PY LOADED")

from flask import (
    Flask, flash, render_template, request,
    redirect, session, send_from_directory
)
import csv
from io import BytesIO
from io import StringIO
import os
import tempfile
from datetime import datetime, date
import httpx
from dotenv import load_dotenv
import psycopg2
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import pandas as pd
from flask import send_file
from hrms.leave.routes import leave_bp
from utils.auth import login_required
from utils.auth import role_required
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
from hrms.performance.routes import performance_bp
from hrms.exit.routes import exit_bp
from hrms.letters.routes import letters_bp

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
app.register_blueprint(performance_bp)
app.register_blueprint(employees_bp)
app.register_blueprint(roles_bp)
app.register_blueprint(exit_bp)
app.register_blueprint(letters_bp)

# Vercel runtime is read-only except for /tmp, so use /tmp there.
if os.getenv("VERCEL") == "1":
    UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), "uploads", "resumes")
else:
    UPLOAD_FOLDER = os.path.join(app.root_path, "uploads", "resumes")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SUPABASE_RESUME_BUCKET = os.getenv("SUPABASE_RESUME_BUCKET", "resumes")

# Startup Bucket Check
def verify_supabase_bucket():
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_key = os.getenv("SUPABASE_KEY")
    if supabase_url and supabase_key:
        import httpx
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}"
        }
        try:
            # First try listing buckets to see if it's there and public
            r = httpx.get(f"{supabase_url}/storage/v1/bucket", headers=headers, timeout=5.0)
            if r.status_code == 200:
                buckets = [b["name"] for b in r.json()]
                if SUPABASE_RESUME_BUCKET not in buckets:
                    print(f"\nWARNING: Supabase bucket '{SUPABASE_RESUME_BUCKET}' not found or not public. Document uploads/views may fail!\n")
        except Exception as e:
            print(f"\nWARNING: Could not verify Supabase bucket: {e}\n")

verify_supabase_bucket()


def _send_excel_dataframe(df, filename):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


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

    # If Auth user is missing/out-of-sync, allow login using hrms_users password hash.
    if token_resp.status_code != 200:
        users_url = f"{rest_base}/hrms_users"
        user_resp = httpx.get(
            users_url,
            headers=service_headers,
            params={"select": "id,email,password", "email": f"eq.{email}", "limit": "1"},
            timeout=20.0,
        )
        if user_resp.status_code != 200:
            return None
        user_rows = user_resp.json() or []
        if not user_rows:
            return None

        stored_password = str(user_rows[0].get("password") or "")
        password_ok = (
            check_password_hash(stored_password, password)
            if stored_password.startswith("pbkdf2:") or stored_password.startswith("scrypt:")
            else stored_password == password
        )
        if not password_ok:
            return None

    # 2) Fetch employee row by email
    emp_url = f"{rest_base}/hrms_employees"
    emp_resp = httpx.get(
        emp_url,
        headers=service_headers,
        params={"select": "id,full_name,email,role_id", "email": f"eq.{email}"},
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
    role_url = f"{rest_base}/hrms_roles"
    role_resp = httpx.get(
        role_url,
        headers=service_headers,
        params={"select": "role_name", "id": f"eq.{role_id}"},
        timeout=20.0,
    )
    if role_resp.status_code != 200:
        return None
    roles = role_resp.json() or []
    if not roles:
        return None

    role_name = str(roles[0].get("role_name") or "").strip()
    if role_name.lower() != role.lower():
        return {"error": "Unauthorized Role Access"}

    full_name = str(emp.get("full_name") or "").strip()
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

                # Primary login path: HRMS users + roles
        try:
            conn, cur = get_db(True)

            cur.execute("""
                SELECT u.id,
                       u.email,
                       u.employee_id,
                       u.password,
                       r.role_name
                                FROM hrms_users u
                                JOIN hrms_roles r
                                    ON u.role_id = r.id
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
        emp_id = session.get("employee_id")
        letters = []
        today_attendance = None
        leave_summary = {"pending": 0, "approved": 0, "rejected": 0, "recent": []}
        doc_summary = {"verified": 0, "pending": 0, "rejected": 0, "recent": []}
        eval_summary = {"latest_score": None, "latest_grade": None, "total": 0}
        
        if emp_id:
            conn, cur = None, None
            try:
                conn, cur = get_db(True)
                
                # Letters
                cur.execute("SELECT * FROM generated_letters WHERE employee_id = %s ORDER BY generated_at DESC", (emp_id,))
                letters = cur.fetchall()
                
                # Today's attendance
                cur.execute("""
                    SELECT status, check_in_time, check_out_time, duration 
                    FROM hrms_attendance 
                    WHERE employee_id = %s AND attendance_date = CURRENT_DATE
                """, (emp_id,))
                today_attendance = cur.fetchone()
                
                # Leave requests summary
                cur.execute("""
                    SELECT status, COUNT(*) as count 
                    FROM leave_applications 
                    WHERE employee_id = %s 
                    GROUP BY status
                """, (emp_id,))
                for row in cur.fetchall():
                    status_lower = row["status"].lower()
                    if "pending" in status_lower:
                        leave_summary["pending"] = row["count"]
                    elif "approved" in status_lower:
                        leave_summary["approved"] = row["count"]
                    elif "rejected" in status_lower:
                        leave_summary["rejected"] = row["count"]
                
                # Recent leave applications
                cur.execute("""
                    SELECT la.from_date, la.to_date, la.status, lt.name as leave_type 
                    FROM leave_applications la
                    JOIN leave_types lt ON la.leave_type_id = lt.id
                    WHERE la.employee_id = %s 
                    ORDER BY la.from_date DESC LIMIT 3
                """, (emp_id,))
                leave_summary["recent"] = cur.fetchall()

                # Document summary
                cur.execute("""
                    SELECT verification_status, COUNT(*) as count 
                    FROM employee_documents 
                    WHERE employee_id = %s 
                    GROUP BY verification_status
                """, (emp_id,))
                for row in cur.fetchall():
                    status_lower = row["verification_status"].lower()
                    if "pending" in status_lower:
                        doc_summary["pending"] = row["count"]
                    elif "verified" in status_lower:
                        doc_summary["verified"] = row["count"]
                    elif "rejected" in status_lower:
                        doc_summary["rejected"] = row["count"]

                # Recent documents
                cur.execute("""
                    SELECT document_title, document_type, verification_status 
                    FROM employee_documents 
                    WHERE employee_id = %s 
                    ORDER BY created_at DESC LIMIT 3
                """, (emp_id,))
                doc_summary["recent"] = cur.fetchall()

                # Performance summary
                cur.execute("""
                    SELECT final_score, grade, evaluation_date 
                    FROM performance_evaluations 
                    WHERE employee_id = %s AND status = 'Completed' 
                    ORDER BY evaluation_date DESC LIMIT 1
                """, (emp_id,))
                latest_eval = cur.fetchone()
                if latest_eval:
                    eval_summary["latest_score"] = latest_eval["final_score"]
                    eval_summary["latest_grade"] = latest_eval["grade"]

                cur.execute("SELECT COUNT(*) as total FROM performance_evaluations WHERE employee_id = %s", (emp_id,))
                eval_summary["total"] = cur.fetchone()["total"]

            except Exception as e:
                print("Error fetching employee dashboard stats:", e)
            finally:
                if conn: release_db(conn, cur)

        return render_template(
            "employee_dashboard.html",
            letters=letters,
            today_attendance=today_attendance,
            leave_summary=leave_summary,
            doc_summary=doc_summary,
            eval_summary=eval_summary
        )

    total_jobs = 0
    total_applications = 0
    total_employees = 0
    pending_leaves = 0
    pending_docs = 0
    perf_metrics = {
        "upcoming": [],
        "due_today": [],
        "overdue": [],
        "evaluated_this_month": 0,
        "pending_this_month": 0,
        "avg_company_score": 0,
        "top_performers": [],
        "bottom_performers": []
    }
    
    notifications = []
    conn, cur = None, None

    try:
        conn, cur = get_db(True)

        cur.execute("SELECT COUNT(*) AS total FROM jobs")
        total_jobs = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM applications")
        total_applications = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM hrms_employees WHERE status = 'Active'")
        total_employees = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM leave_applications WHERE status = 'Pending'")
        pending_leaves = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM employee_documents WHERE verification_status = 'Pending'")
        pending_docs = cur.fetchone()["total"]

        # Calculate Performance Analytics
        today = date.today()
        current_month = today.month
        current_year = today.year

        # Get all active employees with their join dates
        cur.execute("""
            SELECT id, full_name, joining_date, department 
            FROM hrms_employees 
            WHERE status = 'Active' AND joining_date IS NOT NULL
        """)
        active_employees = cur.fetchall()

        # Get evaluations for this month
        cur.execute("""
            SELECT employee_id, final_score, grade 
            FROM performance_evaluations 
            WHERE evaluation_month = %s AND evaluation_year = %s
        """, (current_month, current_year))
        evals_this_month = {row["employee_id"]: row for row in cur.fetchall()}

        perf_metrics["evaluated_this_month"] = len(evals_this_month)
        
        for emp in active_employees:
            jd = emp["joining_date"]
            if jd.year == current_year and jd.month == current_month:
                continue # Skip new joinees this month

            # The due date is the same day of the current month
            # (Simplification: if joining date is 31st and current month has 30 days, assume 30th)
            due_day = jd.day
            # Handle month end cases
            import calendar
            last_day = calendar.monthrange(current_year, current_month)[1]
            if due_day > last_day:
                due_day = last_day
                
            try:
                due_date = date(current_year, current_month, due_day)
            except ValueError:
                due_date = today

            days_diff = (due_date - today).days

            if emp["id"] not in evals_this_month:
                perf_metrics["pending_this_month"] += 1
                
                emp_data = {"id": emp["id"], "name": emp["full_name"], "due_date": due_date.strftime("%d %b %Y")}
                
                if days_diff > 0 and days_diff <= 7:
                    emp_data["days_left"] = days_diff
                    perf_metrics["upcoming"].append(emp_data)
                    notifications.append({
                        "type": "Performance",
                        "title": "Evaluation Upcoming",
                        "message": f"Evaluation for {emp['full_name']} is due in {days_diff} days.",
                        "date": due_date.strftime("%d %b %Y"),
                        "color": "blue",
                        "link": f"/hrms/performance/start/{emp['id']}"
                    })
                elif days_diff == 0:
                    perf_metrics["due_today"].append(emp_data)
                    notifications.append({
                        "type": "Performance",
                        "title": "Evaluation Due Today",
                        "message": f"Evaluation for {emp['full_name']} is due today.",
                        "date": today.strftime("%d %b %Y"),
                        "color": "yellow",
                        "link": f"/hrms/performance/start/{emp['id']}"
                    })
                elif days_diff < 0:
                    emp_data["days_overdue"] = abs(days_diff)
                    emp_data["escalation"] = "Admin" if abs(days_diff) >= 15 else ("HR Manager" if abs(days_diff) >= 7 else "HR")
                    perf_metrics["overdue"].append(emp_data)
                    notifications.append({
                        "type": "Performance",
                        "title": "Evaluation Overdue",
                        "message": f"Evaluation for {emp['full_name']} is {abs(days_diff)} days overdue. (Escalation: {emp_data['escalation']})",
                        "date": today.strftime("%d %b %Y"),
                        "color": "red",
                        "link": f"/hrms/performance/start/{emp['id']}"
                    })

        # Company Avg Score
        cur.execute("SELECT AVG(final_score) as avg_score FROM performance_evaluations")
        avg_res = cur.fetchone()
        perf_metrics["avg_company_score"] = round(avg_res["avg_score"] or 0, 1)

        # Top 5 and Bottom 5 (Latest evaluations)
        cur.execute("""
            SELECT e.full_name, p.final_score 
            FROM performance_evaluations p
            JOIN hrms_employees e ON p.employee_id = e.id
            WHERE p.status IN ('Completed', 'Reviewed', 'Acknowledged')
            ORDER BY p.final_score DESC LIMIT 5
        """)
        perf_metrics["top_performers"] = cur.fetchall()

        cur.execute("""
            SELECT e.full_name, p.final_score 
            FROM performance_evaluations p
            JOIN hrms_employees e ON p.employee_id = e.id
            WHERE p.status IN ('Completed', 'Reviewed', 'Acknowledged')
            ORDER BY p.final_score ASC LIMIT 5
        """)
        perf_metrics["bottom_performers"] = cur.fetchall()

    except Exception as e:
        print("Error fetching dashboard metrics:", e)
    finally:
        if conn:
            release_db(conn, cur)

    return render_template(
        "dashboard.html",
        total_jobs=total_jobs,
        total_applications=total_applications,
        total_employees=total_employees,
        pending_leaves=pending_leaves,
        pending_docs=pending_docs,
        perf_metrics=perf_metrics,
        notifications=notifications
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
                INSERT INTO jobs (title, description, location, department)
                VALUES (%s, %s, %s, %s)
            """, (
                request.form["title"],
                request.form["description"],
                request.form["location"],
                request.form.get("department", "").strip() or None
            ))
            conn.commit()

        cur.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        jobs = cur.fetchall()

        release_db(conn, cur)
        return render_template("jobs.html", jobs=jobs)
    except Exception:
        if request.method == "POST":
            created = supabase_rest.insert_row(
                "jobs",
                {
                    "title": request.form.get("title"),
                    "description": request.form.get("description"),
                    "location": request.form.get("location"),
                    "department": request.form.get("department", "").strip() or None,
                },
            )
            if not created:
                flash("Could not create job. Please try again.", "error")

        jobs = supabase_rest.get_rows(
            "jobs",
            {
                "select": "id,title,description,location,department,created_at",
                "order": "created_at.desc",
            },
        )
        return render_template("jobs.html", jobs=jobs)


@app.route("/delete-job/<job_id>")
@login_required
def delete_job(job_id):
    try:
        conn, cur = get_db()
        cur.execute("DELETE FROM jobs WHERE id=%s", (job_id,))
        conn.commit()
        release_db(conn, cur)
    except Exception:
        supabase_rest.delete_rows("jobs", {"id": f"eq.{job_id}"})
    return redirect("/jobs")


@app.route("/edit-job/<job_id>", methods=["GET", "POST"])
@login_required
def edit_job(job_id):
    try:
        conn, cur = get_db(True)

        if request.method == "POST":
            cur.execute("""
                UPDATE jobs
                SET title=%s, description=%s, location=%s, department=%s
                WHERE id=%s
            """, (
                request.form["title"],
                request.form["description"],
                request.form["location"],
                request.form.get("department", "").strip() or None,
                job_id
            ))
            conn.commit()
            release_db(conn, cur)
            return redirect("/jobs")

        cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
        job = cur.fetchone()

        release_db(conn, cur)
    except Exception:
        if request.method == "POST":
            rows = supabase_rest.update_rows(
                "jobs",
                {"id": f"eq.{job_id}"},
                {
                    "title": request.form.get("title"),
                    "description": request.form.get("description"),
                    "location": request.form.get("location"),
                    "department": request.form.get("department", "").strip() or None,
                },
            )
            if not rows:
                flash("Could not update job.", "error")
            return redirect("/jobs")

        job = supabase_rest.get_first_row(
            "jobs",
            {"select": "id,title,description,location,department,created_at", "id": f"eq.{job_id}"},
        )

    if not job:
        return "Job not found", 404

    return render_template("edit_job.html", job=job)


# =========================
# JOB APPLICATION
# =========================
@app.route("/apply/<job_id>", methods=["GET", "POST"])
def apply(job_id):
    job = None
    try:
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
                (job_id, name, email, phone, resume_url)
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
    except Exception:
        job = supabase_rest.get_first_row(
            "jobs",
            {"select": "id,title,description,location,department,created_at", "id": f"eq.{job_id}"},
        )
        if not job:
            return "Job not found", 404

        if request.method == "POST":
            resume = request.files.get("resume")
            resume_url = None
            if resume and resume.filename:
                try:
                    resume_url = upload_resume_to_supabase(resume)
                except Exception:
                    flash("Resume upload failed. Please try again in a moment.", "error")
                    return redirect(request.url)

            created = supabase_rest.insert_row(
                "applications",
                {
                    "job_id": job_id,
                    "name": request.form.get("name"),
                    "email": request.form.get("email"),
                    "phone": request.form.get("phone"),
                    "resume_url": resume_url,
                },
            )
            if not created:
                flash("Could not submit application. Please try again.", "error")
                return redirect(request.url)

            flash("Application submitted successfully!", "success")
            return redirect("/jobs")

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
@role_required(["HR", "Admin"])
def applications():

    selected_job = request.args.get("job_id")

    try:
        conn, cur = get_db(True)

        cur.execute("SELECT id, title FROM jobs ORDER BY created_at DESC")
        jobs = cur.fetchall()

        if selected_job:
            cur.execute("""
                SELECT
                    a.id,
                    j.title AS job_title,
                    a.applied_at,
                    a.applicant_name,
                    a.email,
                    a.phone,
                    a.resume_url,
                    a.cover_letter,
                    a.status
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
                    a.applied_at,
                    a.applicant_name,
                    a.email,
                    a.phone,
                    a.resume_url,
                    a.cover_letter,
                    a.status
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                ORDER BY a.id DESC
            """)

        applications = cur.fetchall()
        release_db(conn, cur)
    except Exception:
        jobs = supabase_rest.get_rows(
            "jobs",
            {"select": "id,title", "order": "created_at.desc"},
        )
        selected_filter = {"select": "id,job_id,applicant_name,email,phone,resume_url,applied_at,cover_letter,status", "order": "created_at.desc"}
        if selected_job:
            selected_filter["job_id"] = f"eq.{selected_job}"
        app_rows = supabase_rest.get_rows("applications", selected_filter)
        job_lookup = {str(j.get("id")): j.get("title") for j in jobs}
        applications = [
            {
                "id": a.get("id"),
                "job_title": job_lookup.get(str(a.get("job_id")), "-"),
                "applicant_name": a.get("applicant_name"),
                "applied_at": a.get("applied_at"),
                "email": a.get("email"),
                "phone": a.get("phone"),
                "resume_url": a.get("resume_url"),
                "cover_letter": a.get("cover_letter"),
                "status": a.get("status")
            }
            for a in app_rows
        ]

        if selected_job:
            cur.execute("""
                SELECT
                    a.id,
                    j.title AS job_title,
                    a.name AS applicant_name,
                    a.email,
                    a.phone,
                    a.resume_url
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                WHERE a.job_id = %s
                ORDER BY a.created_at DESC
            """, (selected_job,))
        else:
            cur.execute("""
                SELECT
                    a.id,
                    j.title AS job_title,
                    a.name AS applicant_name,
                    a.email,
                    a.phone,
                    a.resume_url
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                ORDER BY a.created_at DESC
            """)

        applications = cur.fetchall()
        release_db(conn, cur)
    except Exception:
        jobs = supabase_rest.get_rows(
            "jobs",
            {"select": "id,title", "order": "created_at.desc"},
        )
        selected_filter = {"select": "id,job_id,name,email,phone,resume_url,created_at", "order": "created_at.desc"}
        if selected_job:
            selected_filter["job_id"] = f"eq.{selected_job}"
        app_rows = supabase_rest.get_rows("applications", selected_filter)
        job_lookup = {str(j.get("id")): j.get("title") for j in jobs}
        applications = [
            {
                "id": a.get("id"),
                "job_title": job_lookup.get(str(a.get("job_id")), "-"),
                "applicant_name": a.get("name"),
                "email": a.get("email"),
                "phone": a.get("phone"),
                "resume_url": a.get("resume_url"),
            }
            for a in app_rows
        ]

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


@app.route("/applications/import-csv", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def import_applications_csv():
    selected_job = (request.form.get("job_id") or request.args.get("job_id") or "").strip()
    csv_file = request.files.get("csv_file")

    if not csv_file or not csv_file.filename:
        flash("Please choose a CSV file to upload.", "error")
        return redirect(f"/applications?job_id={selected_job}" if selected_job else "/applications")

    raw_content = csv_file.read().decode("utf-8-sig")
    reader = csv.DictReader(StringIO(raw_content))

    if not reader.fieldnames:
        flash("The uploaded CSV file has no headers.", "error")
        return redirect(f"/applications?job_id={selected_job}" if selected_job else "/applications")

    rows = list(reader)

    def parse_row(row):
        name = (row.get("name") or row.get("applicant_name") or row.get("full_name") or "").strip()
        email = (row.get("email") or "").strip()
        phone = (row.get("phone") or "").strip() or None
        resume_url = (row.get("resume_url") or row.get("resume") or "").strip() or None
        cover_letter = (row.get("cover_letter") or "").strip() or None
        row_job_id = (
            row.get("job_id")
            or row.get("job")
            or row.get("job_title")
            or selected_job
            or ""
        ).strip()
        return name, email, phone, resume_url, cover_letter, row_job_id

    conn = None
    cur = None

    try:
        conn, cur = get_db(True)
        cur.execute("SELECT id, title FROM jobs ORDER BY created_at DESC")
        jobs = cur.fetchall()
        job_lookup_by_id = {str(job.get("id")): job.get("id") for job in jobs}
        job_lookup_by_title = {str(job.get("title") or "").strip().lower(): job.get("id") for job in jobs}

        inserted = 0
        skipped = 0

        for row in rows:
            name, email, phone, resume_url, cover_letter, row_job_id = parse_row(row)

            resolved_job_id = job_lookup_by_id.get(row_job_id)
            if not resolved_job_id and row_job_id:
                resolved_job_id = job_lookup_by_title.get(row_job_id.lower())

            if not name or not email or not resolved_job_id:
                skipped += 1
                continue

            cur.execute(
                """
                INSERT INTO applications (job_id, name, email, phone, resume_url, cover_letter)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (resolved_job_id, name, email, phone, resume_url, cover_letter),
            )
            inserted += 1

        conn.commit()

        if inserted:
            flash(f"Imported {inserted} applicant(s) from CSV.", "success")
        if skipped:
            flash(f"Skipped {skipped} row(s) because they were missing a job, name, or email.", "error")
    except Exception:
        try:
            jobs = supabase_rest.get_rows("jobs", {"select": "id,title", "order": "created_at.desc"})
            job_lookup_by_id = {str(job.get("id")): job.get("id") for job in jobs}
            job_lookup_by_title = {str(job.get("title") or "").strip().lower(): job.get("id") for job in jobs}
            inserted = 0
            skipped = 0

            for row in rows:
                name, email, phone, resume_url, cover_letter, row_job_id = parse_row(row)

                resolved_job_id = job_lookup_by_id.get(row_job_id)
                if not resolved_job_id and row_job_id:
                    resolved_job_id = job_lookup_by_title.get(row_job_id.lower())

                if not name or not email or not resolved_job_id:
                    skipped += 1
                    continue

                created = supabase_rest.insert_row(
                    "applications",
                    {
                        "job_id": resolved_job_id,
                        "name": name,
                        "email": email,
                        "phone": phone,
                        "resume_url": resume_url,
                        "cover_letter": cover_letter,
                    },
                )
                if created:
                    inserted += 1
                else:
                    skipped += 1

            if inserted:
                flash(f"Imported {inserted} applicant(s) from CSV.", "success")
            if skipped:
                flash(f"Skipped {skipped} row(s) because they were missing a job, name, or email.", "error")
        except Exception:
            flash("CSV import failed. Please check the file format and try again.", "error")
    finally:
        if conn and cur:
            release_db(conn, cur)

    return redirect(f"/applications?job_id={selected_job}" if selected_job else "/applications")


@app.route("/applications/csv-template")
@login_required
@role_required(["HR", "Admin"])
def download_applications_csv_template():
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["job_id", "job_title", "name", "email", "phone", "resume_url", "cover_letter"])
    output.seek(0)
    return send_file(
        BytesIO(output.getvalue().encode("utf-8")),
        as_attachment=True,
        download_name="applications_template.csv",
        mimetype="text/csv",
    )


@app.route("/applications/delete/<application_id>", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def delete_application(application_id):
    try:
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
    except Exception:
        row = supabase_rest.get_first_row("applications", {"select": "id", "id": f"eq.{application_id}"})
        if not row:
            flash("Application not found", "error")
            return redirect("/applications")
        supabase_rest.delete_rows("applications", {"id": f"eq.{application_id}"})

    flash("Application deleted successfully", "success")

    selected_job = (request.form.get("job_id") or "").strip()
    if selected_job:
        return redirect(f"/applications?job_id={selected_job}")

    return redirect("/applications")


@app.route("/applications/update-status/<int:application_id>", methods=["POST"])
@login_required
def update_application_status(application_id):
    data = request.get_json() or {}
    status = data.get("status")
    
    valid_statuses = ["Selected", "Rejected", "Backup", "Future Reference", "Pending", "Pending (Default)", ""]
    if status not in valid_statuses:
        return {"error": "Invalid status value"}, 400
        
    conn, cur = get_db(True)
    cur.execute("SELECT id FROM applications WHERE id=%s", (application_id,))
    row = cur.fetchone()
    
    if not row:
        release_db(conn, cur)
        return {"error": "Application not found"}, 404
        
    cur.execute(
        "UPDATE applications SET status = %s WHERE id = %s",
        (status, application_id)
    )
    conn.commit()
    release_db(conn, cur)
    
    return {"message": "Status updated successfully"}, 200


@app.route("/download-excel")
@login_required
@role_required(["HR", "Admin"])
def download_excel():

    selected_job = request.args.get("job_id")
    conn = None
    cur = None
    try:
        conn, cur = get_db()

        base_query = """
            SELECT
                j.title AS Job,
                a.applied_at AS Applied_At,
                a.applicant_name AS Applicant,
                a.email AS Email,
                a.phone AS Phone,
                a.resume_url AS Resume_URL,
                a.cover_letter AS Cover_Letter,
                a.status AS Status
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
        """

        if selected_job:
            query = base_query + " WHERE a.job_id = %s ORDER BY a.created_at DESC"
            df = pd.read_sql(query, conn, params=(selected_job,))
            filename = f"applications_job_{selected_job}.xlsx"
        else:
            query = base_query + " ORDER BY a.created_at DESC"
            df = pd.read_sql(query, conn)
            filename = "applications.xlsx"

    except Exception:
        jobs = supabase_rest.get_rows("jobs", {"select": "id,title"})
        apps_filter = {"select": "id,job_id,name,email,phone,resume_url,created_at", "order": "created_at.desc"}
        if selected_job:
            apps_filter["job_id"] = f"eq.{selected_job}"
        apps = supabase_rest.get_rows("applications", apps_filter)
        job_lookup = {str(j.get("id")): j.get("title") for j in jobs}
        records = [
            {
                "Job": job_lookup.get(str(a.get("job_id")), "-"),
                "Applicant": a.get("name"),
                "Email": a.get("email"),
                "Phone": a.get("phone"),
                "Resume_URL": a.get("resume_url"),
            }
            for a in apps
        ]
        df = pd.DataFrame(records)
        filename = f"applications_job_{selected_job}.xlsx" if selected_job else "applications.xlsx"
    finally:
        if conn and cur:
            release_db(conn, cur)

    return _send_excel_dataframe(df, filename)

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    message = None
    message_type = "success"
    
    if request.method == "POST":
        if "logo_file" in request.files:
            file = request.files["logo_file"]
            if file and file.filename:
                import os, time
                from werkzeug.utils import secure_filename
                safe_name = secure_filename(file.filename)
                local_filename = f"logo_{int(time.time())}_{safe_name}"
                uploads_dir = os.path.join(app.root_path, "static", "uploads")
                os.makedirs(uploads_dir, exist_ok=True)
                file.save(os.path.join(uploads_dir, local_filename))
                
                logo_url = f"/static/uploads/{local_filename}"
                conn, cur = get_db(True)
                try:
                    cur.execute("SELECT id FROM company_settings LIMIT 1")
                    if cur.fetchone():
                        cur.execute("UPDATE company_settings SET logo_url = %s", (logo_url,))
                    else:
                        cur.execute("INSERT INTO company_settings (logo_url) VALUES (%s)", (logo_url,))
                    conn.commit()
                    message = "Company logo updated successfully!"
                    message_type = "success"
                except Exception as e:
                    print("Error updating logo:", e)
                    message = "Failed to update company logo."
                    message_type = "error"
                finally:
                    release_db(conn, cur)
        else:
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
                try:
                    conn, cur = get_db(True)
                    cur.execute("SELECT password, email FROM hrms_users WHERE id = %s", (user_id,))
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
                            "UPDATE hrms_users SET password = %s WHERE id = %s",
                            (hashed_password, user_id)
                        )
                        conn.commit()
                        message = "Password updated successfully!"
                        message_type = "success"
                    else:
                        message = "Old password is incorrect"
                        message_type = "error"
                    
                    release_db(conn, cur)
                except Exception as e:
                    print("Database password update failed, using Supabase fallback:", e)
                    try:
                        from supabase_client import supabase
                        # Attempt Direct Table Update via Supabase Client
                        hashed_password = generate_password_hash(new_password)
                        res = supabase.table("hrms_users").update({"password": hashed_password}).eq("id", user_id).execute()
                        if res.data:
                            message = "Password updated successfully via Supabase!"
                            message_type = "success"
                        else:
                            message = "Old password verification or update failed."
                            message_type = "error"
                    except Exception as ex:
                        print("Supabase update failed:", ex)
                        message = "Password update failed. Database and Supabase are unreachable."
                        message_type = "error"

    conn, cur = get_db(True)
    try:
        cur.execute("SELECT logo_url FROM company_settings LIMIT 1")
        company = cur.fetchone()
    except Exception:
        company = None
    finally:
        release_db(conn, cur)

    return render_template("settings.html", message=message, message_type=message_type, company=company)

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
                   es.effective_from::text AS effective_from,
                   es.monthly_salary AS monthly_amount,
                   COALESCE(es.annual_ctc, es.monthly_salary * 12) AS annual_ctc
            FROM employee_salary es
            JOIN hrms_employees e ON es.employee_id = e.id
            LEFT JOIN salary_structures s ON es.structure_id = s.id
            ORDER BY es.effective_from DESC
        """)

        records = cur.fetchall()
        release_db(conn, cur)
    except Exception as e:
        print("Error fetching salary records:", e)
        records = supabase_rest.list_salary_records()
        for r in records:
            r["monthly_amount"] = r.get("monthly_salary") or 0.0
            r["annual_ctc"] = r.get("annual_ctc") or (r["monthly_amount"] * 12.0)

    return render_template("salary_records.html", records=records)

@app.route("/download-salary-records")
@login_required
def download_salary_records():
    conn = None
    cur = None
    try:
        conn, cur = get_db()

        query = """
            SELECT 
                e.full_name AS Employee,
                CASE
                    WHEN es.monthly_salary IS NOT NULL
                        THEN CONCAT('Manual Salary (', es.monthly_salary, ')')
                    ELSE COALESCE(s.name, 'Not Assigned')
                END AS Salary_Structure,
                es.effective_from::text AS Effective_From,
                es.monthly_salary AS Monthly_Amount,
                COALESCE(es.annual_ctc, es.monthly_salary * 12) AS Annual_CTC
            FROM employee_salary es
            JOIN hrms_employees e ON es.employee_id = e.id
            LEFT JOIN salary_structures s ON es.structure_id = s.id
            ORDER BY es.effective_from DESC
        """

        df = pd.read_sql(query, conn)
    except Exception as e:
        print("Error downloading salary records:", e)
        records = supabase_rest.list_salary_records()
        df = pd.DataFrame(
            [
                {
                    "Employee": record.get("employee_name"),
                    "Salary_Structure": record.get("structure_name"),
                    "Effective_From": record.get("effective_from"),
                    "Monthly_Amount": record.get("monthly_salary") or 0.0,
                    "Annual_CTC": record.get("annual_ctc") or ((record.get("monthly_salary") or 0.0) * 12.0),
                }
                for record in records
            ]
        )
    finally:
        if conn and cur:
            release_db(conn, cur)

    return _send_excel_dataframe(df, "salary_records.xlsx")


# =========================
# RUN SERVER
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)