from flask import Blueprint, render_template, request, redirect, flash, jsonify
from utils.auth import login_required, role_required
from utils.db import get_db, release_db
from utils import supabase_rest
from datetime import datetime

exit_bp = Blueprint("exit_bp", __name__, url_prefix="/hrms/exit")

# FIX: Removed <int:> from <emp_id>
@exit_bp.route("/manage/<emp_id>")
@login_required
@role_required(["HR", "Admin"])
def manage_exit(emp_id):
    conn, cur = None, None
    try:
        conn, cur = get_db()
        if not conn:
            raise Exception("Database connection failed")

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
        print("Error loading exit management via DB, trying REST fallback:", e)
        if conn:
            try:
                release_db(conn, cur)
            except:
                pass
        try:
            employee = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{emp_id}"})
            if not employee:
                flash("Employee not found.", "error")
                return redirect("/hrms/employees/ui")

            active_exit = supabase_rest.get_first_row("employee_exits", {"employee_id": f"eq.{emp_id}"})
            fnf_record = None
            exit_docs = []

            if active_exit:
                fnf_record = supabase_rest.get_first_row("employee_fnf_records", {"exit_id": f"eq.{active_exit['id']}"})
                exit_docs = supabase_rest.get_rows("employee_exit_documents", {
                    "exit_id": f"eq.{active_exit['id']}",
                    "order": "generated_at.desc"
                })

            return render_template(
                "hrms/exit/manage.html",
                emp=employee,
                active_exit=active_exit,
                fnf=fnf_record,
                docs=exit_docs
            )
        except Exception as rest_err:
            flash(f"Error loading exit management: {rest_err}", "error")
            return redirect("/hrms/employees/ui")
    finally:
        if conn:
            try:
                release_db(conn, cur)
            except:
                pass


@exit_bp.route("/initiate", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def initiate_exit():
    from flask import session
    emp_id = request.form.get("employee_id")
    exit_type = request.form.get("exit_type")
    notice_period_str = request.form.get("notice_period", "")
    try:
        notice_period_days = int(''.join(filter(str.isdigit, notice_period_str)))
    except ValueError:
        notice_period_days = 0
    last_working_date = request.form.get("last_working_date")
    exit_reason = request.form.get("exit_reason")
    remarks = request.form.get("remarks")
    initiated_by = session.get("user")

    conn, cur = get_db(True)
    try:
        cur.execute("""
            INSERT INTO employee_exits (employee_id, exit_type, notice_period_days, last_working_date, exit_reason, remarks, initiated_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (emp_id, exit_type, notice_period_days, last_working_date, exit_reason, remarks, initiated_by))
        
        exit_id = cur.fetchone()['id']

        cur.execute("""
            INSERT INTO employee_fnf_records (employee_id, exit_id) VALUES (%s, %s)
        """, (emp_id, exit_id))

        flash("Exit process initiated successfully.", "success")
        conn.commit()
    except Exception as e:
        print("Error initiating exit via DB, trying REST fallback:", e)
        try:
            exit_row = supabase_rest.insert_row("employee_exits", {
                "employee_id": emp_id,
                "exit_type": exit_type,
                "notice_period_days": notice_period_days,
                "last_working_date": last_working_date,
                "exit_reason": exit_reason,
                "remarks": remarks,
                "initiated_by": initiated_by
            })
            if exit_row:
                exit_id = exit_row.get("id")
                supabase_rest.insert_row("employee_fnf_records", {
                    "employee_id": emp_id,
                    "exit_id": exit_id
                })
                flash("Exit process initiated successfully.", "success")
            else:
                flash("Could not initiate exit process.", "error")
        except Exception as rest_err:
            print("REST fallback for initiate exit failed:", rest_err)
            flash("Could not initiate exit process.", "error")
    finally:
        try:
            release_db(conn, cur)
        except:
            pass

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
            
        conn.commit()
        flash(f"Exit status updated to {new_status}.", "success")
    except Exception as e:
        print("Error updating exit status via DB, trying REST fallback:", e)
        try:
            supabase_rest.update_rows("employee_exits", {"id": f"eq.{exit_id}"}, {"status": new_status})
            if new_status == "Exit Closed":
                supabase_rest.update_rows("hrms_employees", {"id": f"eq.{emp_id}"}, {"status": "Exited"})
            flash(f"Exit status updated to {new_status}.", "success")
        except Exception as rest_err:
            print("REST fallback for update status failed:", rest_err)
            flash("Could not update status.", "error")
    finally:
        try:
            release_db(conn, cur)
        except:
            pass

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
    reimbursements = float(request.form.get("reimbursement") or 0)
    deductions = float(request.form.get("deductions") or 0)

    net_payable = (pending_salary + leave_encashment + bonus + reimbursements) - deductions

    conn, cur = get_db(True)
    try:
        cur.execute("""
            UPDATE employee_fnf_records 
            SET pending_salary = %s, leave_encashment = %s, bonus = %s, reimbursements = %s, deductions = %s, net_payable = %s
            WHERE exit_id = %s
        """, (pending_salary, leave_encashment, bonus, reimbursements, deductions, net_payable, exit_id))
        flash("FNF calculation saved.", "success")
        conn.commit()
    except Exception as e:
        print("Error saving FNF via DB, trying REST fallback:", e)
        try:
            supabase_rest.update_rows(
                "employee_fnf_records",
                {"exit_id": f"eq.{exit_id}"},
                {
                    "pending_salary": pending_salary,
                    "leave_encashment": leave_encashment,
                    "bonus": bonus,
                    "reimbursements": reimbursements,
                    "deductions": deductions,
                    "net_payable": net_payable
                }
            )
            flash("FNF calculation saved.", "success")
        except Exception as rest_err:
            print("REST fallback for save FNF failed:", rest_err)
            flash("Could not save FNF calculation.", "error")
    finally:
        try:
            release_db(conn, cur)
        except:
            pass

    return redirect(f"/hrms/exit/manage/{emp_id}")

@exit_bp.route("/history")
@login_required
@role_required(["HR", "Admin"])
def exit_history():
    conn, cur = get_db()
    try:
        if not conn:
            raise Exception("Database connection failed")

        cur.execute("""
            SELECT e.*, emp.full_name, emp.department 
            FROM employee_exits e
            JOIN hrms_employees emp ON e.employee_id = emp.id
            ORDER BY e.created_at DESC
        """)
        exits = cur.fetchall()

        return render_template("hrms/exit/history.html", exits=exits)
    except Exception as e:
        print("Error loading exit history, trying REST fallback:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            exits = supabase_rest.get_rows("employee_exits", {"order": "created_at.desc"})
            for ex in exits:
                emp = supabase_rest.get_first_row("hrms_employees", {"select": "full_name,department", "id": f"eq.{ex.get('employee_id')}"})
                if emp:
                    ex["full_name"] = emp.get("full_name") or "-"
                    ex["department"] = emp.get("department") or "-"
                else:
                    ex["full_name"] = "-"
                    ex["department"] = "-"

            return render_template("hrms/exit/history.html", exits=exits)
        except Exception as rest_err:
            print("REST fallback for exit history failed:", rest_err)
            return redirect("/dashboard")
    finally:
        if conn:
            try:
                release_db(conn, cur)
            except:
                pass