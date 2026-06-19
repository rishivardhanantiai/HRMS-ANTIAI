from flask import Blueprint, render_template, request, jsonify, session, redirect, flash
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
    
    # Convert interval/timedelta duration to integer minutes
    dur = record.get("duration")
    if dur is not None:
        if isinstance(dur, timedelta):
            record["duration"] = int(dur.total_seconds() // 60)
        elif not isinstance(dur, int):
            try:
                record["duration"] = int(dur)
            except Exception:
                record["duration"] = 0
    else:
        record["duration"] = 0
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

            if from_date and to_date and from_date > to_date:
                flash("From Date cannot be greater than To Date. Date range has been swapped.", "error")
                from_date, to_date = to_date, from_date

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

            # --- Today's Live Attendance Monitor ---
            cur.execute(
                """
                SELECT id, full_name, designation
                FROM hrms_employees
                ORDER BY full_name
                """
            )
            employees = cur.fetchall()

            cur.execute(
                """
                SELECT id, employee_id, status, check_in_time, check_out_time, duration, is_locked
                FROM hrms_attendance
                WHERE attendance_date = %s
                """,
                (today,)
            )
            today_records_raw = cur.fetchall()
            today_records = {str(r["employee_id"]): r for r in today_records_raw}

            today_monitor = []
            stats = {
                "total": len(employees),
                "present": 0,
                "wfh": 0,
                "leave": 0,
                "not_marked": 0,
                "absent": 0
            }

            for emp in employees:
                emp_id_str = str(emp["id"])
                record = today_records.get(emp_id_str)

                if record:
                    norm_record = normalize_attendance_record(record.copy())
                    if norm_record["check_in_time"] and norm_record["check_out_time"]:
                        duration_delta = norm_record["check_out_time"] - norm_record["check_in_time"]
                        norm_record["duration"] = int(duration_delta.total_seconds() / 60)
                    else:
                        norm_record["duration"] = norm_record.get("duration") or 0

                    status_display = norm_record.get("status") or "Present"
                    check_in_display = norm_record["check_in_time"]
                    check_out_display = norm_record["check_out_time"]
                    duration = norm_record["duration"]
                    is_locked = norm_record["is_locked"]
                    attendance_id = norm_record["id"]
                else:
                    status_display = "Not Marked"
                    check_in_display = None
                    check_out_display = None
                    duration = 0
                    is_locked = False
                    attendance_id = None

                status_lower = status_display.lower()
                if status_lower == "present":
                    stats["present"] += 1
                elif status_lower == "wfh":
                    stats["wfh"] += 1
                elif status_lower == "leave":
                    stats["leave"] += 1
                elif status_lower == "absent":
                    stats["absent"] += 1
                else:
                    stats["not_marked"] += 1

                today_monitor.append({
                    "employee_id": emp["id"],
                    "full_name": emp["full_name"],
                    "designation": emp.get("designation") or "Employee",
                    "status": status_display,
                    "check_in_time": check_in_display,
                    "check_out_time": check_out_display,
                    "duration": duration,
                    "is_locked": is_locked,
                    "attendance_id": attendance_id
                })

            release_db(conn, cur)

            return render_template(
                "hrms/hr_attendance.html",
                attendance=records,
                employees=employees,
                today_monitor=today_monitor,
                stats=stats,
                today=today.isoformat(),
            )

        release_db(conn, cur)
        return redirect("/dashboard")

    except Exception:
        # Supabase REST fallback for new schema
        records = supabase_rest.list_attendance()
        for r in records:
            normalize_attendance_record(r)
        
        employees = [
            {"id": e.get("id"), "full_name": e.get("full_name"), "designation": e.get("designation") or "Employee"}
            for e in supabase_rest.list_employees()
        ]

        # Filter today's records
        today_records = {}
        for r in records:
            if r.get("attendance_date") == today:
                today_records[str(r.get("employee_id"))] = r

        today_monitor = []
        stats = {
            "total": len(employees),
            "present": 0,
            "wfh": 0,
            "leave": 0,
            "not_marked": 0,
            "absent": 0
        }

        for emp in employees:
            emp_id_str = str(emp["id"])
            record = today_records.get(emp_id_str)

            if record:
                status_display = record.get("status") or "Present"
                check_in_display = record.get("check_in_time")
                check_out_display = record.get("check_out_time")
                duration = record.get("duration") or 0
                is_locked = record.get("is_locked") or False
                attendance_id = record.get("id")
            else:
                status_display = "Not Marked"
                check_in_display = None
                check_out_display = None
                duration = 0
                is_locked = False
                attendance_id = None

            status_lower = str(status_display).lower()
            if status_lower == "present":
                stats["present"] += 1
            elif status_lower == "wfh":
                stats["wfh"] += 1
            elif status_lower == "leave":
                stats["leave"] += 1
            elif status_lower == "absent":
                stats["absent"] += 1
            else:
                stats["not_marked"] += 1

            today_monitor.append({
                "employee_id": emp["id"],
                "full_name": emp["full_name"],
                "designation": emp.get("designation") or "Employee",
                "status": status_display,
                "check_in_time": check_in_display,
                "check_out_time": check_out_display,
                "duration": duration,
                "is_locked": is_locked,
                "attendance_id": attendance_id
            })

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
            today_monitor=today_monitor,
            stats=stats,
            today=today.isoformat(),
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
                duration = (%s || ' minutes')::interval
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
        if record:
            total_minutes = record.get("duration")
            if isinstance(total_minutes, timedelta):
                record["duration"] = int(total_minutes.total_seconds() // 60)
            elif total_minutes is not None and not isinstance(total_minutes, int):
                try:
                    record["duration"] = int(total_minutes)
                except Exception:
                    record["duration"] = 0
            else:
                record["duration"] = record.get("duration") or 0

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
            "check_in_time": parse_iso(rec.get("check_in_time") or rec.get("check_in")) if rec else None,
            "check_out_time": parse_iso(rec.get("check_out_time") or rec.get("check_out")) if rec else None,
            "duration": rec.get("duration") if rec else None,
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


# =========================================================
# MARK/SAVE ATTENDANCE BY EMPLOYEE & DATE (HR / ADMIN)
# =========================================================

@attendance_bp.route("/attendance/mark", methods=["POST"])
@login_required
def mark_attendance():
    role = session.get("role")

    if role not in ["HR", "Admin"]:
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    employee_id = request.form.get("employee_id", "").strip()
    att_date_str = request.form.get("attendance_date", "").strip()
    status = request.form.get("status", "").strip()

    print(f"[DEBUG] mark_attendance: employee_id='{employee_id}', attendance_date='{att_date_str}', status='{status}'", flush=True)

    if not employee_id:
        return jsonify({"success": False, "message": "Missing employee_id parameter"}), 400
    if not att_date_str:
        return jsonify({"success": False, "message": "Missing attendance_date parameter"}), 400
    if not status:
        return jsonify({"success": False, "message": "Missing status parameter"}), 400

    allowed_statuses = {"Present", "Absent", "WFH", "Weekend", "Leave"}
    if status not in allowed_statuses:
        return jsonify({"success": False, "message": f"Invalid status: '{status}'"}), 400

    try:
        att_date = date.fromisoformat(att_date_str)
    except Exception as e:
        return jsonify({"success": False, "message": f"Invalid date format: '{att_date_str}'"}), 400

    try:
        conn, cur = get_db(True)

        # Check if attendance is locked for this day
        cur.execute("""
            SELECT id, is_locked FROM hrms_attendance
            WHERE employee_id = %s AND attendance_date = %s
        """, (employee_id, att_date))
        record = cur.fetchone()

        if record and record.get("is_locked"):
            release_db(conn, cur)
            return jsonify({"success": False, "message": "Attendance record is locked"}), 400

        # Check if payroll is locked for this month
        cur.execute("""
            SELECT status FROM payroll_runs
            WHERE employee_id = %s AND month = %s AND year = %s
        """, (employee_id, att_date.month, att_date.year))
        payroll = cur.fetchone()

        if payroll and payroll["status"] == "LOCKED" and role != "Admin":
            release_db(conn, cur)
            return jsonify({"success": False, "message": "Payroll locked for this month"}), 400

        if record:
            cur.execute("""
                UPDATE hrms_attendance
                SET status = %s
                WHERE id = %s
            """, (status, record["id"]))
        else:
            cur.execute("""
                INSERT INTO hrms_attendance (employee_id, attendance_date, status)
                VALUES (%s, %s, %s)
            """, (employee_id, att_date, status))

        conn.commit()
        release_db(conn, cur)
        return jsonify({"success": True, "status": status})

    except Exception as e:
        print(f"[DEBUG] mark_attendance DB Exception: {e}", flush=True)
        # Supabase fallback
        try:
            existing = supabase_rest.get_attendance_by_employee_day(employee_id, att_date_str)
            if existing:
                if existing.get("is_locked"):
                    return jsonify({"success": False, "message": "Attendance record is locked"}), 400
                
                updated = supabase_rest.update_attendance_status(existing["id"], status)
            else:
                row = supabase_rest.insert_row(
                    "hrms_attendance",
                    {
                        "employee_id": employee_id,
                        "attendance_date": att_date_str,
                        "status": status.lower(),
                        "is_locked": False,
                    }
                )
                updated = row is not None

            if not updated:
                return jsonify({"success": False, "message": "Failed to update record in Supabase"}), 400

            return jsonify({"success": True, "status": status})
        except Exception as se:
            print(f"[DEBUG] mark_attendance Supabase Exception: {se}", flush=True)
            return jsonify({"success": False, "message": f"Fallback error: {se}"}), 400