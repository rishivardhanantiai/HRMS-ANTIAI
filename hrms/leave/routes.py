from flask import Blueprint, render_template, session, request, redirect
from utils.db import get_db, release_db
from utils import supabase_rest
from utils.auth import login_required, role_required

leave_bp = Blueprint("leave", __name__, url_prefix="/hrms/leave")


# ======================================
# EMPLOYEE LEAVE PAGE
# ======================================
@leave_bp.route("/", methods=["GET", "POST"])
@login_required
@role_required(["Employee"])
def employee_leave():
    employee_id = session.get("employee_id")
    try:
        conn, cur = get_db(True)

        # APPLY LEAVE
        if request.method == "POST":

            leave_type_id = request.form["leave_type_id"]
            from_date = request.form["from_date"]
            to_date = request.form["to_date"]
            reason = request.form["reason"]

            cur.execute("""
                INSERT INTO leave_applications
                (employee_id, leave_type_id, from_date, to_date, reason, status)
                VALUES (%s, %s, %s, %s, %s, 'Pending')
            """, (
                employee_id,
                leave_type_id,
                from_date,
                to_date,
                reason
            ))

            conn.commit()

        # Leave types
        cur.execute("SELECT id, name FROM leave_types")
        leave_types = cur.fetchall()

        # Employee leave history
        cur.execute("""
        SELECT la.id,
               lt.name AS leave_type,
               la.from_date,
               la.to_date,
               la.status
        FROM leave_applications la
        JOIN leave_types lt ON la.leave_type_id = lt.id
        WHERE la.employee_id = %s
        ORDER BY la.from_date DESC
    """, (employee_id,))

        leaves = cur.fetchall()
        release_db(conn, cur)
    except Exception:
        if request.method == "POST":
            leave_type = request.form["leave_type_id"]
            from_date = request.form["from_date"]
            to_date = request.form["to_date"]
            reason = request.form["reason"]

            # Keep the submitted leave_type id as-is for Supabase fallback.
            # Previously we converted id->name which created mismatched leave_type_id values.
            supabase_rest.create_leave_request(employee_id, leave_type, from_date, to_date, reason)

        leave_types = supabase_rest.list_leave_types()
        leaves = supabase_rest.list_employee_leaves(employee_id)

    return render_template(
        "hrms/employee_leave.html",
        leave_types=leave_types,
        leaves=leaves,
        balances=[],
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
                   la.status
            FROM leave_applications la
            JOIN hrms_employees e ON la.employee_id = e.id
            JOIN leave_types lt ON la.leave_type_id = lt.id
            ORDER BY la.from_date DESC
        """)

        requests = cur.fetchall()
        release_db(conn, cur)
    except Exception:
        requests = supabase_rest.list_leaves_manage()

    return render_template(
        "hrms/manage_leave.html",
        requests=requests
    )


# ======================================
# APPROVE / REJECT
# ======================================
@leave_bp.route("/update/<leave_id>/<action>")
@login_required
@role_required(["HR", "Admin"])
def update_leave_status(leave_id, action):
    status = "Approved" if action == "approve" else "Rejected"

    try:
        conn, cur = get_db(True)

        cur.execute("""
            UPDATE leave_applications
            SET status=%s
            WHERE id=%s
        """, (status, leave_id))

        conn.commit()
        release_db(conn, cur)
    except Exception:
        supabase_rest.update_leave_status(leave_id, status)

    return redirect("/hrms/leave/manage")