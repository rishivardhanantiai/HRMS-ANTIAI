print("HRMS EMPLOYEES ROUTES LOADED")

from flask import Blueprint, request, render_template, jsonify, redirect, session
from datetime import date
from utils.db import get_db, release_db
from utils import supabase_rest
from utils.auth import login_required
from werkzeug.security import generate_password_hash


employees_bp = Blueprint(
    "employees",
    __name__,
    url_prefix="/hrms/employees"
)


# =========================
# ROLE CHECK HELPER
# =========================
def hr_admin_required():
    return session.get("role") in ["HR", "Admin"]


# =========================
# EMPLOYEES UI
# =========================
@employees_bp.route("/ui")
@login_required
def employees_ui():

    if not hr_admin_required():
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        cur.execute("""
            SELECT 
                e.id,
                e.employee_code,
                e.full_name,
                e.email,
                e.department,
                e.status,
                r.role_name
            FROM hrms_employees e
            LEFT JOIN hrms_roles r ON e.role_id = r.id
            WHERE e.status != 'Deleted'
            ORDER BY e.id DESC
        """)

        employees = cur.fetchall()
        release_db(conn, cur)
    except Exception:
        employees = supabase_rest.list_employees()

    return render_template("hrms/employees.html", employees=employees)


# =========================
# EMPLOYEES LIST API
# =========================
@employees_bp.route("/list")
@login_required
def employees_list():

    if not hr_admin_required():
        return {"error": "Unauthorized"}, 403

    try:
        conn, cur = get_db(True)

        cur.execute("""
            SELECT
                e.id,
                e.full_name,
                e.email,
                e.department,
                e.status,
                r.role_name
            FROM hrms_employees e
            LEFT JOIN hrms_roles r ON e.role_id = r.id
            WHERE e.status != 'Deleted'
            ORDER BY e.id DESC
        """)

        employees = cur.fetchall()
        release_db(conn, cur)
    except Exception:
        employees = supabase_rest.list_employees()

    return jsonify({"employees": employees})


# =========================
# ADD EMPLOYEE UI
# =========================
@employees_bp.route("/add/ui")
@login_required
def add_employee_ui():

    if not hr_admin_required():
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        cur.execute("SELECT id, role_name FROM hrms_roles ORDER BY role_name")
        roles = cur.fetchall()

        cur.execute("SELECT id, name FROM salary_structures ORDER BY name")
        salary_structures = cur.fetchall()

        release_db(conn, cur)
    except Exception:
        roles = supabase_rest.list_roles()
        salary_structures = []

    return render_template(
        "hrms/add_employee.html",
        roles=roles,
        salary_structures=salary_structures
    )


# =========================
# ADD EMPLOYEE
# =========================
@employees_bp.route("/add", methods=["POST"])
@login_required
def add_employee():

    if not hr_admin_required():
        return redirect("/dashboard")

    data = request.form

    required_fields = [
        "employee_code",
        "full_name",
        "email",
        "role_id",
        "password"
    ]

    for field in required_fields:
        if not data.get(field):
            return {"error": f"{field} is required"}, 400

    try:
        conn, cur = get_db(True)

        # -------- Duplicate Employee Email --------
        cur.execute("SELECT id FROM hrms_employees WHERE email=%s", (data["email"],))
        if cur.fetchone():
            release_db(conn, cur)
            return {"error": "Employee email already exists"}, 400

        # -------- Duplicate Login Email --------
        cur.execute("SELECT id FROM hrms_users WHERE email=%s", (data["email"],))
        if cur.fetchone():
            release_db(conn, cur)
            return {"error": "Login email already exists"}, 400

        hashed_password = generate_password_hash(data["password"])
        joining_date = data.get("joining_date") or date.today()

        # -------- Create Employee Record --------
        cur.execute("""
            INSERT INTO hrms_employees
            (employee_code, full_name, email, phone, department, role_id, joining_date, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'Active')
            RETURNING id
        """, (
            data["employee_code"],
            data["full_name"],
            data["email"],
            data.get("phone"),
            data.get("department"),
            data["role_id"],
            joining_date
        ))

        employee_id = cur.fetchone()["id"]

        # -------- Create Login Account --------
        cur.execute("""
            INSERT INTO hrms_users (email, password, role_id, employee_id)
            VALUES (%s,%s,%s,%s)
        """, (
            data["email"],
            hashed_password,
            data["role_id"],
            employee_id
        ))

        conn.commit()
        release_db(conn, cur)
        return redirect("/hrms/employees/ui")

    except Exception:
        existing = supabase_rest.get_employee_by_email(data["email"])
        if existing:
            return {"error": "Employee email already exists"}, 400

        created = supabase_rest.create_employee(
            employee_code=data["employee_code"],
            full_name=data["full_name"],
            email=data["email"],
            phone=data.get("phone"),
            department=data.get("department"),
            role_id=data["role_id"],
        )
        if not created:
            return {"error": "Could not create employee"}, 500

        supabase_rest.create_auth_user(data["email"], data["password"])
        return redirect("/hrms/employees/ui")


# =========================
# EDIT EMPLOYEE UI
# =========================
@employees_bp.route("/<employee_id>/edit", methods=["GET"])
@login_required
def edit_employee_ui(employee_id):

    if not hr_admin_required():
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        cur.execute("""
            SELECT id, full_name, email, phone, department, role_id
            FROM hrms_employees
            WHERE id=%s AND status != 'Deleted'
        """, (employee_id,))
        employee = cur.fetchone()

        if not employee:
            release_db(conn, cur)
            return "Employee not found", 404

        cur.execute("SELECT id, role_name FROM hrms_roles ORDER BY role_name")
        roles = cur.fetchall()

        release_db(conn, cur)
    except Exception:
        employee = supabase_rest.get_employee_by_id(employee_id)
        if not employee:
            return "Employee not found", 404
        roles = supabase_rest.list_roles()

    return render_template(
        "hrms/edit_employee.html",
        employee=employee,
        roles=roles
    )


# =========================
# UPDATE EMPLOYEE
# =========================
@employees_bp.route("/<employee_id>/edit", methods=["POST"])
@login_required
def edit_employee(employee_id):

    if not hr_admin_required():
        return redirect("/dashboard")

    data = request.form
    try:
        conn, cur = get_db(True)

        cur.execute("""
            UPDATE hrms_employees
            SET full_name=%s,
                email=%s,
                phone=%s,
                department=%s,
                role_id=%s
            WHERE id=%s
        """, (
            data["full_name"],
            data["email"],
            data.get("phone"),
            data.get("department"),
            data["role_id"],
            employee_id
        ))

        conn.commit()
        release_db(conn, cur)
    except Exception:
        supabase_rest.update_employee(
            employee_id=employee_id,
            full_name=data["full_name"],
            email=data["email"],
            phone=data.get("phone"),
            department=data.get("department"),
            role_id=data["role_id"],
        )

    return redirect("/hrms/employees/ui")


# =========================
# CHANGE STATUS
# =========================
@employees_bp.route("/<employee_id>/status", methods=["POST"])
@login_required
def change_employee_status(employee_id):

    if not hr_admin_required():
        return redirect("/dashboard")

    new_status = request.form.get("status")

    if new_status not in ["Active", "Inactive"]:
        return {"error": "Invalid status"}, 400

    try:
        conn, cur = get_db(True)

        cur.execute(
            "UPDATE hrms_employees SET status=%s WHERE id=%s",
            (new_status, employee_id)
        )

        conn.commit()
        release_db(conn, cur)
    except Exception:
        supabase_rest.update_employee_status(employee_id, new_status)

    return {"message": "Status updated"}, 200


# =========================
# SOFT DELETE
# =========================
@employees_bp.route("/<employee_id>/delete", methods=["POST"])
@login_required
def delete_employee(employee_id):

    if not hr_admin_required():
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        cur.execute("""
            UPDATE hrms_employees
            SET status='Deleted'
            WHERE id=%s
        """, (employee_id,))

        conn.commit()
        release_db(conn, cur)
    except Exception:
        supabase_rest.soft_delete_employee(employee_id)

    return {"message": "Employee deleted"}, 200