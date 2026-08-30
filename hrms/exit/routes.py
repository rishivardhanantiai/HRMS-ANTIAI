from flask import Blueprint, render_template, request, redirect, flash, jsonify, session
from utils.auth import login_required, role_required
from utils.db import get_db, release_db
from utils import supabase_rest
from datetime import datetime

exit_bp = Blueprint("exit_bp", __name__, url_prefix="/hrms/exit")

@exit_bp.route("/manage/<emp_id>")
@login_required
@role_required(["HR", "Admin"])
def manage_exit(emp_id):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")

        cur.execute("""
            SELECT e.*, m.full_name as manager_name
            FROM hrms_employees e
            LEFT JOIN hrms_employees m ON e.manager_id::text = m.id::text
            WHERE e.id::text = %s
        """, (str(emp_id),))
        employee = cur.fetchone()

        if not employee:
            flash("Employee not found.", "error")
            return redirect("/hrms/employees/ui")

        cur.execute("""
            SELECT * FROM employee_exits 
            WHERE employee_id::text = %s 
            ORDER BY created_at DESC LIMIT 1
        """, (str(emp_id),))
        active_exit = cur.fetchone()

        fnf_record = None
        exit_docs = []

        offboarding = None
        if active_exit:
            cur.execute("SELECT * FROM employee_fnf_records WHERE exit_id = %s", (active_exit['id'],))
            fnf_record = cur.fetchone()

            cur.execute("SELECT * FROM employee_exit_documents WHERE exit_id = %s ORDER BY generated_at DESC", (active_exit['id'],))
            exit_docs = cur.fetchall()

            # Offboarding case
            cur.execute("SELECT * FROM offboarding_cases WHERE employee_id = %s", (str(emp_id),))
            offboarding = cur.fetchone()
            if not offboarding:
                cur.execute("""
                    INSERT INTO offboarding_cases (employee_id, last_working_day)
                    VALUES (%s, %s) RETURNING *
                """, (str(emp_id), active_exit.get('last_working_date')))
                offboarding = cur.fetchone()
                conn.commit()

        return render_template(
            "hrms/exit/manage.html",
            emp=employee,
            active_exit=active_exit,
            fnf=fnf_record,
            docs=exit_docs,
            offboarding=offboarding
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        print("Error loading exit management via DB, trying REST fallback:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            employee = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{emp_id}"})
            if not employee:
                flash("Employee not found.", "error")
                return redirect("/hrms/employees/ui")

            active_exit = supabase_rest.get_first_row("employee_exits", {
                "employee_id": f"eq.{emp_id}",
                "order": "created_at.desc"
            })
            fnf_record = None
            exit_docs = []
            offboarding = None

            if active_exit:
                fnf_record = supabase_rest.get_first_row("employee_fnf_records", {"exit_id": f"eq.{active_exit['id']}"})
                exit_docs = supabase_rest.get_rows("employee_exit_documents", {
                    "exit_id": f"eq.{active_exit['id']}",
                    "order": "generated_at.desc"
                })

                offboarding = supabase_rest.get_first_row("offboarding_cases", {"employee_id": f"eq.{emp_id}"})
                if not offboarding:
                    offboarding = supabase_rest.insert_row("offboarding_cases", {
                        "employee_id": str(emp_id),
                        "last_working_day": active_exit.get("last_working_date")
                    })

            return render_template(
                "hrms/exit/manage.html",
                emp=employee,
                active_exit=active_exit,
                fnf=fnf_record,
                docs=exit_docs,
                offboarding=offboarding
            )
        except Exception as rest_err:
            flash(f"Error loading exit management: {rest_err}", "error")
            return redirect("/hrms/employees/ui")
    finally:
        if conn:
            try: release_db(conn, cur)
            except: pass


@exit_bp.route("/initiate", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def initiate_exit():
    emp_id = request.form.get("employee_id")
    exit_type = request.form.get("exit_type", "Resignation")
    notice_period_str = request.form.get("notice_period", "")
    try:
        notice_period_days = int(''.join(filter(str.isdigit, notice_period_str)))
    except ValueError:
        notice_period_days = 0

    last_working_date = request.form.get("last_working_date", "").strip() or None
    exit_reason = request.form.get("exit_reason", "").strip()
    remarks = request.form.get("remarks", "").strip()
    work_drive_link = request.form.get("work_drive_link", "").strip()
    if work_drive_link and not (work_drive_link.startswith("http://") or work_drive_link.startswith("https://")):
        work_drive_link = "https://" + work_drive_link
    initiated_by = session.get("employee_name") or session.get("user") or "HR / Admin"

    conn, cur = get_db(True)
    try:
        # Check if active exit exists
        cur.execute("SELECT id FROM employee_exits WHERE employee_id = %s AND status != 'Resignation Rejected' ORDER BY created_at DESC LIMIT 1", (str(emp_id),))
        existing = cur.fetchone()

        if existing:
            exit_id = existing['id']
            cur.execute("""
                UPDATE employee_exits 
                SET exit_type = %s, notice_period = %s, notice_period_days = %s, 
                    last_working_date = %s, exit_reason = %s, remarks = %s, 
                    work_drive_link = %s, status = 'Initiated', initiated_by = %s
                WHERE id = %s
            """, (exit_type, notice_period_str, notice_period_days, last_working_date, exit_reason, remarks, work_drive_link, initiated_by, exit_id))
        else:
            cur.execute("""
                INSERT INTO employee_exits 
                (employee_id, exit_type, notice_period, notice_period_days, last_working_date, exit_reason, remarks, work_drive_link, status, initiated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Initiated', %s) RETURNING id
            """, (str(emp_id), exit_type, notice_period_str, notice_period_days, last_working_date, exit_reason, remarks, work_drive_link, initiated_by))
            exit_id = cur.fetchone()['id']

        # Ensure FNF record exists
        cur.execute("SELECT id FROM employee_fnf_records WHERE exit_id = %s", (exit_id,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO employee_fnf_records (employee_id, exit_id) VALUES (%s, %s)
            """, (str(emp_id), exit_id))

        # Update work_drive_link on employee profile if provided
        if work_drive_link:
            cur.execute("UPDATE hrms_employees SET work_drive_link = %s WHERE id = %s", (work_drive_link, str(emp_id)))

        conn.commit()
        flash("Exit process initiated successfully.", "success")
    except Exception as e:
        print("Error initiating exit via DB, trying REST fallback:", e)
        if conn:
            try: conn.rollback()
            except: pass
        try:
            exit_row = supabase_rest.get_first_row("employee_exits", {"employee_id": f"eq.{emp_id}"})
            payload = {
                "employee_id": str(emp_id),
                "exit_type": exit_type,
                "notice_period": notice_period_str,
                "notice_period_days": notice_period_days,
                "last_working_date": last_working_date,
                "exit_reason": exit_reason,
                "remarks": remarks,
                "work_drive_link": work_drive_link,
                "status": "Initiated",
                "initiated_by": initiated_by
            }
            minimal_payload = {
                "employee_id": str(emp_id),
                "exit_type": exit_type,
                "last_working_date": last_working_date,
                "exit_reason": exit_reason,
                "remarks": remarks,
                "status": "Initiated",
                "initiated_by": initiated_by
            }
            
            if exit_row:
                exit_id = exit_row.get("id")
                try:
                    supabase_rest.update_rows("employee_exits", {"id": f"eq.{exit_id}"}, payload)
                except Exception as _rest_upd_err:
                    print("Full payload REST update failed, trying minimal payload:", _rest_upd_err)
                    supabase_rest.update_rows("employee_exits", {"id": f"eq.{exit_id}"}, minimal_payload)
            else:
                try:
                    new_exit = supabase_rest.insert_row("employee_exits", payload)
                except Exception as _rest_ins_err:
                    print("Full payload REST insert failed, trying minimal payload:", _rest_ins_err)
                    new_exit = supabase_rest.insert_row("employee_exits", minimal_payload)
                exit_id = new_exit.get("id") if new_exit else None

            if exit_id:
                fnf = supabase_rest.get_first_row("employee_fnf_records", {"exit_id": f"eq.{exit_id}"})
                if not fnf:
                    supabase_rest.insert_row("employee_fnf_records", {
                        "employee_id": str(emp_id),
                        "exit_id": exit_id
                    })
                if work_drive_link:
                    supabase_rest.update_rows("hrms_employees", {"id": f"eq.{emp_id}"}, {"work_drive_link": work_drive_link})
                flash("Exit process initiated successfully.", "success")
            else:
                flash(f"Could not initiate exit process.", "error")
        except Exception as rest_err:
            import traceback; traceback.print_exc()
            print("REST fallback for initiate exit failed:", rest_err)
            flash(f"Could not initiate exit process: {rest_err}", "error")
    finally:
        if conn:
            try: release_db(conn, cur)
            except: pass

    return redirect(f"/hrms/exit/manage/{emp_id}")


@exit_bp.route("/apply_resignation", methods=["POST"])
@login_required
def apply_resignation():
    emp_id = request.form.get("employee_id") or session.get("employee_id")
    
    if not emp_id and session.get("user_id"):
        conn_check, cur_check = None, None
        try:
            conn_check, cur_check = get_db(True)
            if conn_check:
                cur_check.execute("SELECT employee_id FROM hrms_users WHERE id = %s", (session.get("user_id"),))
                usr = cur_check.fetchone()
                if usr and usr.get("employee_id"):
                    emp_id = usr["employee_id"]
        except Exception as _usr_err:
            print("Error checking user employee_id:", _usr_err)
        finally:
            if conn_check:
                release_db(conn_check, cur_check)

    if not emp_id:
        flash("Employee record not linked to your account. Please contact HR.", "error")
        return redirect("/dashboard")

    # Guard: Prevent duplicate active exit applications
    conn_chk, cur_chk = None, None
    try:
        conn_chk, cur_chk = get_db(True)
        if conn_chk:
            cur_chk.execute("""
                SELECT id, status FROM employee_exits 
                WHERE employee_id::text = %s AND status NOT IN ('Exit Closed', 'Resignation Rejected')
                ORDER BY created_at DESC LIMIT 1
            """, (str(emp_id),))
            existing_exit = cur_chk.fetchone()
            if existing_exit:
                flash(f"You already have an active exit application in progress (Status: {existing_exit['status']}).", "warning")
                return redirect("/dashboard")
    except Exception as _ex_chk_err:
        print("Notice: Existing exit check error:", _ex_chk_err)
    finally:
        if conn_chk:
            release_db(conn_chk, cur_chk)

    last_working_date = request.form.get("last_working_date", "").strip() or None
    exit_reason = request.form.get("exit_reason", "").strip()
    remarks = request.form.get("remarks", "").strip()
    work_drive_link = request.form.get("work_drive_link", "").strip()
    if work_drive_link and not (work_drive_link.startswith("http://") or work_drive_link.startswith("https://")):
        work_drive_link = "https://" + work_drive_link
    notice_period_str = request.form.get("notice_period", "30 Days")

    conn, cur = get_db(True)
    try:
        cur.execute("""
            INSERT INTO employee_exits 
            (employee_id, exit_type, notice_period, last_working_date, exit_reason, remarks, work_drive_link, status, initiated_by)
            VALUES (%s, 'Resignation', %s, %s, %s, %s, %s, 'Resignation Applied', 'Employee') RETURNING id
        """, (str(emp_id), notice_period_str, last_working_date, exit_reason, remarks, work_drive_link))
        
        exit_id = cur.fetchone()['id']
        cur.execute("INSERT INTO employee_fnf_records (employee_id, exit_id) VALUES (%s, %s)", (str(emp_id), exit_id))
        
        if work_drive_link:
            cur.execute("UPDATE hrms_employees SET work_drive_link = %s WHERE id = %s", (work_drive_link, str(emp_id)))

        conn.commit()
        flash("Resignation submitted successfully. Pending HR review.", "success")
    except Exception as e:
        print("Error submitting resignation via DB, trying REST fallback:", e)
        if conn:
            try: conn.rollback()
            except: pass
        try:
            payload = {
                "employee_id": str(emp_id),
                "exit_type": "Resignation",
                "notice_period": notice_period_str,
                "last_working_date": last_working_date,
                "exit_reason": exit_reason,
                "remarks": remarks,
                "work_drive_link": work_drive_link,
                "status": "Resignation Applied",
                "initiated_by": "Employee"
            }
            try:
                new_exit = supabase_rest.insert_row("employee_exits", payload)
            except Exception as _rest_ins_err:
                print("REST full insert failed, trying minimal:", _rest_ins_err)
                new_exit = supabase_rest.insert_row("employee_exits", {
                    "employee_id": str(emp_id),
                    "exit_type": "Resignation",
                    "last_working_date": last_working_date,
                    "exit_reason": exit_reason,
                    "remarks": remarks,
                    "status": "Resignation Applied",
                    "initiated_by": "Employee"
                })

            if new_exit:
                supabase_rest.insert_row("employee_fnf_records", {
                    "employee_id": str(emp_id),
                    "exit_id": new_exit.get("id")
                })
                if work_drive_link:
                    supabase_rest.update_rows("hrms_employees", {"id": f"eq.{emp_id}"}, {"work_drive_link": work_drive_link})
                flash("Resignation submitted successfully. Pending HR review.", "success")
            else:
                flash(f"Could not submit resignation.", "error")
        except Exception as rest_err:
            import traceback; traceback.print_exc()
            print("REST fallback for apply resignation failed:", rest_err)
            flash(f"Could not submit resignation: {rest_err}", "error")
    finally:
        if conn:
            try: release_db(conn, cur)
            except: pass

    return redirect("/dashboard")


@exit_bp.route("/approve_resignation/<exit_id>", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def approve_resignation(exit_id):
    emp_id = request.form.get("employee_id")
    notice_period = request.form.get("notice_period", "30 Days")
    last_working_date = request.form.get("last_working_date")

    conn, cur = get_db(True)
    try:
        cur.execute("""
            UPDATE employee_exits
            SET status = 'Initiated', notice_period = %s, last_working_date = COALESCE(%s, last_working_date)
            WHERE id = %s
        """, (notice_period, last_working_date, exit_id))
        flash("Resignation approved and exit process initiated.", "success")
        conn.commit()
    except Exception as e:
        print("DB approve resignation failed, trying REST:", e)
        try:
            update_payload = {"status": "Initiated", "notice_period": notice_period}
            if last_working_date:
                update_payload["last_working_date"] = last_working_date
            supabase_rest.update_rows("employee_exits", {"id": f"eq.{exit_id}"}, update_payload)
            flash("Resignation approved and exit process initiated.", "success")
        except Exception as rest_err:
            flash("Failed to approve resignation.", "error")
    finally:
        if conn:
            try: release_db(conn, cur)
            except: pass

    return redirect(f"/hrms/exit/manage/{emp_id}")


@exit_bp.route("/reject_resignation/<exit_id>", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def reject_resignation(exit_id):
    emp_id = request.form.get("employee_id")
    remarks = request.form.get("remarks", "Resignation rejected by HR.").strip()
    conn, cur = get_db(True)
    try:
        cur.execute("UPDATE employee_exits SET status = 'Resignation Rejected', remarks = %s WHERE id = %s", (remarks, exit_id))
        flash("Resignation application rejected.", "info")
        conn.commit()
    except Exception as e:
        print("DB reject resignation failed, trying REST:", e)
        try:
            supabase_rest.update_rows("employee_exits", {"id": f"eq.{exit_id}"}, {"status": "Resignation Rejected", "remarks": remarks})
            flash("Resignation application rejected.", "info")
        except Exception as rest_err:
            flash("Failed to reject resignation.", "error")
    finally:
        if conn:
            try: release_db(conn, cur)
            except: pass

    return redirect(f"/hrms/exit/manage/{emp_id}")


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
            cur.execute("UPDATE hrms_employees SET status = 'Exited' WHERE id = %s", (str(emp_id),))
            
        conn.commit()
        flash(f"Exit status updated to {new_status}.", "success")
        conn.commit()
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
        if conn:
            try: release_db(conn, cur)
            except: pass

    return redirect(f"/hrms/exit/manage/{emp_id}")


@exit_bp.route("/update_info/<exit_id>", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def update_info(exit_id):
    emp_id = request.form.get("employee_id")
    exit_type = request.form.get("exit_type", "Resignation")
    notice_period = request.form.get("notice_period", "30 Days")
    last_working_date = request.form.get("last_working_date", "").strip() or None
    exit_reason = request.form.get("exit_reason", "").strip()
    remarks = request.form.get("remarks", "").strip()
    work_drive_link = request.form.get("work_drive_link", "").strip()
    if work_drive_link and not (work_drive_link.startswith("http://") or work_drive_link.startswith("https://")):
        work_drive_link = "https://" + work_drive_link

    conn, cur = get_db(True)
    try:
        cur.execute("""
            UPDATE employee_exits 
            SET exit_type = %s, notice_period = %s, last_working_date = %s, 
                exit_reason = %s, remarks = %s, work_drive_link = %s
            WHERE id = %s
        """, (exit_type, notice_period, last_working_date, exit_reason, remarks, work_drive_link, exit_id))
        
        if work_drive_link:
            cur.execute("UPDATE hrms_employees SET work_drive_link = %s WHERE id = %s", (work_drive_link, str(emp_id)))

        flash("Exit details and deliverables link updated.", "success")
        conn.commit()
    except Exception as e:
        print("DB update exit info failed, trying REST:", e)
        if conn:
            try: conn.rollback()
            except: pass
        try:
            supabase_rest.update_rows("employee_exits", {"id": f"eq.{exit_id}"}, {
                "exit_type": exit_type,
                "notice_period": notice_period,
                "last_working_date": last_working_date,
                "exit_reason": exit_reason,
                "remarks": remarks,
                "work_drive_link": work_drive_link
            })
            if work_drive_link:
                supabase_rest.update_rows("hrms_employees", {"id": f"eq.{emp_id}"}, {"work_drive_link": work_drive_link})
            flash("Exit details and deliverables link updated.", "success")
        except Exception as rest_err:
            flash("Failed to update exit details.", "error")
    finally:
        if conn:
            try: release_db(conn, cur)
            except: pass

    return redirect(f"/hrms/exit/manage/{emp_id}")


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
            SET pending_salary = %s, leave_encashment = %s, bonus = %s, 
                reimbursements = %s, reimbursement = %s, deductions = %s, 
                net_payable = %s, net_amount = %s
            WHERE exit_id = %s
        """, (pending_salary, leave_encashment, bonus, reimbursements, reimbursements, deductions, net_payable, net_payable, exit_id))
        flash("FNF calculation saved successfully.", "success")
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
                    "reimbursement": reimbursements,
                    "deductions": deductions,
                    "net_payable": net_payable,
                    "net_amount": net_payable
                }
            )
            flash("FNF calculation saved successfully.", "success")
        except Exception as rest_err:
            print("REST fallback for save FNF failed:", rest_err)
            flash("Could not save FNF calculation.", "error")
    finally:
        if conn:
            try: release_db(conn, cur)
            except: pass

    return redirect(f"/hrms/exit/manage/{emp_id}")


@exit_bp.route("/history")
@login_required
@role_required(["HR", "Admin"])
def exit_history():
    conn, cur = get_db(True)
    try:
        if not conn:
            raise Exception("Database connection failed")

        cur.execute("""
            SELECT e.*, emp.full_name, emp.employee_code, emp.department, 
                   emp.designation, emp.email, emp.joining_date, emp.work_drive_link as emp_work_drive
            FROM employee_exits e
            JOIN hrms_employees emp ON e.employee_id::text = emp.id::text
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
                emp = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{ex.get('employee_id')}"})
                if emp:
                    ex["full_name"] = emp.get("full_name") or "-"
                    ex["employee_code"] = emp.get("employee_code") or "-"
                    ex["department"] = emp.get("department") or "-"
                    ex["designation"] = emp.get("designation") or "-"
                    ex["email"] = emp.get("email") or "-"
                    ex["joining_date"] = emp.get("joining_date") or "-"
                    ex["emp_work_drive"] = emp.get("work_drive_link") or ""
                else:
                    ex["full_name"] = "-"
                    ex["employee_code"] = "-"
                    ex["department"] = "-"
                    ex["designation"] = "-"

            return render_template("hrms/exit/history.html", exits=exits)
        except Exception as rest_err:
            print("REST fallback for exit history failed:", rest_err)
            return redirect("/dashboard")
    finally:
        if conn:
            try: release_db(conn, cur)
            except: pass


@exit_bp.route("/delete/<exit_id>", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def delete_exit(exit_id):
    emp_id = request.form.get("employee_id")
    conn, cur = get_db(True)
    try:
        cur.execute("DELETE FROM employee_exit_documents WHERE exit_id = %s", (exit_id,))
        cur.execute("DELETE FROM employee_fnf_records WHERE exit_id = %s", (exit_id,))
        cur.execute("DELETE FROM employee_exits WHERE id = %s", (exit_id,))
        conn.commit()
        flash("Exit record deleted successfully.", "success")
    except Exception as e:
        print("DB delete exit failed, trying REST:", e)
        if conn:
            try: conn.rollback()
            except: pass
        try:
            supabase_rest.delete_rows("employee_exit_documents", {"exit_id": f"eq.{exit_id}"})
            supabase_rest.delete_rows("employee_fnf_records", {"exit_id": f"eq.{exit_id}"})
            supabase_rest.delete_rows("employee_exits", {"id": f"eq.{exit_id}"})
            flash("Exit record deleted successfully.", "success")
        except Exception as rest_err:
            print("REST delete exit failed:", rest_err)
            flash("Failed to delete exit record.", "error")
    finally:
        if conn:
            try: release_db(conn, cur)
            except: pass

    if emp_id:
        return redirect(f"/hrms/exit/manage/{emp_id}")
    return redirect("/hrms/exit/history")


@exit_bp.route("/dismiss_rejection/<exit_id>", methods=["POST"])
@login_required
def dismiss_rejection(exit_id):
    conn, cur = get_db(True)
    try:
        cur.execute("DELETE FROM employee_exits WHERE id = %s AND status = 'Resignation Rejected'", (exit_id,))
        conn.commit()
        flash("Rejection notice cleared.", "info")
    except Exception as e:
        try:
            supabase_rest.delete_rows("employee_exits", {"id": f"eq.{exit_id}", "status": "eq.Resignation Rejected"})
            flash("Rejection notice cleared.", "info")
        except Exception: pass
    finally:
        if conn:
            try: release_db(conn, cur)
            except: pass
    return redirect("/dashboard")


@exit_bp.route("/offboarding/<id>/update-checklist", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def update_checklist(id):
    emp_id = request.form.get("employee_id")
    asset_return_status = request.form.get("asset_return_status", "Pending")
    final_settlement_status = request.form.get("final_settlement_status", "Pending")
    access_revoked = request.form.get("access_revoked") == "true"
    notes = request.form.get("notes", "").strip()

    conn, cur = get_db(True)
    try:
        cur.execute("""
            UPDATE offboarding_cases
            SET asset_return_status = %s, final_settlement_status = %s, access_revoked = %s, notes = %s
            WHERE id = %s
        """, (asset_return_status, final_settlement_status, access_revoked, notes, id))

        if access_revoked:
            # Delete credentials from hrms_users to revoke HRMS login access
            cur.execute("DELETE FROM hrms_users WHERE employee_id = %s", (str(emp_id),))

        conn.commit()
        flash("Offboarding checklist updated successfully.", "success")
        release_db(conn, cur)
    except Exception as e:
        print("Error updating offboarding checklist via DB, trying REST:", e)
        if conn:
            try: conn.rollback()
            except: pass
        try:
            supabase_rest.update_row("offboarding_cases", {"id": f"eq.{id}"}, {
                "asset_return_status": asset_return_status,
                "final_settlement_status": final_settlement_status,
                "access_revoked": access_revoked,
                "notes": notes
            })
            if access_revoked:
                supabase_rest.delete_rows("hrms_users", {"employee_id": f"eq.{emp_id}"})
            flash("Offboarding checklist updated successfully (REST).", "success")
        except Exception as rest_err:
            print("REST fallback for update offboarding checklist failed:", rest_err)
            flash("Failed to update checklist.", "error")
            
    return redirect(f"/hrms/exit/manage/{emp_id}")


@exit_bp.route("/offboarding/<id>/schedule-exit-interview", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def schedule_exit_interview(id):
    emp_id = request.form.get("employee_id")
    date_str = request.form.get("date")
    time_str = request.form.get("time")
    duration = int(request.form.get("duration_minutes", 30))
    location = request.form.get("location", "Virtual / Office")

    if not all([date_str, time_str]):
        flash("Date and Time are required.", "error")
        return redirect(f"/hrms/exit/manage/{emp_id}")

    import pytz, uuid
    from datetime import timedelta
    from icalendar import Calendar, Event, vCalAddress, vText
    from utils.mailer import send_meeting_invite, SENDER_EMAIL, COMPANY_NAME

    conn, cur = get_db(True)
    try:
        # Get employee email
        cur.execute("SELECT full_name, email FROM hrms_employees WHERE id = %s", (str(emp_id),))
        emp = cur.fetchone()
        if not emp:
            raise Exception("Employee record not found")

        # Parse schedule date and time
        dtstart_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        local_tz = pytz.timezone("Asia/Kolkata")
        dtstart = local_tz.localize(dtstart_naive)
        dtend = dtstart + timedelta(minutes=duration)

        ics_uid = f"exit-interview-{uuid.uuid4()}"
        ics_sequence = 0

        # Save to candidate_interviews table
        cur.execute("""
            INSERT INTO candidate_interviews (employee_id, scheduled_at, duration_minutes, location, ics_uid, ics_sequence, status, scheduled_by)
            VALUES (%s, %s, %s, %s, %s, %s, 'Scheduled', %s)
        """, (str(emp_id), dtstart, duration, location, ics_uid, ics_sequence, session.get("employee_name", "HR")))

        # Update offboarding_cases exit interview status
        cur.execute("UPDATE offboarding_cases SET exit_interview_status = 'Scheduled' WHERE id = %s", (id,))

        # Generate .ics attachment
        cal = Calendar()
        cal.add('prodid', f'-//{COMPANY_NAME} HRMS//EN')
        cal.add('version', '2.0')
        cal.add('method', 'REQUEST')

        event = Event()
        event.add('uid', ics_uid)
        event.add('dtstamp', datetime.utcnow().replace(tzinfo=pytz.UTC))
        event.add('dtstart', dtstart)
        event.add('dtend', dtend)
        event.add('summary', f"Exit Interview — {emp['full_name']}")
        event.add('location', location)
        event.add('sequence', ics_sequence)
        event.add('status', 'CONFIRMED')

        organizer = vCalAddress(f'MAILTO:{SENDER_EMAIL}')
        organizer.params['cn'] = vText(f"{COMPANY_NAME} HR")
        event['organizer'] = organizer
        cal.add_component(event)
        ics_bytes = cal.to_ical()

        # Send email with invite
        html_body = f"""
        <p>Hi {emp['full_name']},</p>
        <p>An exit interview has been scheduled for you. Details are below:</p>
        <p>
            <strong>Date & Time:</strong> {date_str} {time_str} (Asia/Kolkata)<br>
            <strong>Duration:</strong> {duration} Minutes<br>
            <strong>Location/Link:</strong> {location}
        </p>
        <p>Please accept the attached calendar invite file to add this event to your calendar.</p>
        """
        send_meeting_invite(
            to_email=emp["email"],
            to_name=emp["full_name"],
            subject=f"Exit Interview Schedule — {COMPANY_NAME}",
            html_body=html_body,
            ics_bytes=ics_bytes
        )

        conn.commit()
        flash("Exit Interview scheduled and calendar invitation sent.", "success")
        release_db(conn, cur)
    except Exception as e:
        print("Error scheduling exit interview via DB, trying REST fallback:", e)
        if conn:
            try: conn.rollback()
            except: pass
        try:
            # REST Fallback
            emp = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{emp_id}"})
            if emp:
                dtstart_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                local_tz = pytz.timezone("Asia/Kolkata")
                dtstart = local_tz.localize(dtstart_naive)
                dtend = dtstart + timedelta(minutes=duration)
                ics_uid = f"exit-interview-{uuid.uuid4()}"
                
                # Insert interview
                supabase_rest.insert_row("candidate_interviews", {
                    "employee_id": str(emp_id),
                    "scheduled_at": dtstart.isoformat(),
                    "duration_minutes": duration,
                    "location": location,
                    "ics_uid": ics_uid,
                    "ics_sequence": 0,
                    "status": "Scheduled",
                    "scheduled_by": session.get("employee_name", "HR")
                })
                
                # Update offboarding status
                supabase_rest.update_rows("offboarding_cases", {"id": f"eq.{id}"}, {
                    "exit_interview_status": "Scheduled"
                })

                # Generate .ics attachment
                cal = Calendar()
                cal.add('prodid', f'-//ANTI.AI HRMS//EN')
                cal.add('version', '2.0')
                cal.add('method', 'REQUEST')

                event = Event()
                event.add('uid', ics_uid)
                event.add('dtstamp', datetime.utcnow().replace(tzinfo=pytz.UTC))
                event.add('dtstart', dtstart)
                event.add('dtend', dtend)
                event.add('summary', f"Exit Interview — {emp['full_name']}")
                event.add('location', location)
                event.add('sequence', 0)
                event.add('status', 'CONFIRMED')

                organizer = vCalAddress(f'MAILTO:{SENDER_EMAIL}')
                organizer.params['cn'] = vText("ANTI.AI HR")
                event['organizer'] = organizer
                cal.add_component(event)
                ics_bytes = cal.to_ical()

                html_body = f"""
                <p>Hi {emp['full_name']},</p>
                <p>An exit interview has been scheduled for you. Details are below:</p>
                <p>
                    <strong>Date & Time:</strong> {date_str} {time_str} (Asia/Kolkata)<br>
                    <strong>Duration:</strong> {duration} Minutes<br>
                    <strong>Location/Link:</strong> {location}
                </p>
                <p>Please accept the attached calendar invite file to add this event to your calendar.</p>
                """
                send_meeting_invite(
                    to_email=emp["email"],
                    to_name=emp["full_name"],
                    subject="Exit Interview Schedule — ANTI.AI",
                    html_body=html_body,
                    ics_bytes=ics_bytes
                )
                flash("Exit Interview scheduled and calendar invitation sent (REST).", "success")
        except Exception as rest_err:
            print("REST fallback for schedule exit interview failed:", rest_err)
            flash("Failed to schedule exit interview.", "error")
    finally:
        if conn:
            try: release_db(conn, cur)
            except: pass

    return redirect(f"/hrms/exit/manage/{emp_id}")


@exit_bp.route("/offboarding/<id>/complete-exit-interview", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def complete_exit_interview(id):
    emp_id = request.form.get("employee_id")
    conn, cur = get_db(True)
    try:
        cur.execute("UPDATE offboarding_cases SET exit_interview_status = 'Completed' WHERE id = %s", (id,))
        
        # Also mark matching scheduled interviews as completed
        cur.execute("""
            UPDATE candidate_interviews 
            SET status = 'Completed' 
            WHERE employee_id = %s AND status = 'Scheduled'
        """, (str(emp_id),))
        
        conn.commit()
        flash("Exit Interview marked as Completed.", "success")
        release_db(conn, cur)
    except Exception as e:
        print("Error completing exit interview via DB, trying REST:", e)
        if conn:
            try: conn.rollback()
            except: pass
        try:
            supabase_rest.update_rows("offboarding_cases", {"id": f"eq.{id}"}, {
                "exit_interview_status": "Completed"
            })
            # Try updating scheduled interviews
            # REST doesn't easily support bulk update of status, so update offboarding status is enough
            flash("Exit Interview marked as Completed (REST).", "success")
        except Exception as rest_err:
            print("REST fallback for complete exit interview failed:", rest_err)
            flash("Failed to complete exit interview.", "error")
            
    return redirect(f"/hrms/exit/manage/{emp_id}")