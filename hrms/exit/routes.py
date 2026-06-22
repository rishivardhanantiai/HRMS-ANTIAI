from flask import Blueprint, render_template, request, redirect, flash, jsonify
from utils.auth import login_required, role_required
from utils.db import get_db, release_db

exit_bp = Blueprint("exit_bp", __name__, url_prefix="/hrms/exit")

# FIX: Removed <int:> from <emp_id>
@exit_bp.route("/manage/<emp_id>")
@login_required
@role_required(["HR", "Admin"])
def manage_exit(emp_id):
    conn, cur = get_db()
    if not conn:
        flash("Database connection error.", "error")
        return redirect("/hrms/employees/ui")

    try:
        cur.execute("SELECT * FROM hrms_employees WHERE id = %s", (emp_id,))
        employee = cur.fetchone()

        if not employee:
            flash("Employee not found.", "error")
            return redirect("/hrms/employees/ui")

        cur.execute("SELECT * FROM employee_exits WHERE employee_id = %s", (emp_id,))
        active_exit = cur.fetchone()

        fnf_record = None
        exit_docs = []

        if active_exit:
            cur.execute("SELECT * FROM employee_fnf_records WHERE exit_id = %s", (active_exit['id'],))
            fnf_record = cur.fetchone()

            cur.execute("SELECT * FROM employee_exit_documents WHERE exit_id = %s ORDER BY generated_at DESC", (active_exit['id'],))
            exit_docs = cur.fetchall()

        return render_template(
            "hrms/exit/manage.html",
            emp=employee,
            active_exit=active_exit,
            fnf=fnf_record,
            docs=exit_docs
        )

    except Exception as e:
        flash(f"Error loading exit management: {e}", "error")
        return redirect("/hrms/employees/ui")
    finally:
        release_db(conn, cur)


@exit_bp.route("/initiate", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def initiate_exit():
    from flask import session
    emp_id = request.form.get("employee_id")
    exit_type = request.form.get("exit_type")
    notice_period = request.form.get("notice_period")
    last_working_date = request.form.get("last_working_date")
    exit_reason = request.form.get("exit_reason")
    remarks = request.form.get("remarks")
    initiated_by = session.get("user")

    conn, cur = get_db(True)
    try:
        cur.execute("""
            INSERT INTO employee_exits (employee_id, exit_type, notice_period, last_working_date, exit_reason, remarks, initiated_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (emp_id, exit_type, notice_period, last_working_date, exit_reason, remarks, initiated_by))
        
        exit_id = cur.fetchone()['id']

        cur.execute("""
            INSERT INTO employee_fnf_records (employee_id, exit_id) VALUES (%s, %s)
        """, (emp_id, exit_id))

        flash("Exit process initiated successfully.", "success")
    except Exception as e:
        print("Error initiating exit:", e)
        flash("Could not initiate exit process.", "error")
    finally:
        release_db(conn, cur)

    return redirect(f"/hrms/exit/manage/{emp_id}")


# FIX: Removed <int:> from <exit_id>
@exit_bp.route("/update_status/<exit_id>", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def update_status(exit_id):
    new_status = request.form.get("status")
    emp_id = request.form.get("employee_id")

    conn, cur = get_db(True)
    try:
        cur.execute("UPDATE employee_exits SET status = %s WHERE id = %s", (new_status, exit_id))
        
        if new_status == "Exit Closed":
            cur.execute("UPDATE hrms_employees SET status = 'Exited' WHERE id = %s", (emp_id,))
            
        flash(f"Exit status updated to {new_status}.", "success")
    except Exception as e:
        print("Error updating status:", e)
        flash("Could not update status.", "error")
    finally:
        release_db(conn, cur)

    return redirect(f"/hrms/exit/manage/{emp_id}")


# FIX: Removed <int:> from <exit_id>
@exit_bp.route("/save_fnf/<exit_id>", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def save_fnf(exit_id):
    emp_id = request.form.get("employee_id")
    pending_salary = float(request.form.get("pending_salary") or 0)
    leave_encashment = float(request.form.get("leave_encashment") or 0)
    bonus = float(request.form.get("bonus") or 0)
    reimbursement = float(request.form.get("reimbursement") or 0)
    deductions = float(request.form.get("deductions") or 0)

    net_amount = (pending_salary + leave_encashment + bonus + reimbursement) - deductions

    conn, cur = get_db(True)
    try:
        cur.execute("""
            UPDATE employee_fnf_records 
            SET pending_salary = %s, leave_encashment = %s, bonus = %s, reimbursement = %s, deductions = %s, net_amount = %s
            WHERE exit_id = %s
        """, (pending_salary, leave_encashment, bonus, reimbursement, deductions, net_amount, exit_id))
        flash("FNF calculation saved.", "success")
    except Exception as e:
        print("Error saving FNF:", e)
        flash("Could not save FNF calculation.", "error")
    finally:
        release_db(conn, cur)

    return redirect(f"/hrms/exit/manage/{emp_id}")

@exit_bp.route("/history")
@login_required
@role_required(["HR", "Admin"])
def exit_history():
    conn, cur = get_db()
    if not conn:
        return redirect("/dashboard")

    try:
        cur.execute("""
            SELECT e.*, emp.full_name, emp.department 
            FROM employee_exits e
            JOIN hrms_employees emp ON e.employee_id = emp.id
            ORDER BY e.created_at DESC
        """)
        exits = cur.fetchall()

        return render_template("hrms/exit/history.html", exits=exits)
    except Exception as e:
        print("Error loading exit history:", e)
        return redirect("/dashboard")
    finally:
        release_db(conn, cur)