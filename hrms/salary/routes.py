from flask import Blueprint, render_template, request, redirect, session, flash
from utils.auth import login_required
from utils.db import get_db, release_db
from utils import supabase_rest

salary_bp = Blueprint("salary", __name__, url_prefix="/hrms")


@salary_bp.route("/assign-salary", methods=["GET", "POST"])
@login_required
def assign_employee_salary():

    role = session.get("role")

    if role not in ["HR", "Admin"]:
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        if request.method == "POST":
            employee_id = request.form.get("employee_id", "").strip()
            monthly_salary = request.form.get("monthly_salary", "").strip()
            effective_from = request.form.get("effective_from", "").strip()

            if not employee_id or not monthly_salary or not effective_from:
                flash("Please fill all required fields.", "error")
                return redirect("/hrms/assign-salary")

            try:
                if float(monthly_salary) <= 0:
                    flash("Monthly salary must be greater than 0.", "error")
                    return redirect("/hrms/assign-salary")
            except ValueError:
                flash("Monthly salary must be a valid number.", "error")
                return redirect("/hrms/assign-salary")

            try:
                cur.execute("""
                    INSERT INTO employee_salary
                    (employee_id, monthly_salary, effective_from)
                    VALUES (%s, %s, %s)
                """, (employee_id, monthly_salary, effective_from))

                conn.commit()
                flash("Salary assigned successfully.", "success")

            except Exception:
                conn.rollback()
                flash("Could not assign salary. Please try again.", "error")

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

    except Exception:
        if request.method == "POST":
            employee_id = request.form.get("employee_id", "").strip()
            monthly_salary = request.form.get("monthly_salary", "").strip()
            effective_from = request.form.get("effective_from", "").strip()

            if not employee_id or not monthly_salary or not effective_from:
                flash("Please fill all required fields.", "error")
                return redirect("/hrms/assign-salary")

            created = supabase_rest.create_salary_record(
                employee_id=employee_id,
                monthly_salary=monthly_salary,
                effective_from=effective_from,
            )
            if created:
                flash("Salary assigned successfully.", "success")
            else:
                flash("Could not assign salary. Please try again.", "error")
            return redirect("/hrms/assign-salary")

        employees = [
            {
                "id": e.get("id"),
                "full_name": e.get("full_name"),
                "designation": e.get("designation") or "Employee",
            }
            for e in supabase_rest.list_employees()
        ]
        return render_template("assign_salary.html", employees=employees)

    finally:
        try:
            release_db(conn, cur)
        except Exception:
            pass