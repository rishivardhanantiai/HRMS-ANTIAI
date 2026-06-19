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
    rows = get_rows("hrms_roles", {"select": "id,role_name,description", "order": "role_name.asc"})
    return [
        {
            "id": r.get("id"),
            "role_name": r.get("role_name"),
            "description": r.get("description") or "",
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

    for row in get_rows("hrms_roles", {"select": "id,role_name"}):
        if str(row.get("role_name") or "").strip().lower() == target:
            return row
    return None


def get_role_by_id(role_id):
    return get_first_row("hrms_roles", {"select": "id,role_name,description", "id": f"eq.{role_id}"})


def create_role(role_name, description=""):
    return insert_row("hrms_roles", {"role_name": role_name, "description": description})


def update_role(role_id, role_name):
    rows = update_rows("hrms_roles", {"id": f"eq.{role_id}"}, {"role_name": role_name})
    return rows[0] if rows else None


def delete_role(role_id):
    return delete_rows("hrms_roles", {"id": f"eq.{role_id}"})


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
        "hrms_employees",
        {
            "select": "id,employee_code,full_name,email,phone,department,role_id,status,joining_date",
            "order": "created_at.desc",
        },
    )

    employees = []
    for r in rows:
        employees.append(
            {
                "id": r.get("id"),
                "employee_code": r.get("employee_code") or "",
                "full_name": r.get("full_name") or "-",
                "email": r.get("email"),
                "phone": r.get("phone"),
                "department": r.get("department"),
                "role_name": role_lookup.get(str(r.get("role_id"))),
                "status": (r.get("status") or "active").capitalize(),
                "designation": "Employee",
            }
        )

    return employees


def get_employee_by_id(employee_id):
    row = get_first_row(
        "hrms_employees",
        {
            "select": "id,employee_code,full_name,email,phone,department,role_id,status,joining_date",
            "id": f"eq.{employee_id}",
        },
    )
    if not row:
        return None

    role_lookup = roles_map()
    return {
        "id": row.get("id"),
        "employee_code": row.get("employee_code") or "",
        "full_name": row.get("full_name") or "-",
        "email": row.get("email"),
        "phone": row.get("phone"),
        "department": row.get("department"),
        "role_id": row.get("role_id"),
        "role_name": role_lookup.get(str(row.get("role_id"))),
        "status": (row.get("status") or "active").capitalize(),
        "designation": "Employee",
    }


def get_employee_by_email(email):
    return get_first_row("hrms_employees", {"select": "id,email", "email": f"eq.{email}"})


def create_employee(employee_code, full_name, email, phone, department, role_id):
    payload = {
        "employee_code": employee_code,
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "department": department,
        "role_id": role_id,
        "status": "active",
        "joining_date": str(date.today()),
    }
    return insert_row("hrms_employees", payload)


def update_employee(employee_id, full_name, email, phone, department, role_id):
    rows = update_rows(
        "hrms_employees",
        {"id": f"eq.{employee_id}"},
        {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "role_id": role_id,
            "department": department,
        },
    )
    return rows[0] if rows else None


def update_employee_status(employee_id, status):
    rows = update_rows("hrms_employees", {"id": f"eq.{employee_id}"}, {"status": status.lower()})
    return rows[0] if rows else None


def soft_delete_employee(employee_id):
    rows = update_rows("hrms_employees", {"id": f"eq.{employee_id}"}, {"status": "deleted"})
    return rows[0] if rows else None


def reassign_role(old_role_id, new_role_id):
    update_rows("hrms_employees", {"role_id": f"eq.{old_role_id}"}, {"role_id": new_role_id})


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
        "hrms_attendance",
        {"select": "id,employee_id,attendance_date,check_in_time,check_out_time,status", "order": "attendance_date.desc"},
    )

    result = []
    for r in rows:
        check_in = _safe_parse_iso(r.get("check_in_time"))
        check_out = _safe_parse_iso(r.get("check_out_time"))
        duration_minutes = 0
        if check_in and check_out:
            duration_minutes = max(0, int((check_out - check_in).total_seconds() // 60))

        emp = employee_lookup.get(str(r.get("employee_id")), {})
        result.append(
            {
                "id": r.get("id"),
                "employee_id": r.get("employee_id"),
                "attendance_date": r.get("attendance_date"),
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
        "hrms_attendance",
        {
            "select": "id,employee_id,attendance_date,check_in_time,check_out_time,status",
            "employee_id": f"eq.{employee_id}",
            "attendance_date": f"eq.{day_text}",
        },
    )


def check_in(employee_id, day_text, now_iso):
    existing = get_attendance_by_employee_day(employee_id, day_text)
    if existing:
        if existing.get("check_in_time"):
            return False, "Already checked in today."
        rows = update_rows(
            "hrms_attendance",
            {"id": f"eq.{existing.get('id')}"},
            {"check_in_time": now_iso},
        )
        return (bool(rows), None if rows else "Could not update check-in")

    status = "weekend" if date.fromisoformat(day_text).weekday() == 6 else "present"
    row = insert_row(
        "hrms_attendance",
        {
            "employee_id": employee_id,
            "attendance_date": day_text,
            "status": status,
            "check_in_time": now_iso,
            "is_locked": False,
        },
    )
    return (row is not None, None if row else "Could not create attendance record")


def check_out(employee_id, day_text, now_iso):
    existing = get_attendance_by_employee_day(employee_id, day_text)
    if not existing:
        return False, "Check-in not found."
    if not existing.get("check_in_time"):
        return False, "You haven't checked in."
    if existing.get("check_out_time"):
        return False, "Already checked out."

    rows = update_rows(
        "hrms_attendance",
        {"id": f"eq.{existing.get('id')}"},
        {"check_out_time": now_iso},
    )
    return (bool(rows), None if rows else "Could not update check-out")


def update_attendance_status(attendance_id, status):
    rows = update_rows("hrms_attendance", {"id": f"eq.{attendance_id}"}, {"status": status.lower()})
    return rows[0] if rows else None


def list_payrolls():
    employees = list_employees()
    employee_lookup = {str(e.get("id")): e for e in employees}
    rows = get_rows(
        "payroll_runs",
        {
            "select": "id,employee_id,month,year,gross_salary,net_salary,status",
            "order": "year.desc,month.desc",
        },
    )

    result = []
    for r in rows:
        emp = employee_lookup.get(str(r.get("employee_id")), {})
        result.append(
            {
                "id": r.get("id"),
                "payroll_id": r.get("id"),
                "employee_id": r.get("employee_id"),
                "month": r.get("month") or 0,
                "year": r.get("year") or 0,
                "gross_salary": r.get("gross_salary") or 0,
                "net_salary": r.get("net_salary") or 0,
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
        "employee_salary",
        {
            "select": "id,monthly_salary,structure_id,effective_from",
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
        "employee_salary",
        {
            "select": "id,monthly_salary,structure_id,effective_from",
            "employee_id": f"eq.{employee_id}",
            "order": "effective_from.desc",
            "limit": "1",
        },
    )
    return fallback[0] if fallback else None


def create_payroll_run(employee_id, month, year):
    period_start, period_end = _month_range(year, month)
    existing = get_first_row(
        "payroll_runs",
        {
            "select": "id,status",
            "employee_id": f"eq.{employee_id}",
            "month": f"eq.{month}",
            "year": f"eq.{year}",
        },
    )
    if existing:
        return {"error": "Payroll already generated for this period."}

    salary = _latest_salary_for_employee(employee_id, str(period_end))
    if not salary:
        # If a default monthly salary is configured via env, create a salary record
        # so payroll generation can proceed. Otherwise, fail with a clear error.
        default_salary = os.getenv("DEFAULT_MONTHLY_SALARY")
        if default_salary:
            try:
                monthly = float(default_salary)
                created = insert_row(
                    "employee_salary",
                    {
                        "employee_id": employee_id,
                        "monthly_salary": monthly,
                        "effective_from": str(period_end),
                    },
                )
                if created:
                    salary = created
            except Exception:
                salary = None

    if not salary:
        return {"error": "Salary record not found for employee."}

    gross = float(salary.get("monthly_salary") or 0)
    payload = {
        "employee_id": employee_id,
        "month": month,
        "year": year,
        "gross_salary": gross,
        "attendance_deduction": 0,
        "pf": 0,
        "variable_pay": 0,
        "bonus": 0,
        "reimbursements": 0,
        "net_salary": gross,
        "status": "draft",
        "generated_at": datetime.now().isoformat(),
        "financial_year": f"{year-1}-{year}" if month >= 4 else f"{year}-{year+1}",
    }
    row = insert_row("payroll_runs", payload)
    if not row:
        return {"error": "Could not generate payroll."}
    return {"success": True, "net_salary": gross, "id": row.get("id")}


def get_payroll_by_id(payroll_id):
    row = get_first_row(
        "payroll_runs",
        {
            "select": "id,employee_id,month,year,gross_salary,attendance_deduction,pf,variable_pay,bonus,reimbursements,net_salary,status,financial_year,generated_at,generated_by",
            "id": f"eq.{payroll_id}",
        },
    )
    if not row:
        return None

    employee = get_employee_by_id(row.get("employee_id")) or {}
    return {
        "id": row.get("id"),
        "employee_id": row.get("employee_id"),
        "full_name": employee.get("full_name") or "-",
        "designation": employee.get("designation") or "Employee",
        "month": row.get("month") or 0,
        "year": row.get("year") or 0,
        "gross_salary": row.get("gross_salary") or 0,
        "net_salary": row.get("net_salary") or 0,
        "status": str(row.get("status") or "draft").upper(),
        "financial_year": row.get("financial_year") or "-",
        "variable_pay": row.get("variable_pay") or 0,
        "bonus": row.get("bonus") or 0,
        "reimbursements": row.get("reimbursements") or 0,
        "attendance_deduction": row.get("attendance_deduction") or 0,
        "pf": row.get("pf") or 0,
        "tax": 0,
    }


def update_payroll_status(payroll_id, status):
    rows = update_rows("payroll_runs", {"id": f"eq.{payroll_id}"}, {"status": status.lower()})
    return rows[0] if rows else None


def update_payroll_net(payroll_id, new_net_salary):
    rows = update_rows(
        "payroll_runs",
        {"id": f"eq.{payroll_id}", "status": "eq.draft"},
        {"net_salary": float(new_net_salary)},
    )
    return rows[0] if rows else None


def delete_payroll_if_draft(payroll_id):
    return delete_rows("payroll_runs", {"id": f"eq.{payroll_id}", "status": "eq.draft"})


def list_my_payrolls(employee_id):
    payrolls = list_payrolls()
    return [p for p in payrolls if str(p.get("employee_id")) == str(employee_id)]


def list_leaves_manage():
    employees = list_employees()
    employee_lookup = {str(e.get("id")): e for e in employees}
    rows = get_rows(
        "leave_applications",
        {
            "select": "id,employee_id,leave_type_id,from_date,to_date,status",
            "order": "from_date.desc",
        },
    )

    leave_types = {str(x.get("id")): x.get("name") for x in list_leave_types()}

    result = []
    for r in rows:
        emp = employee_lookup.get(str(r.get("employee_id")), {})
        result.append(
            {
                "id": r.get("id"),
                "full_name": emp.get("full_name") or "-",
                "type": leave_types.get(str(r.get("leave_type_id")), "Leave"),
                "from_date": r.get("from_date"),
                "to_date": r.get("to_date"),
                "status": (r.get("status") or "pending").capitalize(),
            }
        )

    return result


def list_leave_types():
    rows = get_rows("leave_types", {"select": "id,name", "order": "name.asc"})
    if rows:
        return [{"id": r.get("id"), "name": r.get("name")} for r in rows]
    return [
        {"id": "casual", "name": "Casual"},
        {"id": "sick", "name": "Sick"},
        {"id": "paid", "name": "Paid"},
    ]


def list_employee_leaves(employee_id):
    rows = get_rows(
        "leave_applications",
        {
            "select": "id,leave_type_id,from_date,to_date,status",
            "employee_id": f"eq.{employee_id}",
            "order": "from_date.desc",
        },
    )
    leave_types = {str(x.get("id")): x.get("name") for x in list_leave_types()}
    result = []
    for r in rows:
        result.append(
            {
                "id": r.get("id"),
                "leave_type": leave_types.get(str(r.get("leave_type_id")), "Leave"),
                "from_date": r.get("from_date"),
                "to_date": r.get("to_date"),
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

    # Resolve leave_type to an id suitable for the DB. If a non-UUID (e.g., "casual")
    # is provided, try to find a matching leave_types row by name; if not found,
    # create one and use its id. This allows legacy string identifiers to work.
    resolved_leave_type = leave_type
    try:
        import uuid

        # If this parses as a UUID, use as-is
        uuid.UUID(str(leave_type))
    except Exception:
        # Try to find a leave type by name
        candidates = get_rows("leave_types", {"select": "id,name"})
        match_id = None
        for c in candidates:
            if str(c.get("name") or "").strip().lower() == str(leave_type).strip().lower():
                match_id = c.get("id")
                break

        if match_id:
            resolved_leave_type = match_id
        else:
            # Create a new leave type row and use its id if creation succeeds
            created = insert_row("leave_types", {"name": leave_type})
            if created and isinstance(created, dict) and created.get("id"):
                resolved_leave_type = created.get("id")

    return insert_row(
        "leave_applications",
        {
            "employee_id": employee_id,
            "leave_type_id": resolved_leave_type,
            "from_date": from_date,
            "to_date": to_date,
            "reason": reason,
            "status": "pending",
        },
    )


def update_leave_status(leave_id, status):
    rows = update_rows("leave_applications", {"id": f"eq.{leave_id}"}, {"status": status.lower()})
    return rows[0] if rows else None


def list_salary_records():
    employees = list_employees()
    employee_lookup = {str(e.get("id")): e for e in employees}
    rows = get_rows(
        "employee_salary",
        {
            "select": "id,employee_id,structure_id,monthly_salary,effective_from",
            "order": "effective_from.desc",
        },
    )

    structures = {str(x.get("id")): x.get("name") for x in get_rows("salary_structures", {"select": "id,name"})}

    result = []
    for r in rows:
        emp = employee_lookup.get(str(r.get("employee_id")), {})
        result.append(
            {
                "id": r.get("id"),
                "employee_name": emp.get("full_name") or "-",
                "structure_name": structures.get(str(r.get("structure_id")), f"Manual Salary ({r.get('monthly_salary') or 0})"),
                "effective_from": r.get("effective_from"),
            }
        )

    return result


def create_salary_record(employee_id, monthly_salary, effective_from):
    return insert_row(
        "employee_salary",
        {
            "employee_id": employee_id,
            "monthly_salary": float(monthly_salary),
            "effective_from": effective_from,
        },
    )

def upload_file_bytes(file_bytes, object_key, content_type="application/pdf"):
    supabase_url = _supabase_url()
    service_key = os.getenv("SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    bucket = os.getenv("SUPABASE_RESUME_BUCKET", "resumes")
    if not supabase_url or not service_key:
        return None

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": content_type,
    }
    
    upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{object_key}"
    try:
        response = httpx.post(upload_url, content=file_bytes, headers=headers, timeout=30.0)
        if response.status_code in (200, 201):
            return f"{supabase_url}/storage/v1/object/public/{bucket}/{object_key}"
        return None
    except Exception as e:
        print("Error uploading to supabase:", e)
        return None
