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
# Edit Role
# =========================
@roles_bp.route("/edit/<int:role_id>", methods=["GET", "POST"])
@login_required
def edit_role(role_id):

    conn, cur = get_db(True)

    cur.execute(
        "SELECT id, role_name, description FROM hrms_roles WHERE id=%s",
        (role_id,)
    )
    role = cur.fetchone()

    if not role:
        release_db(conn, cur)
        return "Role not found", 404

    if request.method == "POST":
        role_name = request.form.get("role_name", "").strip()
        description = request.form.get("description", "").strip()

        if not role_name:
            release_db(conn, cur)
            return "Role name required", 400

        cur.execute(
            """
            SELECT id
            FROM hrms_roles
            WHERE LOWER(role_name)=LOWER(%s)
              AND id<>%s
            """,
            (role_name, role_id)
        )
        if cur.fetchone():
            release_db(conn, cur)
            return "Role already exists", 400

        cur.execute(
            """
            UPDATE hrms_roles
            SET role_name=%s,
                description=%s
            WHERE id=%s
            """,
            (role_name, description, role_id)
        )

        conn.commit()
        release_db(conn, cur)

        return redirect("/hrms/roles/ui")

    release_db(conn, cur)
    return render_template("hrms/edit_role.html", role=role)

# =========================
# Delete Role (Safe Delete)
# =========================
@roles_bp.route("/delete/<int:role_id>")
@login_required
def delete_role(role_id):

    conn, cur = get_db(True)

    # Ensure the role exists first.
    cur.execute(
        "SELECT id FROM hrms_roles WHERE id=%s",
        (role_id,)
    )
    role_row = cur.fetchone()
    if not role_row:
        release_db(conn, cur)
        return "Role not found", 404

    # Check if any employees are assigned to this role.
    cur.execute("""
        SELECT COUNT(*) AS total
        FROM hrms_employees
        WHERE role_id = %s
    """, (role_id,))
    assigned_count = cur.fetchone()["total"]

    if assigned_count > 0:
        # Move assigned employees to a fallback role so deletion can proceed.
        cur.execute(
            "SELECT id FROM hrms_roles WHERE LOWER(role_name)=LOWER(%s)",
            ("Unassigned",)
        )
        fallback = cur.fetchone()

        if fallback:
            fallback_role_id = fallback["id"]
        else:
            cur.execute(
                "INSERT INTO hrms_roles (role_name, description) VALUES (%s, %s) RETURNING id",
                ("Unassigned", "System fallback role for removed assignments")
            )
            fallback_role_id = cur.fetchone()["id"]

        if fallback_role_id == role_id:
            release_db(conn, cur)
            return "Cannot delete fallback role while employees are assigned.", 400

        cur.execute(
            "UPDATE hrms_employees SET role_id=%s WHERE role_id=%s",
            (fallback_role_id, role_id)
        )

    cur.execute("DELETE FROM hrms_roles WHERE id=%s", (role_id,))
    conn.commit()

    release_db(conn, cur)

    return redirect("/hrms/roles/ui")
