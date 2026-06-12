print("HRMS ROLES ROUTES LOADED")

from flask import Blueprint, render_template, request, redirect
from utils.auth import login_required
from utils.db import get_db, release_db
from utils import supabase_rest

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
    try:
        conn, cur = get_db(True)

        cur.execute("""
            SELECT *
            FROM hrms_roles
            ORDER BY id DESC
        """)

        roles = cur.fetchall()
        release_db(conn, cur)
    except Exception:
        roles = supabase_rest.list_roles()

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

        try:
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
        except Exception:
            if supabase_rest.get_role_by_name(role_name):
                return "Role already exists", 400
            if not supabase_rest.create_role(role_name, description):
                return "Could not create role", 500

        return redirect("/hrms/roles/ui")

    return render_template("hrms/add_role.html")


# =========================
# Edit Role
# =========================
@roles_bp.route("/edit/<role_id>", methods=["GET", "POST"])
@login_required
def edit_role(role_id):
    try:
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
    except Exception:
        role_obj = supabase_rest.get_role_by_id(role_id)
        if not role_obj:
            return "Role not found", 404

        role = {
            "id": role_obj.get("id"),
            "role_name": role_obj.get("name"),
            "description": "",
        }

        if request.method == "POST":
            role_name = request.form.get("role_name", "").strip()
            if not role_name:
                return "Role name required", 400
            dup = supabase_rest.get_role_by_name(role_name)
            if dup and str(dup.get("id")) != str(role_id):
                return "Role already exists", 400
            if not supabase_rest.update_role(role_id, role_name):
                return "Could not update role", 500
            return redirect("/hrms/roles/ui")

        return render_template("hrms/edit_role.html", role=role)

# =========================
# Delete Role (Safe Delete)
# =========================
@roles_bp.route("/delete/<role_id>")
@login_required
def delete_role(role_id):
    try:
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

            if str(fallback_role_id) == str(role_id):
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
    except Exception:
        role_row = supabase_rest.get_role_by_id(role_id)
        if not role_row:
            return "Role not found", 404

        employees = supabase_rest.get_rows("employees", {"select": "id", "role_id": f"eq.{role_id}"})
        if employees:
            fallback = supabase_rest.get_role_by_name("Unassigned")
            if not fallback:
                fallback = supabase_rest.create_role("Unassigned")
            if not fallback:
                return "Could not create fallback role", 500
            if str(fallback.get("id")) == str(role_id):
                return "Cannot delete fallback role while employees are assigned.", 400
            supabase_rest.reassign_role(role_id, fallback.get("id"))

        supabase_rest.delete_role(role_id)
        return redirect("/hrms/roles/ui")
