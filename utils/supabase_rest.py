import calendar
import os
from datetime import date, datetime, timedelta

import httpx


def _supabase_url():
    return (os.getenv("SUPABASE_URL") or "").rstrip("/")


def _base_url():
    supabase_url = _supabase_url()
    if not supabase_url:
        return None
    return f"{supabase_url}/rest/v1"


def _service_headers(prefer_representation=False):
    key = os.getenv("SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    if not key:
        return None
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer_representation:
        headers["Prefer"] = "return=representation"
    return headers


def _request(method, path, params=None, payload=None, prefer_representation=False):
    base = _base_url()
    headers = _service_headers(prefer_representation=prefer_representation)
    if not base or not headers:
        return None
    try:
        return httpx.request(
            method,
            f"{base}/{path}",
            headers=headers,
            params=params,
            json=payload,
            timeout=20.0,
        )
    except Exception:
        return None


def table_exists(table):
    response = _request("GET", table, params={"select": "id", "limit": "1"})
    return response is not None and response.status_code == 200


def is_ready():
    return _base_url() is not None and _service_headers() is not None


def get_rows(table, params=None):
    query = {"select": "*"}
    if params:
        query.update(params)

    response = _request("GET", table, params=query)
    if response is None or response.status_code != 200:
        return []

    data = response.json()
    return data if isinstance(data, list) else []


def get_first_row(table, params=None):
    rows = get_rows(table, params=params)
    return rows[0] if rows else None


def insert_row(table, payload):
    response = _request("POST", table, payload=payload, prefer_representation=True)
    if response is None or response.status_code not in (200, 201):
        return None
    data = response.json()
    if isinstance(data, list) and data:
        return data[0]
    return data if isinstance(data, dict) else None


def update_rows(table, filters, payload):
    response = _request(
        "PATCH",
        table,
        params=filters,
        payload=payload,
        prefer_representation=True,
    )
    if response is None or response.status_code not in (200, 204):
        return []
    if response.status_code == 204:
        return []
    data = response.json()
    return data if isinstance(data, list) else []


def delete_rows(table, filters):
    response = _request("DELETE", table, params=filters)
    return response is not None and response.status_code in (200, 204)


def create_auth_user(email, password):
    supabase_url = _supabase_url()
    service_key = os.getenv("SERVICE_KEY")
    if not supabase_url or not service_key:
        return False

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    payload = {"email": email, "password": password, "email_confirm": True}

    try:
        response = httpx.post(
            f"{supabase_url}/auth/v1/admin/users",
            headers=headers,
            json=payload,
            timeout=20.0,
        )
        if response.status_code in (200, 201):
            return True

        body = response.text.lower()
        return "already" in body or "registered" in body or "duplicate" in body
    except Exception:
        return False


def list_roles():
    rows = get_rows("roles", {"select": "id,name", "order": "name.asc"})
    return [
        {
            "id": r.get("id"),
            "role_name": r.get("name"),
            "description": "",
        }
        for r in rows
    ]


def roles_map():
    mapping = {}
    for row in list_roles():
        mapping[str(row.get("id"))] = row.get("role_name")
    return mapping


def get_role_by_name(role_name):
    target = (role_name or "").strip().lower()
    if not target:
        return None

    for row in get_rows("roles", {"select": "id,name"}):
        if str(row.get("name") or "").strip().lower() == target:
            return row
    return None


def get_role_by_id(role_id):
    return get_first_row("roles", {"select": "id,name", "id": f"eq.{role_id}"})


def create_role(role_name, description=""):
    return insert_row("roles", {"name": role_name})


def update_role(role_id, role_name):
    rows = update_rows("roles", {"id": f"eq.{role_id}"}, {"name": role_name})
    return rows[0] if rows else None


def delete_role(role_id):
    return delete_rows("roles", {"id": f"eq.{role_id}"})


def _full_name(first_name, last_name):
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    return f"{first} {last}".strip() or "-"


def _split_full_name(full_name):
    text = (full_name or "").strip()
    if not text:
        return "", ""
    parts = text.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def list_employees():
    role_lookup = roles_map()
    rows = get_rows(
        "employees",
        {
            "select": "id,employee_number,first_name,last_name,email,phone,role_id,status,metadata",
            "order": "created_at.desc",
        },
    )

    employees = []
    for r in rows:
        metadata = r.get("metadata") or {}
        department = metadata.get("department") if isinstance(metadata, dict) else None
        employees.append(
            {
                "id": r.get("id"),
                "employee_code": r.get("employee_number") or "",
                "full_name": _full_name(r.get("first_name"), r.get("last_name")),
                "email": r.get("email"),
                "phone": r.get("phone"),
                "department": department,
                "role_name": role_lookup.get(str(r.get("role_id"))),
                "status": (r.get("status") or "active").capitalize(),
                "designation": "Employee",
            }
        )

    return employees


def get_employee_by_id(employee_id):
    row = get_first_row(
        "employees",
        {
            "select": "id,employee_number,first_name,last_name,email,phone,role_id,status,metadata",
            "id": f"eq.{employee_id}",
        },
    )
    if not row:
        return None

    role_lookup = roles_map()
    metadata = row.get("metadata") or {}
    department = metadata.get("department") if isinstance(metadata, dict) else None
    return {
        "id": row.get("id"),
        "employee_code": row.get("employee_number") or "",
        "full_name": _full_name(row.get("first_name"), row.get("last_name")),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "department": department,
        "role_id": row.get("role_id"),
        "role_name": role_lookup.get(str(row.get("role_id"))),
        "status": (row.get("status") or "active").capitalize(),
        "designation": "Employee",
    }


def get_employee_by_email(email):
    return get_first_row("employees", {"select": "id,email", "email": f"eq.{email}"})


def create_employee(employee_code, full_name, email, phone, department, role_id):
    first_name, last_name = _split_full_name(full_name)
    payload = {
        "employee_number": employee_code,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "role_id": role_id,
        "status": "active",
        "hire_date": str(date.today()),
        "metadata": {"department": department} if department else {},
    }
    return insert_row("employees", payload)


def update_employee(employee_id, full_name, email, phone, department, role_id):
    first_name, last_name = _split_full_name(full_name)
    rows = update_rows(
        "employees",
        {"id": f"eq.{employee_id}"},
        {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
            "role_id": role_id,
            "metadata": {"department": department} if department else {},
        },
    )
    return rows[0] if rows else None


def update_employee_status(employee_id, status):
    rows = update_rows("employees", {"id": f"eq.{employee_id}"}, {"status": status.lower()})
    return rows[0] if rows else None


def soft_delete_employee(employee_id):
    rows = update_rows("employees", {"id": f"eq.{employee_id}"}, {"status": "deleted"})
    return rows[0] if rows else None


def reassign_role(old_role_id, new_role_id):
    update_rows("employees", {"role_id": f"eq.{old_role_id}"}, {"role_id": new_role_id})


def _safe_parse_iso(dt_str):
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
    except Exception:
        return None


def list_attendance():
    employees = list_employees()
    employee_lookup = {str(e.get("id")): e for e in employees}
    rows = get_rows(
        "attendance",
        {"select": "id,employee_id,day,check_in,check_out,status", "order": "day.desc"},
    )

    result = []
    for r in rows:
        check_in = _safe_parse_iso(r.get("check_in"))
        check_out = _safe_parse_iso(r.get("check_out"))
        duration_minutes = 0
        if check_in and check_out:
            duration_minutes = max(0, int((check_out - check_in).total_seconds() // 60))

        emp = employee_lookup.get(str(r.get("employee_id")), {})
        result.append(
            {
                "id": r.get("id"),
                "employee_id": r.get("employee_id"),
                "attendance_date": r.get("day"),
                "status": (r.get("status") or "Present").capitalize(),
                "check_in_time": check_in,
                "check_out_time": check_out,
                "duration": duration_minutes,
                "is_locked": False,
                "full_name": emp.get("full_name") or "-",
            }
        )

    return result


def get_attendance_by_employee_day(employee_id, day_text):
    return get_first_row(
        "attendance",
        {
            "select": "id,employee_id,day,check_in,check_out,status",
            "employee_id": f"eq.{employee_id}",
            "day": f"eq.{day_text}",
        },
    )


def check_in(employee_id, day_text, now_iso):
    existing = get_attendance_by_employee_day(employee_id, day_text)
    if existing:
        if existing.get("check_in"):
            return False, "Already checked in today."
        rows = update_rows(
            "attendance",
            {"id": f"eq.{existing.get('id')}"},
            {"check_in": now_iso},
        )
        return (bool(rows), None if rows else "Could not update check-in")

    status = "weekend" if date.fromisoformat(day_text).weekday() == 6 else "present"
    row = insert_row(
        "attendance",
        {
            "employee_id": employee_id,
            "day": day_text,
            "status": status,
            "check_in": now_iso,
        },
    )
    return (row is not None, None if row else "Could not create attendance record")


def check_out(employee_id, day_text, now_iso):
    existing = get_attendance_by_employee_day(employee_id, day_text)
    if not existing:
        return False, "Check-in not found."
    if not existing.get("check_in"):
        return False, "You haven't checked in."
    if existing.get("check_out"):
        return False, "Already checked out."

    rows = update_rows(
        "attendance",
        {"id": f"eq.{existing.get('id')}"},
        {"check_out": now_iso},
    )
    return (bool(rows), None if rows else "Could not update check-out")


def update_attendance_status(attendance_id, status):
    rows = update_rows("attendance", {"id": f"eq.{attendance_id}"}, {"status": status.lower()})
    return rows[0] if rows else None


def list_payrolls():
    employees = list_employees()
    employee_lookup = {str(e.get("id")): e for e in employees}
    rows = get_rows(
        "payrolls",
        {
            "select": "id,employee_id,period_start,gross_pay,net_pay,status",
            "order": "period_start.desc",
        },
    )

    result = []
    for r in rows:
        period_start = str(r.get("period_start") or "")
        month = 0
        year = 0
        if len(period_start) >= 7:
            try:
                year = int(period_start[:4])
                month = int(period_start[5:7])
            except Exception:
                month = 0
                year = 0

        emp = employee_lookup.get(str(r.get("employee_id")), {})
        result.append(
            {
                "id": r.get("id"),
                "payroll_id": r.get("id"),
                "employee_id": r.get("employee_id"),
                "month": month,
                "year": year,
                "gross_salary": r.get("gross_pay") or 0,
                "net_salary": r.get("net_pay") or 0,
                "status": str(r.get("status") or "draft").upper(),
                "full_name": emp.get("full_name") or "-",
            }
        )

    return result


def _month_range(year, month):
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    return start, end


def _latest_salary_for_employee(employee_id, up_to_date_text):
    rows = get_rows(
        "salaries",
        {
            "select": "id,base_amount,effective_from",
            "employee_id": f"eq.{employee_id}",
            "effective_from": f"lte.{up_to_date_text}",
            "order": "effective_from.desc",
            "limit": "1",
        },
    )
    if rows:
        return rows[0]

    # Fallback: latest salary regardless of effective date.
    fallback = get_rows(
        "salaries",
        {
            "select": "id,base_amount,effective_from",
            "employee_id": f"eq.{employee_id}",
            "order": "effective_from.desc",
            "limit": "1",
        },
    )
    return fallback[0] if fallback else None


def create_payroll_run(employee_id, month, year):
    period_start, period_end = _month_range(year, month)
    existing = get_first_row(
        "payrolls",
        {
            "select": "id,status",
            "employee_id": f"eq.{employee_id}",
            "period_start": f"eq.{period_start}",
        },
    )
    if existing:
        return {"error": "Payroll already generated for this period."}

    salary = _latest_salary_for_employee(employee_id, str(period_end))
    if not salary:
        return {"error": "Salary record not found for employee."}

    gross = float(salary.get("base_amount") or 0)
    payload = {
        "employee_id": employee_id,
        "period_start": str(period_start),
        "period_end": str(period_end),
        "gross_pay": gross,
        "net_pay": gross,
        "tax_amount": 0,
        "deductions": {},
        "additions": {},
        "status": "draft",
    }
    row = insert_row("payrolls", payload)
    if not row:
        return {"error": "Could not generate payroll."}
    return {"success": True, "net_salary": gross, "id": row.get("id")}


def get_payroll_by_id(payroll_id):
    row = get_first_row(
        "payrolls",
        {
            "select": "id,employee_id,period_start,period_end,gross_pay,net_pay,status,tax_amount,deductions,additions",
            "id": f"eq.{payroll_id}",
        },
    )
    if not row:
        return None

    period_start = str(row.get("period_start") or "")
    month = 0
    year = 0
    if len(period_start) >= 7:
        try:
            year = int(period_start[:4])
            month = int(period_start[5:7])
        except Exception:
            pass

    employee = get_employee_by_id(row.get("employee_id")) or {}
    return {
        "id": row.get("id"),
        "employee_id": row.get("employee_id"),
        "full_name": employee.get("full_name") or "-",
        "designation": employee.get("designation") or "Employee",
        "month": month,
        "year": year,
        "gross_salary": row.get("gross_pay") or 0,
        "net_salary": row.get("net_pay") or 0,
        "status": str(row.get("status") or "draft").upper(),
        "financial_year": f"{year-1}-{year}" if month and month < 4 else f"{year}-{year+1}" if year else "-",
        "variable_pay": 0,
        "bonus": 0,
        "reimbursements": 0,
        "attendance_deduction": 0,
        "pf": 0,
        "tax": row.get("tax_amount") or 0,
    }


def update_payroll_status(payroll_id, status):
    rows = update_rows("payrolls", {"id": f"eq.{payroll_id}"}, {"status": status.lower()})
    return rows[0] if rows else None


def update_payroll_net(payroll_id, new_net_salary):
    rows = update_rows(
        "payrolls",
        {"id": f"eq.{payroll_id}", "status": "eq.draft"},
        {"net_pay": float(new_net_salary)},
    )
    return rows[0] if rows else None


def delete_payroll_if_draft(payroll_id):
    return delete_rows("payrolls", {"id": f"eq.{payroll_id}", "status": "eq.draft"})


def list_my_payrolls(employee_id):
    payrolls = list_payrolls()
    return [p for p in payrolls if str(p.get("employee_id")) == str(employee_id)]


def list_leaves_manage():
    employees = list_employees()
    employee_lookup = {str(e.get("id")): e for e in employees}
    rows = get_rows(
        "leaves",
        {
            "select": "id,employee_id,leave_type,start_date,end_date,status",
            "order": "start_date.desc",
        },
    )

    result = []
    for r in rows:
        emp = employee_lookup.get(str(r.get("employee_id")), {})
        result.append(
            {
                "id": r.get("id"),
                "full_name": emp.get("full_name") or "-",
                "type": r.get("leave_type") or "Leave",
                "from_date": r.get("start_date"),
                "to_date": r.get("end_date"),
                "status": (r.get("status") or "pending").capitalize(),
            }
        )

    return result


def list_leave_types():
    rows = get_rows("leaves", {"select": "leave_type"})
    values = {str(r.get("leave_type") or "").strip() for r in rows}
    values = {v for v in values if v}
    if not values:
        values = {"Casual", "Sick", "Paid"}
    return [{"id": v, "name": v} for v in sorted(values)]


def list_employee_leaves(employee_id):
    rows = get_rows(
        "leaves",
        {
            "select": "id,leave_type,start_date,end_date,status",
            "employee_id": f"eq.{employee_id}",
            "order": "start_date.desc",
        },
    )
    result = []
    for r in rows:
        result.append(
            {
                "id": r.get("id"),
                "leave_type": r.get("leave_type") or "Leave",
                "from_date": r.get("start_date"),
                "to_date": r.get("end_date"),
                "status": (r.get("status") or "pending").capitalize(),
            }
        )
    return result


def create_leave_request(employee_id, leave_type, from_date, to_date, reason):
    try:
        from_dt = date.fromisoformat(from_date)
        to_dt = date.fromisoformat(to_date)
        days = max(1, (to_dt - from_dt).days + 1)
    except Exception:
        days = 1

    return insert_row(
        "leaves",
        {
            "employee_id": employee_id,
            "leave_type": leave_type,
            "start_date": from_date,
            "end_date": to_date,
            "days": days,
            "reason": reason,
            "status": "pending",
        },
    )


def update_leave_status(leave_id, status):
    rows = update_rows("leaves", {"id": f"eq.{leave_id}"}, {"status": status.lower()})
    return rows[0] if rows else None


def list_salary_records():
    employees = list_employees()
    employee_lookup = {str(e.get("id")): e for e in employees}
    rows = get_rows(
        "salaries",
        {
            "select": "id,employee_id,base_amount,effective_from",
            "order": "effective_from.desc",
        },
    )

    result = []
    for r in rows:
        emp = employee_lookup.get(str(r.get("employee_id")), {})
        result.append(
            {
                "id": r.get("id"),
                "employee_name": emp.get("full_name") or "-",
                "structure_name": f"Manual Salary ({r.get('base_amount') or 0})",
                "effective_from": r.get("effective_from"),
            }
        )

    return result


def create_salary_record(employee_id, monthly_salary, effective_from):
    return insert_row(
        "salaries",
        {
            "employee_id": employee_id,
            "base_amount": float(monthly_salary),
            "effective_from": effective_from,
        },
    )
