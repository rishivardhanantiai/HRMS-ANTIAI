from flask import Blueprint, render_template, request, jsonify, session, redirect
from utils.auth import login_required
from utils.db import get_db, release_db
from datetime import date, datetime, timedelta
import calendar

attendance_bp = Blueprint("attendance", __name__, url_prefix="/hrms")

# =========================================================
# MAIN ATTENDANCE PAGE
# =========================================================
@attendance_bp.route("/attendance")
@login_required
def attendance_page():

    role = session.get("role")
    employee_id = session.get("employee_id")

    selected_month = request.args.get("month")
    today = date.today()

    if selected_month:
        year, month = map(int, selected_month.split("-"))
    else:
        year = today.year
        month = today.month

    conn, cur = get_db(True)

    # Auto lock previous months
    first_day_current_month = today.replace(day=1)

    cur.execute("""
        UPDATE hrms_attendance
        SET is_locked = TRUE
        WHERE attendance_date < %s
    """, (first_day_current_month,))
    conn.commit()

    # ================= EMPLOYEE VIEW =================
    if role == "Employee":

        cur.execute("""
            SELECT attendance_date,
                   status,
                   check_in_time,
                   check_out_time,
                   duration
            FROM hrms_attendance
            WHERE employee_id = %s
              AND EXTRACT(MONTH FROM attendance_date) = %s
              AND EXTRACT(YEAR FROM attendance_date) = %s
            ORDER BY attendance_date
        """, (employee_id, month, year))

        records = cur.fetchall()

        attendance_map = {
            r["attendance_date"]: r for r in records
        }

        cal = calendar.monthcalendar(year, month)

        release_db(conn, cur)

        return render_template(
            "hrms/employee_attendance.html",
            calendar_data=cal,
            attendance_map=attendance_map,
            year=year,
            month=month,
            date=date
        )

    # ================= HR VIEW =================
    elif role in ["HR", "Admin"]:

        cur.execute("""
            SELECT 
                a.employee_id,
                a.attendance_date,
                a.status,
                a.check_in_time,
                a.check_out_time,
                a.duration,
                a.is_locked,
                e.full_name
            FROM hrms_attendance a
            JOIN hrms_employees e ON a.employee_id = e.id
            ORDER BY a.attendance_date DESC
        """)

        records = cur.fetchall()

        release_db(conn, cur)

        return render_template(
            "hrms/hr_attendance.html",
            attendance=records
        )

    release_db(conn, cur)
    return redirect("/dashboard")


# =========================================================
# CHECK IN
# =========================================================
@attendance_bp.route("/attendance/check-in", methods=["POST"])
@login_required
def check_in():

    conn, cur = get_db(True)

    today = date.today()
    employee_id = session.get("employee_id")

    cur.execute("""
        SELECT id FROM hrms_attendance
        WHERE employee_id = %s AND attendance_date = %s
    """, (employee_id, today))

    if cur.fetchone():
        release_db(conn, cur)
        return jsonify({"success": False, "message": "Already marked today."})

    status = "Weekend" if today.weekday() == 6 else "Present"

    cur.execute("""
        INSERT INTO hrms_attendance
        (employee_id, attendance_date, status, check_in_time)
        VALUES (%s, %s, %s, %s)
    """, (employee_id, today, status, datetime.now()))

    conn.commit()
    release_db(conn, cur)

    return jsonify({"success": True})


# =========================================================
# CHECK OUT
# =========================================================
@attendance_bp.route("/attendance/check-out", methods=["POST"])
@login_required
def check_out():

    conn, cur = get_db(True)

    today = date.today()
    employee_id = session.get("employee_id")

    cur.execute("""
        SELECT id, check_in_time, check_out_time
        FROM hrms_attendance
        WHERE employee_id = %s AND attendance_date = %s
    """, (employee_id, today))

    record = cur.fetchone()

    if not record:
        release_db(conn, cur)
        return jsonify({"success": False, "message": "Check-in not found."})

    if record["check_out_time"]:
        release_db(conn, cur)
        return jsonify({"success": False, "message": "Already checked out."})

    # Store duration in minutes (SAFE)
    duration_delta = datetime.now() - record["check_in_time"]
    duration_minutes = int(duration_delta.total_seconds() / 60)

    cur.execute("""
        UPDATE hrms_attendance
        SET check_out_time = %s,
            duration = %s
        WHERE id = %s
    """, (datetime.now(), duration_minutes, record["id"]))

    conn.commit()
    release_db(conn, cur)

    return jsonify({"success": True})


# =========================================================
# LEAVE MODULE
# =========================================================
@attendance_bp.route("/leave", methods=["GET", "POST"])
@login_required
def leave_page():

    role = session.get("role")
    employee_id = session.get("employee_id")

    if role != "Employee":
        return redirect("/dashboard")

    conn, cur = get_db(True)

    if request.method == "POST":

        leave_type_id = request.form["leave_type"]
        from_date = date.fromisoformat(request.form["from_date"])
        to_date = date.fromisoformat(request.form["to_date"])
        reason = request.form["reason"]

        # 🚫 Past leave
        if from_date < date.today():
            release_db(conn, cur)
            return "Past leave not allowed"

        # 🚫 Wrong range
        if to_date < from_date:
            release_db(conn, cur)
            return "Invalid date range"

        requested_days = (to_date - from_date).days + 1

        # ✅ Balance check
        cur.execute("""
            SELECT total_allocated, used
            FROM employee_leave_balance
            WHERE employee_id = %s
            AND leave_type_id = %s
        """, (employee_id, leave_type_id))

        balance = cur.fetchone()

        if not balance:
            release_db(conn, cur)
            return "Balance not found"

        remaining = balance["total_allocated"] - balance["used"]

        if requested_days > remaining:
            release_db(conn, cur)
            return f"Only {remaining} days remaining"

        # ✅ Overlap check
        cur.execute("""
            SELECT id FROM leave_applications
            WHERE employee_id = %s
            AND status IN ('Pending','Approved')
            AND (
                (%s BETWEEN from_date AND to_date)
                OR (%s BETWEEN from_date AND to_date)
                OR (from_date BETWEEN %s AND %s)
            )
        """, (employee_id, from_date, to_date, from_date, to_date))

        if cur.fetchone():
            release_db(conn, cur)
            return "Leave overlap detected"

        # ✅ Locked payroll period block
        first_day_current_month = date.today().replace(day=1)

        if from_date < first_day_current_month:
            release_db(conn, cur)
            return "Cannot apply leave in locked payroll period."

        # ✅ Insert leave
        cur.execute("""
            INSERT INTO leave_applications
            (employee_id, leave_type_id, from_date, to_date, reason)
            VALUES (%s, %s, %s, %s, %s)
        """, (employee_id, leave_type_id, from_date, to_date, reason))

        conn.commit()

    # Fetch data
    cur.execute("SELECT * FROM leave_types")
    leave_types = cur.fetchall()

    cur.execute("""
        SELECT lt.name,
               elb.total_allocated,
               elb.used,
               (elb.total_allocated - elb.used) AS remaining
        FROM employee_leave_balance elb
        JOIN leave_types lt ON elb.leave_type_id = lt.id
        WHERE elb.employee_id = %s
    """, (employee_id,))
    balances = cur.fetchall()

    cur.execute("""
        SELECT la.*, lt.name AS leave_name
        FROM leave_applications la
        JOIN leave_types lt ON la.leave_type_id = lt.id
        WHERE la.employee_id = %s
        ORDER BY la.applied_on DESC
    """, (employee_id,))
    leaves = cur.fetchall()

    release_db(conn, cur)

    return render_template(
        "hrms/employee_leave.html",
        leave_types=leave_types,
        balances=balances,
        leaves=leaves,
        today=date.today()
    )
