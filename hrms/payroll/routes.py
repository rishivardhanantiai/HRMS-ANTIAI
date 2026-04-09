from flask import Blueprint, render_template, request, session, redirect, flash
from utils.auth import login_required
from services.payroll_engine import generate_payroll
from utils.db import get_db, release_db
from utils import supabase_rest
from constants import PAYROLL_STATUS
from datetime import datetime
from reportlab.pdfgen import canvas
from flask import send_file
import io
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import units

payroll_bp = Blueprint("payroll", __name__, url_prefix="/hrms")

# ===============================
# DASHBOARD
# ===============================

@payroll_bp.route("/payroll/")
@login_required
def payroll_dashboard():

    role = session.get("role")

    if role not in ["HR", "Admin"]:
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        # Payroll runs
        cur.execute("""
        SELECT 
            p.id AS payroll_id,
            p.employee_id,
            p.month,
            p.year,
            p.net_salary,
            p.status,
            e.full_name
        FROM payroll_runs p
        JOIN hrms_employees e
            ON p.employee_id = e.id
        ORDER BY p.year DESC, p.month DESC
        """)

        payroll_runs = cur.fetchall()

        # ✅ UPDATED EMPLOYEE QUERY (designation added)
        cur.execute("""
            SELECT id, full_name, designation
            FROM hrms_employees
            ORDER BY full_name
        """)
        employees = cur.fetchall()

        release_db(conn, cur)
    except Exception:
        payroll_runs = supabase_rest.list_payrolls()
        employees = [
            {
                "id": e.get("id"),
                "full_name": e.get("full_name"),
                "designation": e.get("designation") or "Employee",
            }
            for e in supabase_rest.list_employees()
        ]

    return render_template(
        "hrms/payroll_dashboard.html",
        payroll_runs=payroll_runs,
        employees=employees
    )


# ===============================
# GENERATE
# ===============================

@payroll_bp.route("/generate", methods=["POST"])
@payroll_bp.route("/payroll/generate", methods=["POST"])
@login_required
def generate():

    role = session.get("role")

    if role not in ["HR", "Admin"]:
        return redirect("/dashboard")

    employee_id = request.form["employee_id"]
    month = int(request.form["month"])
    year = int(request.form["year"])
    generated_by = session.get("user_id")

    try:
        result = generate_payroll(employee_id, month, year, generated_by)
    except Exception:
        result = supabase_rest.create_payroll_run(employee_id, month, year)

    if "error" in result:
        flash(result["error"], "error")
        return redirect("/hrms/payroll/")

    flash("Payroll generated successfully", "success")

    return redirect("/hrms/payroll/")


# ===============================
# APPROVE
# ===============================

@payroll_bp.route("/payroll/<id>/approve", methods=["POST"])
@login_required
def approve_payroll(id):

    if session.get("role") != "HR":
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        cur.execute("SELECT status FROM payroll_runs WHERE id=%s", (id,))
        payroll = cur.fetchone()

        if not payroll or payroll["status"] != PAYROLL_STATUS["DRAFT"]:
            release_db(conn, cur)
            return "Invalid action"

        cur.execute("""
            UPDATE payroll_runs
            SET status=%s,
                approved_at=%s
            WHERE id=%s
        """, (
            PAYROLL_STATUS["APPROVED"],
            datetime.now(),
            id
        ))

        conn.commit()
        release_db(conn, cur)
    except Exception:
        payroll = supabase_rest.get_payroll_by_id(id)
        if not payroll or payroll["status"] != PAYROLL_STATUS["DRAFT"]:
            return "Invalid action"
        supabase_rest.update_payroll_status(id, PAYROLL_STATUS["APPROVED"])

    return redirect("/hrms/payroll/")


# ===============================
# LOCK
# ===============================

@payroll_bp.route("/payroll/<id>/lock", methods=["POST"])
@login_required
def lock_payroll(id):

    if session.get("role") != "Admin":
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        cur.execute("SELECT status FROM payroll_runs WHERE id=%s", (id,))
        payroll = cur.fetchone()

        if not payroll or payroll["status"] != PAYROLL_STATUS["APPROVED"]:
            release_db(conn, cur)
            return "Approve first"

        cur.execute("""
            UPDATE payroll_runs
            SET status=%s,
                locked_at=%s
            WHERE id=%s
        """, (
            PAYROLL_STATUS["LOCKED"],
            datetime.now(),
            id
        ))

        conn.commit()
        release_db(conn, cur)
    except Exception:
        payroll = supabase_rest.get_payroll_by_id(id)
        if not payroll or payroll["status"] != PAYROLL_STATUS["APPROVED"]:
            return "Approve first"
        supabase_rest.update_payroll_status(id, PAYROLL_STATUS["LOCKED"])

    return redirect("/hrms/payroll/")


# ===============================
# DELETE
# ===============================

@payroll_bp.route("/payroll/<id>/delete", methods=["POST"])
@login_required
def delete_payroll(id):

    if session.get("role") != "HR":
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        cur.execute("SELECT status FROM payroll_runs WHERE id=%s", (id,))
        payroll = cur.fetchone()

        if not payroll or payroll["status"] != PAYROLL_STATUS["DRAFT"]:
            release_db(conn, cur)
            return "Only draft payroll can be deleted"

        cur.execute("DELETE FROM payroll_runs WHERE id=%s", (id,))
        conn.commit()

        release_db(conn, cur)
    except Exception:
        payroll = supabase_rest.get_payroll_by_id(id)
        if not payroll or payroll["status"] != PAYROLL_STATUS["DRAFT"]:
            return "Only draft payroll can be deleted"
        if not supabase_rest.delete_payroll_if_draft(id):
            return "Only draft payroll can be deleted"

    return redirect("/hrms/payroll/")


# ===============================
# DOWNLOAD PAYSLIP
# ===============================

@payroll_bp.route("/payroll/<id>/payslip")
@login_required
def download_payslip(id):
    try:
        conn, cur = get_db(True)

        cur.execute("""
            SELECT p.*, e.full_name, e.designation
            FROM payroll_runs p
            JOIN hrms_employees e ON p.employee_id = e.id
            WHERE p.id=%s
        """, (id,))

        payroll = cur.fetchone()
        release_db(conn, cur)
    except Exception:
        payroll = supabase_rest.get_payroll_by_id(id)

    if not payroll:
        return "Payslip not found"

    if session.get("role") == "Employee":
        if payroll["employee_id"] != session.get("employee_id"):
            return "Unauthorized"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)

    elements = []
    styles = getSampleStyleSheet()

    elements.append(Paragraph("<b>Company Payroll Payslip</b>", styles["Title"]))
    elements.append(Spacer(1, 20))

    emp_data = [
        ["Employee Name", payroll["full_name"]],
        ["Employee ID", payroll["employee_id"]],
        ["Designation", payroll.get("designation", "N/A")],
        ["Month", f"{payroll['month']}/{payroll['year']}"],
        ["Financial Year", payroll["financial_year"]],
    ]

    emp_table = Table(emp_data, colWidths=[150, 250])
    emp_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1, colors.grey),
    ]))

    elements.append(emp_table)
    elements.append(Spacer(1, 30))

    earnings_data = [
        ["Earnings", "Amount"],
        ["Gross Salary", payroll["gross_salary"]],
        ["Variable Pay", payroll["variable_pay"]],
        ["Bonus", payroll["bonus"]],
        ["Reimbursements", payroll["reimbursements"]],
    ]

    earnings_table = Table(earnings_data, colWidths=[250, 150])
    earnings_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1, colors.grey),
    ]))

    elements.append(Paragraph("<b>Earnings</b>", styles["Heading2"]))
    elements.append(Spacer(1, 10))
    elements.append(earnings_table)
    elements.append(Spacer(1, 30))

    deductions_data = [
        ["Deductions", "Amount"],
        ["Attendance Deduction", payroll["attendance_deduction"]],
        ["PF", payroll["pf"]],
        ["Tax", payroll["tax"]],
    ]

    deductions_table = Table(deductions_data, colWidths=[250, 150])
    deductions_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1, colors.grey),
    ]))

    elements.append(Paragraph("<b>Deductions</b>", styles["Heading2"]))
    elements.append(Spacer(1, 10))
    elements.append(deductions_table)
    elements.append(Spacer(1, 30))

    elements.append(Paragraph(
        f"<b>Net Pay: ₹ {payroll['net_salary']}</b>",
        styles["Heading1"]
    ))

    doc.build(elements)

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="payslip.pdf",
        mimetype="application/pdf"
    )


# ===============================
# EMPLOYEE PAYROLL
# ===============================

@payroll_bp.route("/my-payroll")
@login_required
def my_payroll():

    if session.get("role") != "Employee":
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        cur.execute("""
            SELECT *
            FROM payroll_runs
            WHERE employee_id = %s
            ORDER BY year DESC, month DESC
        """, (session.get("employee_id"),))

        payrolls = cur.fetchall()

        release_db(conn, cur)
    except Exception:
        payrolls = supabase_rest.list_my_payrolls(session.get("employee_id"))

    return render_template(
        "hrms/employee_payroll.html",
        payrolls=payrolls
    )


# ===============================
# EDIT PAYROLL
# ===============================

@payroll_bp.route("/payroll/<id>/edit", methods=["GET", "POST"])
@login_required
def edit_payroll(id):

    if session.get("role") not in ["HR", "Admin"]:
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        if request.method == "POST":

            new_net_salary = request.form.get("net_salary")

            cur.execute("""
                UPDATE payroll_runs
                SET net_salary=%s
                WHERE id=%s AND status=%s
            """, (
                new_net_salary,
                id,
                PAYROLL_STATUS["DRAFT"]
            ))

            conn.commit()
            release_db(conn, cur)

            return redirect("/hrms/payroll/")

        cur.execute("SELECT * FROM payroll_runs WHERE id=%s", (id,))
        payroll = cur.fetchone()

        release_db(conn, cur)
    except Exception:
        if request.method == "POST":
            new_net_salary = request.form.get("net_salary")
            supabase_rest.update_payroll_net(id, new_net_salary)
            return redirect("/hrms/payroll/")

        payroll = supabase_rest.get_payroll_by_id(id)

    return render_template("hrms/edit_payroll.html", payroll=payroll)