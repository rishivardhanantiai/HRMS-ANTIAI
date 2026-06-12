from flask import Blueprint, render_template, request, jsonify, session, redirect
from utils.auth import login_required
from utils.db import get_db, release_db
from utils import supabase_rest
from datetime import date, datetime, timedelta
import calendar
from zoneinfo import ZoneInfo

attendance_bp = Blueprint("attendance", __name__, url_prefix="/hrms")

# =========================================================
# IST TIME HELPERS
# =========================================================

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")

def get_ist_now():
    return datetime.now(IST)

def get_ist_today():
    return get_ist_now().date()

def ensure_ist(dt):
    # Converts to IST properly, treating naive datetimes as UTC
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        # Naive datetime from database - assume it's in UTC (PostgreSQL default)
        dt = dt.replace(tzinfo=UTC)
    # Convert to IST
    return dt.astimezone(IST)


def parse_attendance_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def normalize_attendance_record(record):
    record["attendance_date"] = parse_attendance_date(record.get("attendance_date"))
    record["check_in_time"] = ensure_ist(record.get("check_in_time"))
    record["check_out_time"] = ensure_ist(record.get("check_out_time"))
    return record

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

    try:
        conn, cur = get_db(True)

        # Auto lock previous months (existing logic untouched)
        first_day_current_month = today.replace(day=1)
        cur.execute(
            """
            UPDATE hrms_attendance
            SET is_locked = TRUE
            WHERE attendance_date < %s
            """,
            (first_day_current_month,),
        )
        conn.commit()

        if role == "Employee":
            cur.execute(
                """
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
                """,
                (employee_id, month, year),
            )

            records = cur.fetchall()
            for r in records:
                normalize_attendance_record(r)

            attendance_map = {r["attendance_date"]: r for r in records}
            cal = calendar.monthcalendar(year, month)
            month_name = calendar.month_name[month]
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            release_db(conn, cur)

            return render_template(
                "hrms/employee_attendance.html",
                calendar_data=cal,
                attendance_map=attendance_map,
                attendance=records,
                year=year,
                month=month,
                month_name=month_name,
                day_names=day_names,
                date=date,
            )

        if role in ["HR", "Admin"]:
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
                tuple(params),
            )

            records = cur.fetchall()
            for r in records:
                normalize_attendance_record(r)
                if r["check_in_time"] and r["check_out_time"]:
                    duration_delta = r["check_out_time"] - r["check_in_time"]
                    r["duration"] = int(duration_delta.total_seconds() / 60)
                else:
                    r["duration"] = 0

            cur.execute(
                """
                SELECT id, full_name
                FROM hrms_employees
                ORDER BY full_name
                """
            )
            employees = cur.fetchall()
            release_db(conn, cur)

            return render_template(
                "hrms/hr_attendance.html",
                attendance=records,
                employees=employees,
            )

        release_db(conn, cur)
        return redirect("/dashboard")

    except Exception:
        # Supabase REST fallback for new schema
        records = supabase_rest.list_attendance()
        for r in records:
            normalize_attendance_record(r)
        employees = [
            {"id": e.get("id"), "full_name": e.get("full_name")}
            for e in supabase_rest.list_employees()
        ]

        if role == "Employee":
            emp_id = str(employee_id)
            records = [r for r in records if str(r.get("employee_id")) == emp_id]
            attendance_map = {r.get("attendance_date"): r for r in records}
            cal = calendar.monthcalendar(year, month)
            month_name = calendar.month_name[month]
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            return render_template(
                "hrms/employee_attendance.html",
                calendar_data=cal,
                attendance_map=attendance_map,
                attendance=records,
                year=year,
                month=month,
                month_name=month_name,
                day_names=day_names,
                date=date,
            )

        return render_template(
            "hrms/hr_attendance.html",
            attendance=records,
            employees=employees,
        )


# =========================================================
# CHECK IN
# =========================================================

@attendance_bp.route("/attendance/check-in", methods=["POST"])
@login_required
def check_in():
    employee_id = session.get("employee_id")
    role = session.get("role")
    today = get_ist_today()
    now = get_ist_now()

    try:
        conn, cur = get_db(True)

        month = today.month
        year = today.year

        cur.execute("""
            SELECT status FROM payroll_runs
            WHERE employee_id = %s AND month = %s AND year = %s
        """, (employee_id, month, year))

        payroll = cur.fetchone()

        if payroll and payroll["status"] == "LOCKED" and role != "Admin":
            release_db(conn, cur)
            return jsonify({"success": False, "message": "Payroll locked. Attendance modification not allowed."})

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
    except Exception:
        month = today.month
        year = today.year
        if role != "Admin":
            payrolls = supabase_rest.list_my_payrolls(employee_id)
            if any((p.get("month") == month and p.get("year") == year and p.get("status") == "LOCKED") for p in payrolls):
                return jsonify({"success": False, "message": "Payroll locked. Attendance modification not allowed."})

        ok, msg = supabase_rest.check_in(employee_id, str(today), now.isoformat())
        if not ok:
            return jsonify({"success": False, "message": msg or "Check-in failed."})
        return jsonify({"success": True})


# =========================================================
# CHECK OUT
# =========================================================

@attendance_bp.route("/attendance/check-out", methods=["POST"])
@login_required
def check_out():
    employee_id = session.get("employee_id")
    role = session.get("role")
    today = get_ist_today()

    try:
        conn, cur = get_db(True)

        month = today.month
        year = today.year

        cur.execute("""
            SELECT status FROM payroll_runs
            WHERE employee_id = %s AND month = %s AND year = %s
        """, (employee_id, month, year))

        payroll = cur.fetchone()

        if payroll and payroll["status"] == "LOCKED" and role != "Admin":
            release_db(conn, cur)
            return jsonify({"success": False, "message": "Payroll locked. Attendance modification not allowed."})

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
    except Exception:
        month = today.month
        year = today.year
        if role != "Admin":
            payrolls = supabase_rest.list_my_payrolls(employee_id)
            if any((p.get("month") == month and p.get("year") == year and p.get("status") == "LOCKED") for p in payrolls):
                return jsonify({"success": False, "message": "Payroll locked. Attendance modification not allowed."})

        ok, msg = supabase_rest.check_out(employee_id, str(today), get_ist_now().isoformat())
        if not ok:
            return jsonify({"success": False, "message": msg or "Check-out failed."})
        return jsonify({"success": True})


# =========================================================
# TODAY STATUS API
# =========================================================

@attendance_bp.route("/attendance/today-status")
@login_required
def today_status():
    employee_id = session.get("employee_id")
    today = get_ist_today()

    try:
        conn, cur = get_db(True)

        cur.execute("""
            SELECT check_in_time,
                   check_out_time,
                   duration
            FROM hrms_attendance
            WHERE employee_id=%s AND attendance_date=%s
        """, (employee_id, today))

        record = cur.fetchone()

        release_db(conn, cur)
    except Exception:
        rec = supabase_rest.get_attendance_by_employee_day(employee_id, str(today))
        def parse_iso(dt_str):
            if not dt_str:
                return None
            try:
                return datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
            except Exception:
                return None
        record = {
            "check_in_time": parse_iso(rec.get("check_in")) if rec else None,
            "check_out_time": parse_iso(rec.get("check_out")) if rec else None,
            "duration": None,
        } if rec else None

    if not record:
        return jsonify({"status": "Not Marked"})

    if record["check_in_time"] and not record["check_out_time"]:
        check_in = ensure_ist(record["check_in_time"])
        worked = "-"
        return jsonify({
            "status": "Checked In",
            "check_in_time": check_in.strftime("%H:%M") if check_in else "-",
            "worked": worked
        })

    if record["check_out_time"]:
        check_in = ensure_ist(record["check_in_time"])
        check_out = ensure_ist(record["check_out_time"])
        total_minutes = record["duration"] or 0
        hours = total_minutes // 60
        minutes = total_minutes % 60
        worked = f"{hours:02d}:{minutes:02d}"

        return jsonify({
            "status": "Checked Out",
            "check_in_time": check_in.strftime("%H:%M") if check_in else "-",
            "check_out_time": check_out.strftime("%H:%M") if check_out else "-",
            "worked": worked
        })

    return jsonify({"status": "Not Marked"})


# =========================================================
# EDIT ATTENDANCE (HR / ADMIN)
# =========================================================

@attendance_bp.route("/attendance/edit/<attendance_id>", methods=["POST"])
@login_required
def edit_attendance(attendance_id):

    role = session.get("role")

    if role not in ["HR", "Admin"]:
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    status = request.form.get("status", "").strip()

    allowed_statuses = {"Present", "Absent", "WFH", "Weekend", "Leave"}
    if status not in allowed_statuses:
        return jsonify({"success": False, "message": "Invalid status"}), 400

    try:
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
    except Exception:
        updated = supabase_rest.update_attendance_status(attendance_id, status)
        if not updated:
            return jsonify({"success": False, "message": "Record not updated (not found)"}), 400
        return jsonify({"success": True, "status": status})