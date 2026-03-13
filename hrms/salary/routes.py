from flask import Blueprint, render_template, request, redirect, session
from utils.auth import login_required
from utils.db import get_db, release_db

salary_bp = Blueprint("salary", __name__, url_prefix="/hrms")


@salary_bp.route("/assign-salary", methods=["GET", "POST"])
@login_required
def assign_employee_salary():

    role = session.get("role")

    if role not in ["HR", "Admin"]:
        return redirect("/dashboard")

    conn, cur = get_db(True)

    try:

        if request.method == "POST":
            employee_id = request.form["employee_id"]
            monthly_salary = request.form["monthly_salary"]
            effective_from = request.form["effective_from"]

            cur.execute("""
                INSERT INTO employee_salary
                (employee_id, monthly_salary, effective_from)
                VALUES (%s, %s, %s)
            """, (employee_id, monthly_salary, effective_from))

            conn.commit()

            return redirect("/hrms/assign-salary")

        # ✅ UPDATED QUERY (designation added)
        cur.execute("""
            SELECT id, full_name, designation
            FROM hrms_employees
            ORDER BY full_name
        """)
        employees = cur.fetchall()

        return render_template(
            "assign_salary.html",
            employees=employees
        )

    finally:
        release_db(conn, cur)