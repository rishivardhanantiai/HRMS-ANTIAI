print("HRMS ROLES ROUTES LOADED")

from flask import Blueprint, render_template, request, redirect
from utils.auth import login_required
from utils.db import get_db, release_db

# =========================
# Blueprint Configuration
# =========================
roles_bp = Blueprint(
    "roles",
    __name__,
    url_prefix="/hrms/roles"
)

# =========================
# Health / Test Route
# =========================
@roles_bp.route("/", methods=["GET"])
@login_required
def roles_home():
    return "HRMS Roles Module Running"

# =========================
# Roles List UI
# =========================
@roles_bp.route("/ui")
@login_required
def roles_ui():

    conn, cur = get_db(True)

    cur.execute("""
        SELECT *
        FROM hrms_roles
        ORDER BY id DESC
    """)

    roles = cur.fetchall()
    release_db(conn, cur)

    return render_template("hrms/roles.html", roles=roles)

# =========================
# Add Role
# =========================
@roles_bp.route("/add", methods=["GET", "POST"])
@login_required
def add_role():

    if request.method == "POST":

        role_name = request.form.get("role_name", "").strip()
        description = request.form.get("description", "").strip()

        if not role_name:
            return "Role name required", 400

        conn, cur = get_db(True)

        # Duplicate Role Check
        cur.execute(
            "SELECT id FROM hrms_roles WHERE LOWER(role_name)=LOWER(%s)",
            (role_name,)
        )

        if cur.fetchone():
            release_db(conn, cur)
            return "Role already exists", 400

        cur.execute("""
            INSERT INTO hrms_roles (role_name, description)
            VALUES (%s, %s)
        """, (role_name, description))

        conn.commit()
        release_db(conn, cur)

        return redirect("/hrms/roles/ui")

    return render_template("hrms/add_role.html")

# =========================
# Delete Role (Safe Delete)
# =========================
@roles_bp.route("/delete/<int:role_id>")
@login_required
def delete_role(role_id):

    conn, cur = get_db(True)

    # Check role assignment
    cur.execute("""
        SELECT COUNT(*) AS total
        FROM hrms_employees
        WHERE role_id = %s
    """, (role_id,))

    assigned_count = cur.fetchone()["total"]

    if assigned_count > 0:
        release_db(conn, cur)
        return "Cannot delete role. Employees are assigned.", 400

    cur.execute("DELETE FROM hrms_roles WHERE id=%s", (role_id,))
    conn.commit()

    release_db(conn, cur)

    return redirect("/hrms/roles/ui")
