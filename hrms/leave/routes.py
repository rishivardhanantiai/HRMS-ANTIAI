from flask import Blueprint, render_template, session, request, redirect, flash
from utils.db import get_db, release_db
from utils import supabase_rest
from utils.auth import login_required, role_required

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

run_leave_migration()


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
        print("Leave balance calculation error:", e)
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

        # Get employee email for simulation
        cur.execute("""
            SELECT e.email, e.full_name, la.from_date, la.to_date 
            FROM leave_applications la
            JOIN hrms_employees e ON la.employee_id = e.id
            WHERE la.id = %s
        """, (leave_id,))
        emp_details = cur.fetchone()

        cur.execute("""
            UPDATE leave_applications
            SET status=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
        """, (status, leave_id))

        conn.commit()
        release_db(conn, cur)

        if emp_details:
            print(f"--- EMAIL AUTOMATION ---")
            print(f"To: {emp_details['email']}")
            print(f"Subject: Leave Request {status} - {emp_details['full_name']}")
            print(f"Dear {emp_details['full_name']},\nYour leave request from {emp_details['from_date']} to {emp_details['to_date']} has been {status}.")
            print(f"------------------------")
            flash(f"Leave request has been {status}. Notification email simulated.", "success")

    except Exception as e:
        print("Error updating leave status:", e)
        supabase_rest.update_leave_status(leave_id, status)
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
            return redirect("/hrms/leave/configure")

        cur.execute("SELECT id, name, description, annual_entitlement FROM leave_types ORDER BY name")
        leave_types = cur.fetchall()
        release_db(conn, cur)
    except Exception as e:
        print("Error configuring leaves:", e)
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
        print("Error deleting leave type:", e)
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