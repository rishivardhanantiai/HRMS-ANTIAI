from flask import Blueprint, render_template, request, jsonify, session, redirect
from utils.auth import login_required
from utils.db import get_db, release_db
from datetime import date, datetime, timedelta
import calendar
from zoneinfo import ZoneInfo

attendance_bp = Blueprint("attendance", __name__, url_prefix="/hrms")

# =========================================================
# IST TIME HELPERS
# =========================================================

IST = ZoneInfo("Asia/Kolkata")

def get_ist_now():
    return datetime.now(IST)

def get_ist_today():
    return get_ist_now().date()

def ensure_ist(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)

# =========================================================
# MAIN ATTENDANCE PAGE
# =========================================================

@attendance_bp.route("/attendance")
@login_required
def attendance_page():

    role = session.get("role")
    employee_id = session.get("employee_id")
    selected_month = request.args.get("month")
    today = get_ist_today()

    if selected_month:
        year, month = map(int, selected_month.split("-"))
    else:
        year = today.year
        month = today.month

    conn, cur = get_db(True)

    # Auto lock previous months (existing logic untouched)
    first_day_current_month = today.replace(day=1)

    cur.execute("""
        UPDATE hrms_attendance
        SET is_locked = TRUE
        WHERE attendance_date < %s
    """, (first_day_current_month,))
    conn.commit()

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
        attendance_map = {r["attendance_date"]: r for r in records}
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

    employee_id = session.get("employee_id")
    role = session.get("role")
    today = get_ist_today()
    now = get_ist_now()

    # ===============================
    # PAYROLL LOCK CHECK (NEW)
    # ===============================

    month = today.month
    year = today.year

    cur.execute("""
        SELECT status FROM payroll_runs
        WHERE employee_id = %s AND month = %s AND year = %s
    """, (employee_id, month, year))

    payroll = cur.fetchone()

    if payroll and payroll["status"] == "LOCKED":
        if role != "Admin":
            release_db(conn, cur)
            return jsonify({"success": False, "message": "Payroll locked. Attendance modification not allowed."})

    # ===============================
    # EXISTING ATTENDANCE LOCK CHECK
    # ===============================

    cur.execute("""
        SELECT id, check_in_time, is_locked
        FROM hrms_attendance
        WHERE employee_id = %s AND attendance_date = %s
    """, (employee_id, today))

    record = cur.fetchone()

    if record and record.get("is_locked"):
        release_db(conn, cur)
        return jsonify({"success": False, "message": "Attendance locked."})

    if record and record["check_in_time"]:
        release_db(conn, cur)
        return jsonify({"success": False, "message": "Already checked in today."})

    if record:
        cur.execute("""
            UPDATE hrms_attendance
            SET check_in_time = %s
            WHERE id = %s
        """, (now, record["id"]))
    else:
        status = "Weekend" if today.weekday() == 6 else "Present"
        cur.execute("""
            INSERT INTO hrms_attendance
            (employee_id, attendance_date, status, check_in_time)
            VALUES (%s, %s, %s, %s)
        """, (employee_id, today, status, now))

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

    employee_id = session.get("employee_id")
    role = session.get("role")
    today = get_ist_today()

    # ===============================
    # PAYROLL LOCK CHECK (NEW)
    # ===============================

    month = today.month
    year = today.year

    cur.execute("""
        SELECT status FROM payroll_runs
        WHERE employee_id = %s AND month = %s AND year = %s
    """, (employee_id, month, year))

    payroll = cur.fetchone()

    if payroll and payroll["status"] == "LOCKED":
        if role != "Admin":
            release_db(conn, cur)
            return jsonify({"success": False, "message": "Payroll locked. Attendance modification not allowed."})

    # ===============================
    # EXISTING ATTENDANCE CHECK
    # ===============================

    cur.execute("""
        SELECT id, check_in_time, check_out_time, is_locked
        FROM hrms_attendance
        WHERE employee_id = %s AND attendance_date = %s
    """, (employee_id, today))

    record = cur.fetchone()

    if not record:
        release_db(conn, cur)
        return jsonify({"success": False, "message": "Check-in not found."})

    if record.get("is_locked"):
        release_db(conn, cur)
        return jsonify({"success": False, "message": "Attendance locked."})

    if not record["check_in_time"]:
        release_db(conn, cur)
        return jsonify({"success": False, "message": "You haven't checked in."})

    if record["check_out_time"]:
        release_db(conn, cur)
        return jsonify({"success": False, "message": "Already checked out."})

    now = get_ist_now()
    check_in_time = ensure_ist(record["check_in_time"])

    duration_delta = now - check_in_time
    duration_minutes = int(duration_delta.total_seconds() / 60)

    cur.execute("""
        UPDATE hrms_attendance
        SET check_out_time = %s,
            duration = %s
        WHERE id = %s
    """, (now, duration_minutes, record["id"]))

    conn.commit()
    release_db(conn, cur)

    return jsonify({"success": True})