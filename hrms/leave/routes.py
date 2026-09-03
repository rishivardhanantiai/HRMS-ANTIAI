from flask import Blueprint, render_template, session, request, redirect, flash
from utils.db import get_db, release_db
from utils import supabase_rest
from utils.auth import login_required, role_required
from hrms.notifications.routes import create_notification

leave_bp = Blueprint("leave", __name__, url_prefix="/hrms/leave")

# Automatic database migration/upgrade
def run_leave_migration():
    try:
        conn, cur = get_db()
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='leave_types' AND column_name='annual_entitlement'
        """)
        if not cur.fetchone():
            cur.execute("ALTER TABLE leave_types ADD COLUMN annual_entitlement INTEGER DEFAULT 15")
            conn.commit()
            print("DB Migration: Added column annual_entitlement to leave_types.")
    except Exception as e:
        print("Leave DB Migration Error:", e)
    finally:
        try:
            release_db(conn, cur)
        except Exception:
            pass

try:
    run_leave_migration()
except Exception as _migration_err:
    print("Skipping leave migration on startup (DB may not be ready):", _migration_err)


# ======================================
# LEAVE BALANCE CALCULATOR ENGINE
# ======================================
def get_leave_balances(employee_id):
    from datetime import date
    balances = []
    conn = None
    cur = None
    try:
        conn, cur = get_db(True)
        # Fetch employee's joining date
        cur.execute("SELECT joining_date FROM hrms_employees WHERE id = %s", (employee_id,))
        emp = cur.fetchone()
        joining_date = emp["joining_date"] if emp and emp["joining_date"] else date.today()
            
        # Calculate months since joining
        today = date.today()
        months_worked = (today.year - joining_date.year) * 12 + today.month - joining_date.month
        months_worked = max(1, months_worked)
        
        # Fetch leave types
        cur.execute("SELECT id, name, annual_entitlement FROM leave_types ORDER BY name")
        leave_types = cur.fetchall()
        
        # Approved used days
        cur.execute("""
            SELECT leave_type_id, SUM(to_date - from_date + 1) AS used_days
            FROM leave_applications
            WHERE employee_id = %s AND status = 'Approved'
            GROUP BY leave_type_id
        """, (employee_id,))
        used_raw = cur.fetchall()
        used_map = {row["leave_type_id"]: int(row["used_days"]) for row in used_raw if row["used_days"]}
        
        for lt in leave_types:
            annual = lt["annual_entitlement"] if lt["annual_entitlement"] is not None else 15
            accrued = min(annual, round((annual / 12.0) * months_worked))
            used = used_map.get(lt["id"], 0)
            remaining = max(0, accrued - used)
            balances.append({
                "id": lt["id"],
                "name": lt["name"],
                "total_allocated": accrued,
                "used": used,
                "remaining": remaining
            })
    except Exception as e:
        print("Leave balance calculation error, trying REST fallback:", e)
        if conn and cur:
            try:
                release_db(conn, cur)
            except Exception:
                pass
        try:
            emp = supabase_rest.get_first_row("hrms_employees", {"select": "joining_date", "id": f"eq.{employee_id}"})
            joining_date = date.today()
            if emp and emp.get("joining_date"):
                try:
                    joining_date = date.fromisoformat(str(emp["joining_date"])[:10])
                except:
                    pass
            
            today = date.today()
            months_worked = (today.year - joining_date.year) * 12 + today.month - joining_date.month
            months_worked = max(1, months_worked)
            
            leave_types = supabase_rest.get_rows("leave_types", {"select": "id,name,annual_entitlement", "order": "name.asc"})
            
            used_raw = supabase_rest.get_rows("leave_applications", {
                "select": "leave_type_id,from_date,to_date",
                "employee_id": f"eq.{employee_id}",
                "status": "eq.Approved"
            })
            
            used_map = {}
            for row in used_raw:
                lt_id = row.get("leave_type_id")
                f_str = row.get("from_date")
                t_str = row.get("to_date")
                if lt_id and f_str and t_str:
                    try:
                        fd = date.fromisoformat(str(f_str)[:10])
                        td = date.fromisoformat(str(t_str)[:10])
                        days = (td - fd).days + 1
                        used_map[lt_id] = used_map.get(lt_id, 0) + days
                    except:
                        pass
            
            for lt in leave_types:
                annual = lt.get("annual_entitlement")
                annual = annual if annual is not None else 15
                accrued = min(annual, round((annual / 12.0) * months_worked))
                used = used_map.get(lt.get("id"), 0)
                remaining = max(0, accrued - used)
                balances.append({
                    "id": lt.get("id"),
                    "name": lt.get("name"),
                    "total_allocated": accrued,
                    "used": used,
                    "remaining": remaining
                })
        except Exception as rest_err:
            print("REST fallback for leave balance calculation failed:", rest_err)
    finally:
        if conn and cur:
            try:
                release_db(conn, cur)
            except Exception:
                pass
    return balances


# ======================================
# EMPLOYEE LEAVE PAGE
# ======================================
@leave_bp.route("/", methods=["GET", "POST"])
@login_required
@role_required(["Employee"])
def employee_leave():
    employee_id = session.get("employee_id")
    balances = get_leave_balances(employee_id)
    
    try:
        conn, cur = get_db(True)

        # APPLY LEAVE
        if request.method == "POST":
            leave_type_id = request.form.get("leave_type_id")
            if not leave_type_id:
                flash("Leave Type is mandatory.", "error")
                return redirect("/hrms/leave/")
            
            from_date_str = request.form["from_date"]
            to_date_str = request.form["to_date"]
            reason = request.form["reason"]

            if from_date_str > to_date_str:
                flash("To Date cannot be before From Date.", "error")
                return redirect("/hrms/leave/")

            # Double check leave type balance
            remaining_balance = 15
            for b in balances:
                if str(b["id"]) == str(leave_type_id):
                    remaining_balance = b["remaining"]
                    break

            from datetime import datetime
            fd = datetime.strptime(from_date_str, "%Y-%m-%d")
            td = datetime.strptime(to_date_str, "%Y-%m-%d")
            days_requested = (td - fd).days + 1

            if days_requested > remaining_balance:
                flash(f"Insufficient leave balance. You requested {days_requested} days but only have {remaining_balance} remaining.", "error")
                return redirect("/hrms/leave/")

            cur.execute("""
                INSERT INTO leave_applications
                (employee_id, leave_type_id, from_date, to_date, reason, status)
                VALUES (%s, %s, %s, %s, %s, 'Pending')
            """, (
                employee_id,
                leave_type_id,
                from_date_str,
                to_date_str,
                reason
            ))

            conn.commit()
            employee_name = session.get("employee_name") or "An employee"
            create_notification(
                recipient_role="HR",
                notif_type="leave_applied",
                message=f"{employee_name} requested leave from {from_date_str} to {to_date_str}",
                link="/hrms/leave/manage"
            )
            flash("Leave applied successfully.", "success")
            return redirect("/hrms/leave/")

        # Leave types
        cur.execute("SELECT id, name FROM leave_types")
        leave_types = cur.fetchall()

        # Employee leave history
        cur.execute("""
            SELECT la.id,
                   lt.name AS leave_type,
                   la.from_date,
                   la.to_date,
                   la.status,
                   la.reason,
                   (la.to_date - la.from_date + 1) AS days
            FROM leave_applications la
            JOIN leave_types lt ON la.leave_type_id = lt.id
            WHERE la.employee_id = %s
            ORDER BY la.from_date DESC
        """, (employee_id,))

        leaves = cur.fetchall()
        release_db(conn, cur)
    except Exception as e:
        print("Employee leave error:", e)
        if request.method == "POST":
            leave_type = request.form.get("leave_type_id")
            from_date = request.form["from_date"]
            to_date = request.form["to_date"]
            reason = request.form["reason"]
            supabase_rest.create_leave_request(employee_id, leave_type, from_date, to_date, reason)
            employee_name = session.get("employee_name") or "An employee"
            create_notification(
                recipient_role="HR",
                notif_type="leave_applied",
                message=f"{employee_name} requested leave from {from_date} to {to_date}",
                link="/hrms/leave/manage"
            )

        leave_types = supabase_rest.list_leave_types()
        leaves = supabase_rest.list_employee_leaves(employee_id)

    return render_template(
        "hrms/employee_leave.html",
        leave_types=leave_types,
        leaves=leaves,
        balances=balances,
    )


# ======================================
# HR / ADMIN MANAGE LEAVE
# ======================================
@leave_bp.route("/manage")
@login_required
@role_required(["HR", "Admin"])
def manage_leave():
    try:
        conn, cur = get_db(True)

        cur.execute("""
            SELECT la.id,
                   e.full_name,
                   lt.name AS type,
                   la.from_date,
                   la.to_date,
                   la.status,
                   la.reason,
                   (la.to_date - la.from_date + 1) AS days
            FROM leave_applications la
            JOIN hrms_employees e ON la.employee_id = e.id
            JOIN leave_types lt ON la.leave_type_id = lt.id
            ORDER BY la.from_date DESC
        """)

        requests = cur.fetchall()
        release_db(conn, cur)
    except Exception as e:
        print("Error fetching requests:", e)
        requests = supabase_rest.list_leaves_manage()

    return render_template(
        "hrms/manage_leave.html",
        requests=requests
    )


# ======================================
# APPROVE / REJECT (SECURE POST METHOD)
# ======================================
@leave_bp.route("/update/<leave_id>", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def update_leave_status(leave_id):
    action = request.form.get("action")
    status = "Approved" if action == "approve" else "Rejected"

    try:
        conn, cur = get_db(True)

        # Get employee email and employee_id for simulation and notification
        cur.execute("""
            SELECT e.email, e.full_name, la.from_date, la.to_date, la.employee_id 
            FROM leave_applications la
            JOIN hrms_employees e ON la.employee_id = e.id
            WHERE la.id = %s
        """, (leave_id,))
        emp_details = cur.fetchone()

        cur.execute("""
            UPDATE leave_applications
            SET status=%s
            WHERE id=%s
        """, (status, leave_id))

        conn.commit()

        if emp_details:
            create_notification(
                recipient_role="Employee",
                notif_type="leave_resolved",
                message=f"Your leave request from {emp_details['from_date']} to {emp_details['to_date']} was {status.lower()}",
                link="/hrms/leave/",
                employee_id=emp_details["employee_id"]
            )
            
            print(f"--- EMAIL AUTOMATION ---")
            print(f"To: {emp_details['email']}")
            print(f"Subject: Leave Request {status} - {emp_details['full_name']}")
            print(f"Dear {emp_details['full_name']},\nYour leave request from {emp_details['from_date']} to {emp_details['to_date']} has been {status}.")
            print(f"------------------------")
            flash(f"Leave request has been {status}. Notification email simulated.", "success")

        release_db(conn, cur)

    except Exception as e:
        print("Error updating leave status:", e)
        try:
            supabase_rest.update_leave_status(leave_id, status)
            leave_row = supabase_rest.get_first_row("leave_applications", {"id": f"eq.{leave_id}"})
            if leave_row:
                emp_id = leave_row.get("employee_id")
                emp_details = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{emp_id}"})
                if emp_details:
                    create_notification(
                        recipient_role="Employee",
                        notif_type="leave_resolved",
                        message=f"Your leave request from {leave_row.get('from_date')} to {leave_row.get('to_date')} was {status.lower()}",
                        link="/hrms/leave/",
                        employee_id=emp_id
                    )
        except Exception as rest_notif_err:
            print("REST notification fallback failed:", rest_notif_err)
        flash(f"Leave status updated to {status}.", "success")

    return redirect("/hrms/leave/manage")


# ======================================
# HR: CONFIGURE LEAVE TYPES (CRUD PANEL)
# ======================================
@leave_bp.route("/configure", methods=["GET", "POST"])
@login_required
@role_required(["HR", "Admin"])
def configure_leaves():
    try:
        conn, cur = get_db(True)

        if request.method == "POST":
            leave_id = request.form.get("id", "").strip()
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            annual_entitlement = int(request.form.get("annual_entitlement", 15))

            if not name:
                flash("Leave Type name is required.", "error")
                return redirect("/hrms/leave/configure")

            if leave_id:
                # Update
                cur.execute("""
                    UPDATE leave_types
                    SET name=%s, description=%s, annual_entitlement=%s
                    WHERE id=%s
                """, (name, description, annual_entitlement, leave_id))
                flash("Leave Type updated successfully.", "success")
            else:
                # Create
                cur.execute("""
                    INSERT INTO leave_types (name, description, annual_entitlement)
                    VALUES (%s, %s, %s)
                """, (name, description, annual_entitlement))
                flash("Leave Type created successfully.", "success")

            conn.commit()
            release_db(conn, cur)
            return redirect("/hrms/leave/configure")

        cur.execute("SELECT id, name, description, annual_entitlement FROM leave_types ORDER BY name")
        leave_types = cur.fetchall()
        release_db(conn, cur)
    except Exception as e:
        print("Error configuring leaves, trying REST fallback:", e)
        if conn:
            try:
                release_db(conn, cur)
            except:
                pass
        
        try:
            if request.method == "POST":
                leave_id = request.form.get("id", "").strip()
                name = request.form.get("name", "").strip()
                description = request.form.get("description", "").strip()
                annual_entitlement = int(request.form.get("annual_entitlement", 15))

                if not name:
                    flash("Leave Type name is required.", "error")
                    return redirect("/hrms/leave/configure")

                if leave_id:
                    supabase_rest.update_rows(
                        "leave_types",
                        {"id": f"eq.{leave_id}"},
                        {
                            "name": name,
                            "description": description,
                            "annual_entitlement": annual_entitlement
                        }
                    )
                    flash("Leave Type updated successfully.", "success")
                else:
                    supabase_rest.insert_row(
                        "leave_types",
                        {
                            "name": name,
                            "description": description,
                            "annual_entitlement": annual_entitlement
                        }
                    )
                    flash("Leave Type created successfully.", "success")
                return redirect("/hrms/leave/configure")
                
            leave_types = supabase_rest.get_rows("leave_types", {"select": "id,name,description,annual_entitlement", "order": "name.asc"})
        except Exception as rest_err:
            print("REST fallback for configure leaves failed:", rest_err)
            leave_types = []

    return render_template("hrms/configure_leaves.html", leave_types=leave_types)


@leave_bp.route("/configure/delete/<leave_id>", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def delete_leave_type(leave_id):
    try:
        conn, cur = get_db(True)
        cur.execute("DELETE FROM leave_types WHERE id = %s", (leave_id,))
        conn.commit()
        release_db(conn, cur)
        flash("Leave type deleted.", "success")
    except Exception as e:
        print("Error deleting leave type, trying REST fallback:", e)
        if conn:
            try:
                release_db(conn, cur)
            except:
                pass
        try:
            success = supabase_rest.delete_rows("leave_types", {"id": f"eq.{leave_id}"})
            if success:
                flash("Leave type deleted.", "success")
            else:
                flash("Could not delete leave type.", "error")
        except Exception as rest_err:
            print("REST fallback for deleting leave type failed:", rest_err)
            flash("Could not delete leave type.", "error")
    return redirect("/hrms/leave/configure")


# ======================================
# API: PENDING LEAVES (FOR DASHBOARD)
# ======================================
@leave_bp.route("/api/pending")
@login_required
@role_required(["HR", "Admin"])
def api_pending_leaves():
    try:
        conn, cur = get_db(True)
        cur.execute("""
            SELECT la.id,
                   e.full_name AS employee_name,
                   lt.name AS leave_type,
                   la.from_date,
                   la.to_date,
                   la.reason,
                   la.created_at
            FROM leave_applications la
            JOIN hrms_employees e ON la.employee_id = e.id
            JOIN leave_types lt ON la.leave_type_id = lt.id
            WHERE la.status = 'Pending'
            ORDER BY la.created_at DESC
        """)
        
        requests = cur.fetchall()
        release_db(conn, cur)
        
        for r in requests:
            if r.get('from_date'): r['from_date'] = str(r['from_date'])
            if r.get('to_date'): r['to_date'] = str(r['to_date'])
            if r.get('created_at'): r['created_at'] = str(r['created_at'])
            
        return {"requests": requests}, 200
    except Exception:
        requests = supabase_rest.list_leaves_manage()
        pending = [r for r in requests if str(r.get("status", "")).lower() == "pending"]
        
        for r in pending:
            r['employee_name'] = r.get('full_name')
            r['leave_type'] = r.get('type')
            
        return {"requests": pending}, 200


@leave_bp.route("/holidays", methods=["GET"])
@login_required
def holidays():
    from datetime import date
    conn, cur = None, None
    holidays = []
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB Connection")
        cur.execute("SELECT * FROM company_holidays ORDER BY holiday_date ASC")
        holidays = cur.fetchall()
        release_db(conn, cur)
    except Exception as e:
        print("Error fetching holidays via DB, trying REST fallback:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            holidays = supabase_rest.get_rows("company_holidays", {"order": "holiday_date.asc"})
        except Exception as rest_err:
            print("REST fallback for holidays failed:", rest_err)
            
    # Normalize holiday_date to actual date objects
    today = date.today()
    for h in holidays:
        h_date = h.get("holiday_date")
        if isinstance(h_date, str):
            try:
                from datetime import datetime
                h_date = datetime.strptime(h_date[:10], "%Y-%m-%d").date()
                h["holiday_date"] = h_date
            except:
                pass
            
    return render_template("hrms/holidays.html", holidays=holidays, today=today)


@leave_bp.route("/holidays/add", methods=["POST"])
@login_required
@role_required(["Admin"])
def add_holiday():
    name = request.form.get("name")
    date_str = request.form.get("holiday_date")
    
    if not name or not date_str:
        flash("Name and Date are required.", "error")
        return redirect("/hrms/leave/holidays")
        
    conn, cur = get_db()
    try:
        if not conn:
            raise Exception("No DB Connection")
        cur.execute("""
            INSERT INTO company_holidays (name, holiday_date)
            VALUES (%s, %s)
        """, (name, date_str))
        conn.commit()
        flash("Holiday added successfully.", "success")
    except Exception as e:
        print("DB Add Holiday Error:", e)
        try:
            supabase_rest.insert_row("company_holidays", {
                "name": name,
                "holiday_date": date_str
            })
            flash("Holiday added successfully (REST).", "success")
        except Exception as rest_err:
            print("REST Add Holiday Error:", rest_err)
            flash("Failed to add holiday.", "error")
    finally:
        if conn: release_db(conn, cur)
        
    return redirect("/hrms/leave/holidays")


@leave_bp.route("/holidays/<id>/delete", methods=["POST"])
@login_required
@role_required(["Admin"])
def delete_holiday(id):
    conn, cur = get_db()
    try:
        if not conn:
            raise Exception("No DB Connection")
        cur.execute("DELETE FROM company_holidays WHERE id=%s", (id,))
        conn.commit()
        flash("Holiday deleted successfully.", "success")
    except Exception as e:
        print("DB Delete Holiday Error:", e)
        try:
            supabase_rest.delete_rows("company_holidays", {"id": f"eq.{id}"})
            flash("Holiday deleted successfully (REST).", "success")
        except Exception as rest_err:
            print("REST Delete Holiday Error:", rest_err)
            flash("Failed to delete holiday.", "error")
    finally:
        if conn: release_db(conn, cur)
        
    return redirect("/hrms/leave/holidays")