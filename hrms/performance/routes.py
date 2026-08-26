import os
import io
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, request, redirect, flash, session, url_for
from werkzeug.utils import secure_filename
from utils.auth import login_required
from utils.db import get_db, release_db
from utils import supabase_rest

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
    conn = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB connection")
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
        conn = None
    except Exception as e:
        print("Error fetching performance via DB, trying REST fallback:", e)
        if conn:
            try: release_db(conn, cur)
            except Exception: pass
            conn = None
        try:
            evals_raw = supabase_rest.get_rows("performance_evaluations", {"order": "evaluation_year.desc,evaluation_month.desc,id.desc"})
            employees_raw = supabase_rest.get_rows("hrms_employees")
            users_raw = supabase_rest.get_rows("hrms_users")

            emp_map = {str(emp["id"]): emp for emp in employees_raw}
            user_map = {str(u["id"]): u for u in users_raw}

            evaluations = []
            for ev in evals_raw:
                emp = emp_map.get(str(ev.get("employee_id")))
                user = user_map.get(str(ev.get("evaluator_id")))
                evaluator_emp = emp_map.get(str(user.get("employee_id"))) if user else None

                evaluations.append({
                    "id": ev.get("id"),
                    "status": ev.get("status"),
                    "evaluation_month": ev.get("evaluation_month"),
                    "evaluation_year": ev.get("evaluation_year"),
                    "final_score": ev.get("final_score"),
                    "full_name": emp.get("full_name") if emp else "-",
                    "employee_code": emp.get("employee_code") if emp else "-",
                    "department": emp.get("department") if emp else "-",
                    "designation": emp.get("designation") if emp else "-",
                    "evaluator_name": evaluator_emp.get("full_name") if evaluator_emp else "HR Admin"
                })

            employees = [
                {
                    "id": emp.get("id"),
                    "full_name": emp.get("full_name"),
                    "employee_code": emp.get("employee_code"),
                    "department": emp.get("department"),
                    "designation": emp.get("designation")
                }
                for emp in employees_raw if emp.get("status") != "Deleted"
            ]
            employees.sort(key=lambda x: (x["full_name"] or ""))
        except Exception as rest_err:
            print("REST fallback for performance ui failed:", rest_err)
            evaluations = []
            employees = []

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
        
    conn = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB connection")
        cur.execute("""
            SELECT e.id, e.full_name, e.employee_code, e.department, e.designation, e.joining_date,
                   m.full_name as manager_name, m.id as manager_id
            FROM hrms_employees e
            LEFT JOIN hrms_employees m ON e.manager_id = m.id
            WHERE e.id = %s
        """, (employee_id,))
        emp = cur.fetchone()
        
        release_db(conn, cur)
        conn = None
    except Exception as e:
        print("Error loading evaluation form via DB, trying REST fallback:", e)
        if conn:
            try: release_db(conn, cur)
            except Exception: pass
            conn = None
        try:
            emp_raw = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{employee_id}"})
            if emp_raw:
                emp = {
                    "id": emp_raw.get("id"),
                    "full_name": emp_raw.get("full_name"),
                    "employee_code": emp_raw.get("employee_code"),
                    "department": emp_raw.get("department"),
                    "designation": emp_raw.get("designation"),
                    "joining_date": emp_raw.get("joining_date")
                }
                if isinstance(emp["joining_date"], str):
                    emp["joining_date"] = datetime.strptime(emp["joining_date"][:10], "%Y-%m-%d").date()
                
                # Fetch manager
                if emp_raw.get("manager_id"):
                    mgr = supabase_rest.get_first_row("hrms_employees", {"select": "id,full_name", "id": f"eq.{emp_raw['manager_id']}"})
                    if mgr:
                        emp["manager_name"] = mgr.get("full_name")
                        emp["manager_id"] = mgr.get("id")
                    else:
                        emp["manager_name"] = None
                        emp["manager_id"] = None
                else:
                    emp["manager_name"] = None
                    emp["manager_id"] = None
            else:
                emp = None
        except Exception as rest_err:
            print("REST fallback for start evaluation failed:", rest_err)
            emp = None

    if not emp:
        flash("Employee not found.", "error")
        return redirect("/hrms/employees/ui")

    # Calculate evaluation cycle
    cycle = 1
    eval_month = date.today().month
    eval_year = date.today().year
    
    if emp and emp.get("joining_date"):
        jd = emp["joining_date"]
        months_diff = (date.today().year - jd.year) * 12 + date.today().month - jd.month
        if months_diff > 0:
            cycle = months_diff

    return render_template("hrms/evaluate_employee.html", emp=emp, cycle=cycle, eval_month=eval_month, eval_year=eval_year)

@performance_bp.route("/save/<employee_id>", methods=["POST"])
@login_required
def save_evaluation(employee_id):
    if not hr_admin_required():
        return redirect("/dashboard")
        
    conn = None
    try:
        evaluator_id = session.get("user_id")
        eval_type = request.form.get("evaluation_type", "HR Evaluation")
        
        # Extract metadata
        cycle = int(request.form.get("evaluation_cycle", 1))
        eval_month = int(request.form.get("evaluation_month", date.today().month))
        eval_year = int(request.form.get("evaluation_year", date.today().year))
        
        final_score = float(request.form.get("final_score") or 0)
        manager_score = float(request.form.get("manager_score") or 0)
        hr_score = float(request.form.get("hr_score") or 0)
        
        grade = request.form.get("grade", "")
        status = request.form.get("status", "Completed")
        
        strengths = request.form.get("strengths", "")
        improvements = request.form.get("improvements", "")
        hr_comments = request.form.get("hr_comments", "")
        manager_comments = request.form.get("manager_comments", "")
        goals = request.form.get("goals", "")

        conn, cur = get_db()
        if not conn:
            raise Exception("No DB connection")
            
        cur.execute("""
            INSERT INTO performance_evaluations 
            (employee_id, evaluator_id, evaluation_date, evaluation_month, evaluation_year, evaluation_cycle, evaluation_type, final_score, hr_score, manager_score, grade, strengths, improvements, hr_comments, manager_comments, goals, status)
            VALUES (%s, %s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            employee_id, evaluator_id, eval_month, eval_year, cycle, eval_type,
            final_score, hr_score, manager_score, grade,
            strengths, improvements, hr_comments, manager_comments, goals, status
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
        conn = None
        
        flash("Evaluation saved successfully.", "success")
        return redirect(f"/hrms/employees/{employee_id}/profile?tab=performance")
    except Exception as e:
        print("Error saving evaluation via DB, trying REST fallback:", e)
        if conn:
            try:
                conn.rollback()
                release_db(conn, cur)
            except Exception: pass
            conn = None
        try:
            evaluator_id = session.get("user_id")
            eval_type = request.form.get("evaluation_type", "HR Evaluation")
            cycle = int(request.form.get("evaluation_cycle", 1))
            eval_month = int(request.form.get("evaluation_month", date.today().month))
            eval_year = int(request.form.get("evaluation_year", date.today().year))
            final_score = float(request.form.get("final_score") or 0)
            manager_score = float(request.form.get("manager_score") or 0)
            hr_score = float(request.form.get("hr_score") or 0)
            grade = request.form.get("grade", "")
            status = request.form.get("status", "Completed")
            strengths = request.form.get("strengths", "")
            improvements = request.form.get("improvements", "")
            hr_comments = request.form.get("hr_comments", "")
            manager_comments = request.form.get("manager_comments", "")
            goals = request.form.get("goals", "")

            eval_row = supabase_rest.insert_row("performance_evaluations", {
                "employee_id": employee_id,
                "evaluator_id": evaluator_id,
                "evaluation_date": date.today().isoformat(),
                "evaluation_month": eval_month,
                "evaluation_year": eval_year,
                "evaluation_cycle": cycle,
                "evaluation_type": eval_type,
                "final_score": final_score,
                "hr_score": hr_score,
                "manager_score": manager_score,
                "grade": grade,
                "strengths": strengths,
                "improvements": improvements,
                "hr_comments": hr_comments,
                "manager_comments": manager_comments,
                "goals": goals,
                "status": status
            })

            if eval_row:
                eval_id = eval_row.get("id")
                # Save ratings
                for key, val in request.form.items():
                    if key.startswith("rating_"):
                        category = key.replace("rating_", "")
                        rating_val = int(val)
                        supabase_rest.insert_row("performance_ratings", {
                            "evaluation_id": eval_id,
                            "category_name": category,
                            "rating": rating_val,
                            "evaluator_type": eval_type
                        })

                # Automatic PIP generation
                if final_score < 60:
                    deadline = (date.today() + relativedelta(months=1)).isoformat()
                    supabase_rest.insert_row("performance_improvement_plans", {
                        "evaluation_id": eval_id,
                        "employee_id": employee_id,
                        "target_score": 75.0,
                        "deadline": deadline,
                        "action_items": "Improve performance based on recent evaluation."
                    })
                
                flash("Evaluation saved successfully.", "success")
                return redirect(f"/hrms/employees/{employee_id}/profile?tab=performance")
            else:
                flash("Could not save evaluation.", "error")
                return redirect(f"/hrms/performance/start/{employee_id}")
        except Exception as rest_err:
            print("REST fallback for save evaluation failed:", rest_err)
            with open("eval_error.log", "w") as f:
                f.write(str(rest_err))
            flash("Could not save evaluation.", "error")
            return redirect(f"/hrms/performance/start/{employee_id}")

@performance_bp.route("/update/<eval_id>", methods=["POST"])
@login_required
def update_evaluation(eval_id):
    if not hr_admin_required():
        return redirect("/dashboard")
        
    conn = None
    try:
        eval_type = request.form.get("evaluation_type", "HR Evaluation")
        final_score = float(request.form.get("final_score") or 0)
        manager_score = float(request.form.get("manager_score") or 0)
        hr_score = float(request.form.get("hr_score") or 0)
        grade = request.form.get("grade", "")
        status = request.form.get("status", "Completed")
        strengths = request.form.get("strengths", "")
        improvements = request.form.get("improvements", "")
        hr_comments = request.form.get("hr_comments", "")
        manager_comments = request.form.get("manager_comments", "")
        goals = request.form.get("goals", "")

        conn, cur = get_db()
        if not conn:
            raise Exception("No DB connection")
            
        cur.execute("""
            UPDATE performance_evaluations 
            SET evaluation_type=%s, final_score=%s, hr_score=%s, manager_score=%s, grade=%s, 
                strengths=%s, improvements=%s, hr_comments=%s, manager_comments=%s, goals=%s, status=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s RETURNING employee_id
        """, (
            eval_type, final_score, hr_score, manager_score, grade,
            strengths, improvements, hr_comments, manager_comments, goals, status,
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
        conn = None
        
        flash("Evaluation updated successfully.", "success")
        return redirect(f"/hrms/employees/{emp_id}/profile?tab=performance")
    except Exception as e:
        print("Error updating evaluation via DB, trying REST fallback:", e)
        if conn:
            try:
                conn.rollback()
                release_db(conn, cur)
            except Exception: pass
            conn = None
        try:
            eval_type = request.form.get("evaluation_type", "HR Evaluation")
            final_score = float(request.form.get("final_score") or 0)
            manager_score = float(request.form.get("manager_score") or 0)
            hr_score = float(request.form.get("hr_score") or 0)
            grade = request.form.get("grade", "")
            status = request.form.get("status", "Completed")
            strengths = request.form.get("strengths", "")
            improvements = request.form.get("improvements", "")
            hr_comments = request.form.get("hr_comments", "")
            manager_comments = request.form.get("manager_comments", "")
            goals = request.form.get("goals", "")

            eval_record = supabase_rest.get_first_row("performance_evaluations", {"id": f"eq.{eval_id}"})
            if not eval_record:
                flash("Evaluation not found.", "error")
                return redirect("/dashboard")

            emp_id = eval_record.get("employee_id")

            # Update evaluation
            supabase_rest.update_rows("performance_evaluations", {"id": f"eq.{eval_id}"}, {
                "evaluation_type": eval_type,
                "final_score": final_score,
                "hr_score": hr_score,
                "manager_score": manager_score,
                "grade": grade,
                "strengths": strengths,
                "improvements": improvements,
                "hr_comments": hr_comments,
                "manager_comments": manager_comments,
                "goals": goals,
                "status": status,
                "updated_at": datetime.now().isoformat()
            })

            # Delete old ratings
            supabase_rest.delete_rows("performance_ratings", {"evaluation_id": f"eq.{eval_id}"})

            # Insert new ratings
            for key, val in request.form.items():
                if key.startswith("rating_"):
                    category = key.replace("rating_", "")
                    rating_val = int(val)
                    supabase_rest.insert_row("performance_ratings", {
                        "evaluation_id": eval_id,
                        "category_name": category,
                        "rating": rating_val,
                        "evaluator_type": eval_type
                    })

            flash("Evaluation updated successfully.", "success")
            return redirect(f"/hrms/employees/{emp_id}/profile?tab=performance")
        except Exception as rest_err:
            print("REST fallback for update evaluation failed:", rest_err)
            flash("Could not update evaluation.", "error")
            return redirect(f"/hrms/performance/view/{eval_id}")

@performance_bp.route("/acknowledge/<eval_id>", methods=["POST"])
@login_required
def acknowledge_evaluation(eval_id):
    conn = None
    try:
        comments = request.form.get("employee_comments", "")
        conn, cur = get_db()
        if not conn:
            raise Exception("No DB connection")
        cur.execute("""
            UPDATE performance_evaluations 
            SET employee_acknowledged = TRUE, employee_comments = %s, acknowledged_at = CURRENT_TIMESTAMP, status = 'Acknowledged'
            WHERE id = %s
        """, (comments, eval_id))
        conn.commit()
        release_db(conn, cur)
        conn = None
        flash("Evaluation acknowledged.", "success")
        return redirect("/dashboard")
    except Exception as e:
        print("Error acknowledging evaluation via DB, trying REST fallback:", e)
        if conn:
            try: release_db(conn, cur)
            except Exception: pass
            conn = None
        try:
            comments = request.form.get("employee_comments", "")
            supabase_rest.update_rows("performance_evaluations", {"id": f"eq.{eval_id}"}, {
                "employee_acknowledged": True,
                "employee_comments": comments,
                "acknowledged_at": datetime.now().isoformat(),
                "status": "Acknowledged"
            })
            flash("Evaluation acknowledged.", "success")
            return redirect("/dashboard")
        except Exception as rest_err:
            print("REST fallback for acknowledge evaluation failed:", rest_err)
            return redirect("/dashboard")

@performance_bp.route("/my_evaluations", methods=["GET"])
@login_required
def my_evaluations():
    if session.get("role") != "Employee":
        return redirect("/dashboard")

    conn, cur = None, None
    evals = []
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB connection")
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
        release_db(conn, cur)
        conn = None
    except Exception as e:
        print("Error loading my evaluations via DB, trying REST fallback:", e)
        if conn:
            try: release_db(conn, cur)
            except Exception: pass
            conn = None
        try:
            employee_id = session.get("employee_id")
            evals_raw = supabase_rest.get_rows("performance_evaluations", {
                "employee_id": f"eq.{employee_id}",
                "status": "neq.Draft",
                "order": "evaluation_year.desc,evaluation_month.desc"
            })
            employees_raw = supabase_rest.get_rows("hrms_employees")
            users_raw = supabase_rest.get_rows("hrms_users")

            emp_map = {str(emp["id"]): emp for emp in employees_raw}
            user_map = {str(u["id"]): u for u in users_raw}

            evals = []
            for ev in evals_raw:
                user = user_map.get(str(ev.get("evaluator_id")))
                evaluator_emp = emp_map.get(str(user.get("employee_id"))) if user else None
                ev["evaluator_name"] = evaluator_emp.get("full_name") if evaluator_emp else "HR Admin"
                evals.append(ev)
        except Exception as rest_err:
            print("REST fallback for my evaluations failed:", rest_err)
            evals = []

    return render_template("hrms/my_evaluations.html", evals=evals)

@performance_bp.route("/view/<eval_id>", methods=["GET"])
@login_required
def view_evaluation(eval_id):
    conn, cur = None, None
    evaluation = ratings = pip = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB connection")
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

        release_db(conn, cur)
        conn = None
    except Exception as e:
        print("Error viewing evaluation via DB, trying REST fallback:", e)
        if conn:
            try: release_db(conn, cur)
            except Exception: pass
            conn = None
        try:
            evaluation = supabase_rest.get_first_row("performance_evaluations", {"id": f"eq.{eval_id}"})
            if not evaluation:
                flash("Evaluation not found", "error")
                return redirect("/dashboard")

            # Security check
            if session.get("role") == "Employee" and evaluation["employee_id"] != session.get("employee_id"):
                return redirect("/dashboard")

            # Fetch employee
            emp = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{evaluation['employee_id']}"})
            if emp:
                evaluation["full_name"] = emp.get("full_name")
                evaluation["employee_code"] = emp.get("employee_code")
                evaluation["department"] = emp.get("department")
                evaluation["designation"] = emp.get("designation")
                evaluation["joining_date"] = emp.get("joining_date")
                if isinstance(evaluation["joining_date"], str):
                    evaluation["joining_date"] = datetime.strptime(evaluation["joining_date"][:10], "%Y-%m-%d").date()

            # Fetch evaluator
            evaluation["evaluator_name"] = "HR Admin"
            if evaluation.get("evaluator_id"):
                user = supabase_rest.get_first_row("hrms_users", {"id": f"eq.{evaluation['evaluator_id']}"})
                if user and user.get("employee_id"):
                    evaluator_emp = supabase_rest.get_first_row("hrms_employees", {"select": "full_name", "id": f"eq.{user['employee_id']}"})
                    if evaluator_emp:
                        evaluation["evaluator_name"] = evaluator_emp.get("full_name")

            # Fetch ratings
            ratings = supabase_rest.get_rows("performance_ratings", {"evaluation_id": f"eq.{eval_id}"})
            
            # Fetch PIP
            pip = None
            if evaluation.get("final_score", 0) < 60:
                pip = supabase_rest.get_first_row("performance_improvement_plans", {"evaluation_id": f"eq.{eval_id}"})
        except Exception as rest_err:
            print("REST fallback for view evaluation failed:", rest_err)
            flash("Error loading evaluation details.", "error")
            return redirect("/dashboard")

    return render_template("hrms/view_evaluation.html", eval=evaluation, ratings=ratings, pip=pip)

@performance_bp.route("/export/<eval_id>", methods=["GET"])
@login_required
def export_evaluation(eval_id):
    import tempfile
    
    conn = None
    cur = None
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("SELECT employee_id, evaluation_cycle, evaluation_year FROM performance_evaluations WHERE id = %s", (eval_id,))
            eval_record = cur.fetchone()
            if not eval_record:
                release_db(conn, cur)
                conn, cur = None, None
                return "Evaluation not found", 404
        else:
            raise Exception("No DB connection")
    except Exception as e:
        print("Error getting evaluation record for export via DB, trying REST fallback:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
            conn, cur = None, None
        try:
            eval_record = supabase_rest.get_first_row("performance_evaluations", {"select": "employee_id,evaluation_cycle,evaluation_year", "id": f"eq.{eval_id}"})
            if not eval_record:
                return "Evaluation not found", 404
        except Exception as rest_err:
            print("REST fallback for export evaluation failed:", rest_err)
            return "Evaluation not found", 404
            
    try:
        # Check permissions
        if session.get("role") == "Employee" and eval_record["employee_id"] != session.get("employee_id"):
            if conn:
                try: release_db(conn, cur)
                except: pass
                conn, cur = None, None
            return "Unauthorized", 403
            
        employee_id = eval_record["employee_id"]
        cycle = eval_record["evaluation_cycle"]
        year = eval_record["evaluation_year"]
        
        # Try importing Playwright
        import httpx
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            if conn and cur:
                try: release_db(conn, cur)
                except: pass
                conn, cur = None, None
            return "PDF generation not available on this server.", 503

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
