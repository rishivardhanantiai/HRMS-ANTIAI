print("APP.PY LOADED")

from flask import (
    Flask, render_template, request,
    redirect, session, send_from_directory
)
import os
from datetime import datetime
from dotenv import load_dotenv
from werkzeug.security import check_password_hash

from utils.auth import login_required
from utils.db import get_db, release_db

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

UPLOAD_FOLDER = "uploads/resumes"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =========================
# REGISTER BLUEPRINTS
# =========================
app.register_blueprint(employees_bp)
app.register_blueprint(roles_bp)


# =========================
# AUTHENTICATION
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn, cur = get_db(True)

        # -------- Users Table --------
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["hr_logged_in"] = True
            session["user_email"] = user["email"]
            release_db(conn, cur)
            return redirect("/dashboard")

        # -------- Legacy Admin --------
        cur.execute("SELECT * FROM admins WHERE email=%s", (email,))
        admin = cur.fetchone()

        release_db(conn, cur)

        if admin and admin["password"] == password:
            session.clear()
            session["hr_logged_in"] = True
            return redirect("/dashboard")

        return "Invalid Login", 401

    return render_template("login.html")


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
    return render_template("applications.html")


@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


# =========================
# RUN SERVER
# =========================
if __name__ == "__main__":
    app.run(debug=True)
