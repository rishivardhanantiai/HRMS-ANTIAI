print("HRMS EMPLOYEES ROUTES LOADED")

from flask import Blueprint, request, render_template, jsonify, redirect
from datetime import date
from utils.db import get_db, release_db
from utils.auth import login_required

employees_bp = Blueprint(
    "employees",
    __name__,
    url_prefix="/hrms/employees"
)

# =========================
# HEALTH CHECK
# =========================
@employees_bp.route("/", methods=["GET"])
def employees_home():
    return "HRMS Employees Module Running"


# =========================
# EMPLOYEES UI
# =========================
@employees_bp.route("/ui")
@login_required
def employees_ui():
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
        ORDER BY e.id DESC
    """)

    employees = cur.fetchall()
    release_db(conn, cur)

    return render_template("hrms/employees.html", employees=employees)


# =========================
# ADD EMPLOYEE UI
# =========================
@employees_bp.route("/add/ui")
@login_required
def add_employee_ui():
    conn, cur = get_db(True)

    cur.execute("SELECT id, role_name FROM hrms_roles ORDER BY role_name")
    roles = cur.fetchall()

    release_db(conn, cur)

    return render_template("hrms/add_employee.html", roles=roles)


# =========================
# ADD EMPLOYEE (API + UI)
# =========================
@employees_bp.route("/add", methods=["POST"])
@login_required
def add_employee():

    data = request.form or (request.json if request.is_json else {})

    required_fields = ["employee_code", "full_name", "email", "role_id"]
    for field in required_fields:
        if not data.get(field):
            return {"error": f"{field} is required"}, 400

    conn, cur = get_db(True)

    # ---- Duplicate Email Check ----
    cur.execute(
        "SELECT id FROM hrms_employees WHERE email=%s",
        (data["email"],)
    )
    if cur.fetchone():
        release_db(conn, cur)
        return {"error": "Employee with this email already exists"}, 400

    # ---- Role Existence Check ----
    cur.execute(
        "SELECT id FROM hrms_roles WHERE id=%s",
        (data["role_id"],)
    )
    if not cur.fetchone():
        release_db(conn, cur)
        return {"error": "Invalid role selected"}, 400

    joining_date = data.get("joining_date") or date.today()

    cur.execute("""
        INSERT INTO hrms_employees
        (employee_code, full_name, email, phone, department, role_id, joining_date, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        data["employee_code"],
        data["full_name"],
        data["email"],
        data.get("phone"),
        data.get("department"),
        int(data["role_id"]),
        joining_date,
        "Active"
    ))

    conn.commit()
    release_db(conn, cur)

    # ---- Redirect for UI ----
    if not request.is_json:
        return redirect("/hrms/employees/ui")

    return {"message": "Employee added successfully"}, 201


# =========================
# LIST EMPLOYEES API
# =========================
@employees_bp.route("/list", methods=["GET"])
@login_required
def list_employees():
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

    return jsonify({"employees": employees})


# =========================
# CHANGE EMPLOYEE STATUS
# =========================
@employees_bp.route("/<int:employee_id>/status", methods=["POST"])
@login_required
def change_employee_status(employee_id):

    new_status = (
        request.form.get("status")
        or (request.json.get("status") if request.is_json else None)
    )

    if not new_status:
        return {"error": "status is required"}, 400

    new_status = new_status.strip().capitalize()

    if new_status not in ["Active", "Inactive"]:
        return {"error": "Invalid status"}, 400

    conn, cur = get_db(True)

    cur.execute(
        "UPDATE hrms_employees SET status=%s WHERE id=%s",
        (new_status, employee_id)
    )

    if cur.rowcount == 0:
        release_db(conn, cur)
        return {"error": "Employee not found"}, 404

    conn.commit()
    release_db(conn, cur)

    return {"message": f"Employee status updated to {new_status}"}, 200


# =========================
# UPDATE EMPLOYEE
# =========================
@employees_bp.route("/<int:employee_id>/update", methods=["POST"])
@login_required
def update_employee(employee_id):

    data = request.form or (request.json if request.is_json else {})

    allowed_fields = ["full_name", "department", "phone"]
    update_data = {k: data.get(k) for k in allowed_fields if data.get(k)}

    if not update_data:
        return {"error": "No valid fields provided"}, 400

    conn, cur = get_db(True)

    set_clause = ", ".join([f"{k}=%s" for k in update_data.keys()])
    values = list(update_data.values()) + [employee_id]

    cur.execute(
        f"UPDATE hrms_employees SET {set_clause} WHERE id=%s",
        values
    )

    if cur.rowcount == 0:
        release_db(conn, cur)
        return {"error": "Employee not found"}, 404

    conn.commit()
    release_db(conn, cur)

    return {"message": "Employee updated successfully"}, 200

@employees_bp.route("/<int:employee_id>/edit")
@login_required
def edit_employee_ui(employee_id):

    conn, cur = get_db(True)

    cur.execute("SELECT * FROM hrms_employees WHERE id=%s", (employee_id,))
    employee = cur.fetchone()

    cur.execute("SELECT id, role_name FROM hrms_roles")
    roles = cur.fetchall()

    release_db(conn, cur)

    return render_template(
        "hrms/edit_employee.html",
        employee=employee,
        roles=roles
    )

@employees_bp.route("/<int:employee_id>/edit", methods=["POST"])
@login_required
def edit_employee(employee_id):

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
# DELETE EMPLOYEE (Soft Delete)
# =========================
@employees_bp.route("/<int:employee_id>/delete", methods=["POST"])
@login_required
def delete_employee(employee_id):

    conn, cur = get_db()

    cur.execute("""
        UPDATE hrms_employees
        SET status='Deleted'
        WHERE id=%s
    """, (employee_id,))

    conn.commit()
    release_db(conn, cur)

    return {"message": "Employee deleted"}, 200
