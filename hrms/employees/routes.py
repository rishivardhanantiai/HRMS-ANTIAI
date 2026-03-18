print("HRMS EMPLOYEES ROUTES LOADED")

from flask import Blueprint, request, render_template, jsonify, redirect, session
from datetime import date
from utils.db import get_db, release_db
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

    return render_template("hrms/employees.html", employees=employees)


# =========================
# EMPLOYEES LIST API
# =========================
@employees_bp.route("/list")
@login_required
def employees_list():

    if not hr_admin_required():
        return {"error": "Unauthorized"}, 403

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

    return jsonify({"employees": employees})


# =========================
# ADD EMPLOYEE UI
# =========================
@employees_bp.route("/add/ui")
@login_required
def add_employee_ui():

    if not hr_admin_required():
        return redirect("/dashboard")

    conn, cur = get_db(True)

    cur.execute("SELECT id, role_name FROM hrms_roles ORDER BY role_name")
    roles = cur.fetchall()

    cur.execute("SELECT id, name FROM salary_structures ORDER BY name")
    salary_structures = cur.fetchall()

    release_db(conn, cur)

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

    conn, cur = get_db(True)

    try:
        # -------- Duplicate Employee Email --------
        cur.execute("SELECT id FROM hrms_employees WHERE email=%s", (data["email"],))
        if cur.fetchone():
            return {"error": "Employee email already exists"}, 400

        # -------- Duplicate Login Email --------
        cur.execute("SELECT id FROM hrms_users WHERE email=%s", (data["email"],))
        if cur.fetchone():
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
            int(data["role_id"]),
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
            int(data["role_id"]),
            employee_id
        ))

        # -------- Optional Salary Assignment --------
        if data.get("structure_id"):
            cur.execute("""
                INSERT INTO employee_salary
                (employee_id, structure_id, effective_from)
                VALUES (%s,%s,CURRENT_DATE)
            """, (
                employee_id,
                int(data["structure_id"])
            ))

        conn.commit()

    except Exception as e:
        conn.rollback()
        release_db(conn, cur)
        return {"error": str(e)}, 500

    release_db(conn, cur)
    return redirect("/hrms/employees/ui")


# =========================
# EDIT EMPLOYEE UI
# =========================
@employees_bp.route("/<int:employee_id>/edit", methods=["GET"])
@login_required
def edit_employee_ui(employee_id):

    if not hr_admin_required():
        return redirect("/dashboard")

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

    return render_template(
        "hrms/edit_employee.html",
        employee=employee,
        roles=roles
    )


# =========================
# UPDATE EMPLOYEE
# =========================
@employees_bp.route("/<int:employee_id>/edit", methods=["POST"])
@login_required
def edit_employee(employee_id):

    if not hr_admin_required():
        return redirect("/dashboard")

    data = request.form
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

    return redirect("/hrms/employees/ui")


# =========================
# CHANGE STATUS
# =========================
@employees_bp.route("/<int:employee_id>/status", methods=["POST"])
@login_required
def change_employee_status(employee_id):

    if not hr_admin_required():
        return redirect("/dashboard")

    new_status = request.form.get("status")

    if new_status not in ["Active", "Inactive"]:
        return {"error": "Invalid status"}, 400

    conn, cur = get_db(True)

    cur.execute(
        "UPDATE hrms_employees SET status=%s WHERE id=%s",
        (new_status, employee_id)
    )

    conn.commit()
    release_db(conn, cur)

    return {"message": "Status updated"}, 200


# =========================
# SOFT DELETE
# =========================
@employees_bp.route("/<int:employee_id>/delete", methods=["POST"])
@login_required
def delete_employee(employee_id):

    if not hr_admin_required():
        return redirect("/dashboard")

    conn, cur = get_db(True)

    cur.execute("""
        UPDATE hrms_employees
        SET status='Deleted'
        WHERE id=%s
    """, (employee_id,))

    conn.commit()
    release_db(conn, cur)

    return {"message": "Employee deleted"}, 200