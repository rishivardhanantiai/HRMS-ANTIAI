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
            structure_id = request.form.get("structure_id", "").strip()
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
                # Check if a salary assignment already exists for this employee on this date
                cur.execute("""
                    SELECT id FROM employee_salary 
                    WHERE employee_id = %s AND effective_from = %s
                """, (employee_id, effective_from))
                existing = cur.fetchone()

                if existing:
                    cur.execute("""
                        UPDATE employee_salary
                        SET monthly_salary = %s, structure_id = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (monthly_salary, structure_id if structure_id else None, existing["id"]))
                else:
                    cur.execute("""
                        INSERT INTO employee_salary
                        (employee_id, monthly_salary, effective_from, structure_id)
                        VALUES (%s, %s, %s, %s)
                    """, (employee_id, monthly_salary, effective_from, structure_id if structure_id else None))

                conn.commit()
                flash("Salary assigned successfully.", "success")

            except Exception as e:
                conn.rollback()
                print("Error saving salary:", e)
                flash("Could not assign salary. Please try again.", "error")

            return redirect("/hrms/assign-salary")

        # Fetch employees
        cur.execute("""
            SELECT id, full_name, designation
            FROM hrms_employees
            WHERE status != 'Deleted'
            ORDER BY full_name
        """)
        employees = cur.fetchall()

        # Fetch salary structures
        cur.execute("""
            SELECT id, name
            FROM salary_structures
            ORDER BY name
        """)
        structures = cur.fetchall()

        return render_template(
            "assign_salary.html",
            employees=employees,
            salary_structures=structures
        )

    except Exception as e:
        print("Salary assignment DB failure, trying fallback:", e)
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
        return render_template("assign_salary.html", employees=employees, salary_structures=[])

    finally:
        try:
            release_db(conn, cur)
        except Exception:
            pass