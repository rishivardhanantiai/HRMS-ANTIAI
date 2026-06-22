import os
import io
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, request, redirect, flash, session, url_for
from werkzeug.utils import secure_filename
from utils.auth import login_required
from utils.db import get_db, release_db

performance_bp = Blueprint("performance_bp", __name__, url_prefix="/hrms/performance")

def hr_admin_required():
    return session.get("role") in ["HR", "Admin"]

@performance_bp.route("/ui")
@login_required
def performance_ui():
    if not hr_admin_required():
        return redirect("/dashboard")

    evaluations = []
    employees = []
    try:
        conn, cur = get_db(True)
        # Fetch all evaluations with employee details
        cur.execute("""
            SELECT p.id, p.status, p.evaluation_month, p.evaluation_year, p.final_score,
                   e.full_name, e.employee_code, e.department, e.designation,
                   COALESCE(e2.full_name, 'HR Admin') as evaluator_name
            FROM performance_evaluations p
            JOIN hrms_employees e ON p.employee_id = e.id
            LEFT JOIN hrms_users u ON p.evaluator_id = u.id
            LEFT JOIN hrms_employees e2 ON u.employee_id = e2.id
            ORDER BY p.evaluation_year DESC, p.evaluation_month DESC, p.id DESC
        """)
        evaluations = cur.fetchall()

        # Fetch active/inactive employees list for starting new evaluation dropdown
        cur.execute("""
            SELECT id, full_name, employee_code, department, designation
            FROM hrms_employees
            WHERE status != 'Deleted'
            ORDER BY full_name
        """)
        employees = cur.fetchall()

        release_db(conn, cur)
    except Exception as e:
        print(f"Error fetching performance: {e}")
        if 'conn' in locals():
            try:
                release_db(conn, cur)
            except Exception:
                pass

    return render_template(
        "hrms/performance_history.html",
        evaluations=evaluations,
        employees=employees
    )

@performance_bp.route("/start/<employee_id>", methods=["GET"])
@login_required
def start_evaluation(employee_id):
    if not hr_admin_required():
        return redirect("/dashboard")
        
    try:
        conn, cur = get_db(True)
        cur.execute("""
            SELECT e.id, e.full_name, e.employee_code, e.department, e.designation, e.joining_date,
                   m.full_name as manager_name, m.id as manager_id
            FROM hrms_employees e
            LEFT JOIN hrms_employees m ON e.manager_id = m.id
            WHERE e.id = %s
        """, (employee_id,))
        emp = cur.fetchone()
        
        # Calculate evaluation cycle
        cycle = 1
        eval_month = date.today().month
        eval_year = date.today().year
        
        if emp and emp["joining_date"]:
            jd = emp["joining_date"]
            months_diff = (date.today().year - jd.year) * 12 + date.today().month - jd.month
            if months_diff > 0:
                cycle = months_diff
        
        release_db(conn, cur)
        
        if not emp:
            flash("Employee not found.", "error")
            return redirect("/hrms/employees/ui")
            
        return render_template("hrms/evaluate_employee.html", emp=emp, cycle=cycle, eval_month=eval_month, eval_year=eval_year)
    except Exception as e:
        print(f"Error loading evaluation form: {e}")
        return redirect("/hrms/employees/ui")

@performance_bp.route("/save/<employee_id>", methods=["POST"])
@login_required
def save_evaluation(employee_id):
    if not hr_admin_required():
        return redirect("/dashboard")
        
    try:
        conn, cur = get_db()
        evaluator_id = session.get("user_id")
        eval_type = request.form.get("evaluation_type", "HR Evaluation")
        
        # Extract metadata
        cycle = int(request.form.get("evaluation_cycle", 1))
        eval_month = int(request.form.get("evaluation_month", date.today().month))
        eval_year = int(request.form.get("evaluation_year", date.today().year))
        
        # Calculate scores
        # In actual implementation, we read radio button inputs. 
        # For simplicity, calculate from form directly or expect them to be sent.
        final_score = float(request.form.get("final_score") or 0)
        manager_score = float(request.form.get("manager_score") or 0)
        hr_score = float(request.form.get("hr_score") or 0)
        
        grade = request.form.get("grade", "")
        status = request.form.get("status", "Completed")
        
        cur.execute("""
            INSERT INTO performance_evaluations 
            (employee_id, evaluator_id, evaluation_date, evaluation_month, evaluation_year, evaluation_cycle, evaluation_type, final_score, hr_score, manager_score, grade, strengths, improvements, hr_comments, manager_comments, goals, status)
            VALUES (%s, %s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            employee_id, evaluator_id, eval_month, eval_year, cycle, eval_type,
            final_score, hr_score, manager_score, grade,
            request.form.get("strengths", ""), request.form.get("improvements", ""),
            request.form.get("hr_comments", ""), request.form.get("manager_comments", ""),
            request.form.get("goals", ""), status
        ))
        
        eval_id = cur.fetchone()[0]
        
        # Save line-item ratings
        for key, val in request.form.items():
            if key.startswith("rating_"):
                category = key.replace("rating_", "")
                rating_val = int(val)
                cur.execute("""
                    INSERT INTO performance_ratings (evaluation_id, category_name, rating, evaluator_type)
                    VALUES (%s, %s, %s, %s)
                """, (eval_id, category, rating_val, eval_type))
        
        # Automatic PIP generation
        if final_score < 60:
            deadline = date.today() + relativedelta(months=1)
            cur.execute("""
                INSERT INTO performance_improvement_plans (evaluation_id, employee_id, target_score, deadline, action_items)
                VALUES (%s, %s, %s, %s, %s)
            """, (eval_id, employee_id, 75.0, deadline, "Improve performance based on recent evaluation."))
            
        conn.commit()
        release_db(conn, cur)
        
        flash("Evaluation saved successfully.", "success")
        return redirect(f"/hrms/employees/{employee_id}/profile?tab=performance")
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
            release_db(conn, cur)
        with open("eval_error.log", "w") as f:
            f.write(str(e))
        print(f"Error saving evaluation: {e}")
        return redirect(f"/hrms/performance/start/{employee_id}")

@performance_bp.route("/update/<eval_id>", methods=["POST"])
@login_required
def update_evaluation(eval_id):
    if not hr_admin_required():
        return redirect("/dashboard")
        
    try:
        conn, cur = get_db()
        
        eval_type = request.form.get("evaluation_type", "HR Evaluation")
        final_score = float(request.form.get("final_score") or 0)
        manager_score = float(request.form.get("manager_score") or 0)
        hr_score = float(request.form.get("hr_score") or 0)
        grade = request.form.get("grade", "")
        status = request.form.get("status", "Completed")
        
        cur.execute("""
            UPDATE performance_evaluations 
            SET evaluation_type=%s, final_score=%s, hr_score=%s, manager_score=%s, grade=%s, 
                strengths=%s, improvements=%s, hr_comments=%s, manager_comments=%s, goals=%s, status=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s RETURNING employee_id
        """, (
            eval_type, final_score, hr_score, manager_score, grade,
            request.form.get("strengths", ""), request.form.get("improvements", ""),
            request.form.get("hr_comments", ""), request.form.get("manager_comments", ""),
            request.form.get("goals", ""), status,
            eval_id
        ))
        
        emp_id = cur.fetchone()[0]
        
        # Clear old ratings
        cur.execute("DELETE FROM performance_ratings WHERE evaluation_id=%s", (eval_id,))
        
        # Save line-item ratings
        for key, val in request.form.items():
            if key.startswith("rating_"):
                category = key.replace("rating_", "")
                rating_val = int(val)
                cur.execute("""
                    INSERT INTO performance_ratings (evaluation_id, category_name, rating, evaluator_type)
                    VALUES (%s, %s, %s, %s)
                """, (eval_id, category, rating_val, eval_type))
        
        conn.commit()
        release_db(conn, cur)
        
        flash("Evaluation updated successfully.", "success")
        return redirect(f"/hrms/employees/{emp_id}/profile?tab=performance")
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
            release_db(conn, cur)
        print(f"Error updating evaluation: {e}")
        return redirect(f"/hrms/performance/view/{eval_id}")

@performance_bp.route("/acknowledge/<eval_id>", methods=["POST"])
@login_required
def acknowledge_evaluation(eval_id):
    try:
        conn, cur = get_db()
        comments = request.form.get("employee_comments", "")
        cur.execute("""
            UPDATE performance_evaluations 
            SET employee_acknowledged = TRUE, employee_comments = %s, acknowledged_at = CURRENT_TIMESTAMP, status = 'Acknowledged'
            WHERE id = %s
        """, (comments, eval_id))
        conn.commit()
        release_db(conn, cur)
        flash("Evaluation acknowledged.", "success")
        return redirect("/dashboard")
    except Exception as e:
        print(f"Error acknowledging evaluation: {e}")
        return redirect("/dashboard")

@performance_bp.route("/my_evaluations", methods=["GET"])
@login_required
def my_evaluations():
    if session.get("role") != "Employee":
        return redirect("/dashboard")

    conn, cur = get_db(True)
    try:
        employee_id = session.get("employee_id")
        cur.execute("""
            SELECT p.*, COALESCE(e2.full_name, 'HR Admin') as evaluator_name 
            FROM performance_evaluations p
            LEFT JOIN hrms_users u ON p.evaluator_id = u.id
            LEFT JOIN hrms_employees e2 ON u.employee_id = e2.id
            WHERE p.employee_id = %s AND p.status != 'Draft'
            ORDER BY p.evaluation_year DESC, p.evaluation_month DESC
        """, (employee_id,))
        evals = cur.fetchall()
    finally:
        release_db(conn, cur)

    return render_template("hrms/my_evaluations.html", evals=evals)

@performance_bp.route("/view/<eval_id>", methods=["GET"])
@login_required
def view_evaluation(eval_id):
    conn, cur = get_db(True)
    try:
        cur.execute("""
            SELECT p.*, e.full_name, e.employee_code, e.department, e.designation, e.joining_date, COALESCE(e2.full_name, 'HR Admin') as evaluator_name
            FROM performance_evaluations p
            JOIN hrms_employees e ON p.employee_id = e.id
            LEFT JOIN hrms_users u ON p.evaluator_id = u.id
            LEFT JOIN hrms_employees e2 ON u.employee_id = e2.id
            WHERE p.id = %s
        """, (eval_id,))
        evaluation = cur.fetchone()

        if not evaluation:
            flash("Evaluation not found", "error")
            return redirect("/dashboard")

        # Security check
        if session.get("role") == "Employee" and evaluation["employee_id"] != session.get("employee_id"):
            return redirect("/dashboard")

        cur.execute("SELECT category_name, rating FROM performance_ratings WHERE evaluation_id = %s", (eval_id,))
        ratings = cur.fetchall()
        
        # Determine PIP if exists
        pip = None
        if evaluation["final_score"] < 60:
            cur.execute("SELECT * FROM performance_improvement_plans WHERE evaluation_id = %s", (eval_id,))
            pip = cur.fetchone()

    finally:
        release_db(conn, cur)

    return render_template("hrms/view_evaluation.html", eval=evaluation, ratings=ratings, pip=pip)

@performance_bp.route("/export/<eval_id>", methods=["GET"])
@login_required
def export_evaluation(eval_id):
    import tempfile
    
    conn = None
    cur = None
    try:
        conn, cur = get_db(True)
        cur.execute("SELECT employee_id, evaluation_cycle, evaluation_year FROM performance_evaluations WHERE id = %s", (eval_id,))
        eval_record = cur.fetchone()
        if not eval_record:
            release_db(conn, cur)
            return "Evaluation not found", 404
        
        # Check permissions
        if session.get("role") == "Employee" and eval_record["employee_id"] != session.get("employee_id"):
            release_db(conn, cur)
            return "Unauthorized", 403
            
        employee_id = eval_record["employee_id"]
        cycle = eval_record["evaluation_cycle"]
        year = eval_record["evaluation_year"]
        
        # Try importing Playwright
        import httpx
        from playwright.sync_api import sync_playwright
        
        # Generate PDF with Playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            domain = request.host
            cookie_name = "session"
            cookie_value = request.cookies.get("session")
            
            if cookie_value:
                page.context.add_cookies([{
                    "name": cookie_name,
                    "value": cookie_value,
                    "domain": domain.split(":")[0],
                    "path": "/"
                }])
            
            url = f"{request.scheme}://{request.host}/hrms/performance/view/{eval_id}?print=1"
            page.goto(url, wait_until="networkidle")
            
            pdf_bytes = page.pdf(format="A4", print_background=True)
            browser.close()
            
        # Upload to Supabase
        supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        supabase_key = os.getenv("SUPABASE_KEY")
        bucket = os.getenv("SUPABASE_RESUME_BUCKET", "resumes")
        
        if not supabase_url or not supabase_key:
            return "Supabase credentials missing", 500
            
        safe_name = f"eval_{employee_id}_cycle_{cycle}_{year}.pdf"
        timestamp = int(datetime.now().timestamp())
        object_key = f"evaluations/{timestamp}_{safe_name}"
        
        upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{object_key}"
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/pdf",
            "x-upsert": "false"
        }
        
        response = httpx.post(upload_url, content=pdf_bytes, headers=headers, timeout=30.0)
        
        if response.status_code in (200, 201):
            public_url = f"{supabase_url}/storage/v1/object/public/{bucket}/{object_key}"
            return redirect(public_url)
        else:
            raise RuntimeError(f"Supabase upload failed: {response.text}")
            
    except Exception as e:
        print(f"Error generating PDF, executing browser print fallback: {e}")
        flash("PDF generation service is currently offline. We have loaded the printer-friendly version. Press Ctrl+P (Cmd+P) to print/save as PDF.", "info")
        return redirect(url_for("performance_bp.view_evaluation", eval_id=eval_id) + "?print=1")
    finally:
        if conn and cur:
            try:
                release_db(conn, cur)
            except Exception:
                pass
