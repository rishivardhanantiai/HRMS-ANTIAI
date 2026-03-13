print("APP.PY LOADED")

from flask import (
    Flask, flash, render_template, request,
    redirect, session, send_from_directory
)
import os
from datetime import datetime
from dotenv import load_dotenv
from werkzeug.security import check_password_hash
import pandas as pd
from flask import send_file
from hrms.leave.routes import leave_bp
from utils.auth import login_required
from utils.db import get_db, release_db
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
UPLOAD_FOLDER = "uploads/resumes"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


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

        if not check_password_hash(user["password"], password):
            release_db(conn, cur)
            flash("Invalid Email or Password", "error")
            return redirect(request.url)

        if user["role_name"] != role:
            release_db(conn, cur)
            flash("Unauthorized Role Access", "error")
            return redirect(request.url)

        # SESSION SETUP
        session.clear()
        session["user_id"] = user["id"]
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

    conn, cur = get_db(True)

    cur.execute("SELECT COUNT(*) AS total FROM jobs")
    total_jobs = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) AS total FROM applications")
    total_applications = cur.fetchone()["total"]

    release_db(conn, cur)

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
            filename = f"{int(datetime.now().timestamp())}_{resume.filename}"
            resume.save(os.path.join(UPLOAD_FOLDER, filename))
            resume_url = f"/uploads/resumes/{filename}"

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

        return "Application submitted successfully!"

    release_db(conn, cur)

    return render_template("apply.html", job=job)


# =========================
# RESUME SERVE
# =========================
@app.route("/uploads/resumes/<path:filename>")
def serve_resume(filename):
    return send_from_directory("uploads/resumes", filename)


# =========================
# APPLICATIONS & SETTINGS
# =========================
@app.route("/applications")
@login_required
def applications():

    conn, cur = get_db(True)

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

    return render_template(
        "applications.html",
        applications=applications
    )

@app.route("/salary-records")
@login_required
def salary_records():

    conn, cur = get_db(True)

    cur.execute("""
        SELECT es.id,
               e.full_name AS employee_name,
               s.name AS structure_name,
               es.effective_from
        FROM employee_salary es
        JOIN hrms_employees e ON es.employee_id = e.id
        JOIN salary_structures s ON es.structure_id = s.id
        ORDER BY es.effective_from DESC
    """)

    records = cur.fetchall()

    release_db(conn, cur)

    return render_template("salary_records.html", records=records)

@app.route("/download-salary-records")
@login_required
def download_salary_records():

    conn, _ = get_db()

    query = """
        SELECT 
            e.full_name AS Employee,
            s.name AS Salary_Structure,
            es.effective_from AS Effective_From
        FROM employee_salary es
        JOIN hrms_employees e ON es.employee_id = e.id
        JOIN salary_structures s ON es.structure_id = s.id
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