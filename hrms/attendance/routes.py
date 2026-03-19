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
        month_name = calendar.month_name[month]
        day_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        release_db(conn, cur)

        return render_template(
    "hrms/employee_attendance.html",
    calendar_data=cal,
    attendance_map=attendance_map,
    attendance=records,   # ADD THIS
    year=year,
    month=month,
    month_name=month_name,
    day_names=day_names,
    date=date
)

    elif role in ["HR", "Admin"]:

        employee_filter = request.args.get("employee_id", "").strip()
        from_date = request.args.get("from_date", "").strip()
        to_date = request.args.get("to_date", "").strip()

        conditions = []
        params = []

        if employee_filter:
            conditions.append("a.employee_id = %s")
            params.append(employee_filter)

        if from_date:
            conditions.append("a.attendance_date >= %s")
            params.append(from_date)

        if to_date:
            conditions.append("a.attendance_date <= %s")
            params.append(to_date)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        cur.execute(
            f"""
            SELECT
                a.id,
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
            {where_clause}
            ORDER BY a.attendance_date DESC, e.full_name
            """,
            tuple(params)
        )
        records = cur.fetchall()

        # Fetch employees for filter dropdown
        cur.execute("""
            SELECT id, full_name
            FROM hrms_employees
            ORDER BY full_name
        """)
        employees = cur.fetchall()

        release_db(conn, cur)

        return render_template(
            "hrms/hr_attendance.html",
            attendance=records,
            employees=employees
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


# =========================================================
# TODAY STATUS API
# =========================================================

@attendance_bp.route("/attendance/today-status")
@login_required
def today_status():

    conn, cur = get_db(True)

    employee_id = session.get("employee_id")
    today = get_ist_today()

    cur.execute("""
        SELECT check_in_time,
               check_out_time,
               duration
        FROM hrms_attendance
        WHERE employee_id=%s AND attendance_date=%s
    """, (employee_id, today))

    record = cur.fetchone()

    release_db(conn, cur)

    if not record:
        return jsonify({"status": "Not Marked"})

    if record["check_in_time"] and not record["check_out_time"]:
        worked = "-"
        return jsonify({
            "status": "Checked In",
            "worked": worked
        })

    if record["check_out_time"]:
        total_minutes = record["duration"] or 0
        hours = total_minutes // 60
        minutes = total_minutes % 60
        worked = f"{hours:02d}:{minutes:02d}"

        return jsonify({
            "status": "Checked Out",
            "worked": worked
        })

    return jsonify({"status": "Not Marked"})


# =========================================================
# EDIT ATTENDANCE (HR / ADMIN)
# =========================================================

@attendance_bp.route("/attendance/edit/<int:attendance_id>", methods=["POST"])
@login_required
def edit_attendance(attendance_id):

    role = session.get("role")

    if role not in ["HR", "Admin"]:
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    status = request.form.get("status", "").strip()

    allowed_statuses = {"Present", "Absent", "WFH", "Weekend", "Leave"}
    if status not in allowed_statuses:
        return jsonify({"success": False, "message": "Invalid status"}), 400

    conn, cur = get_db(True)

    cur.execute("""
        UPDATE hrms_attendance
        SET status = %s
        WHERE id = %s
        AND is_locked = FALSE
    """, (status, attendance_id))

    conn.commit()

    updated = cur.rowcount > 0

    release_db(conn, cur)

    if not updated:
        return jsonify({"success": False, "message": "Record not updated (locked or not found)"}), 400

    return jsonify({"success": True, "status": status})