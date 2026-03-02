from flask import Blueprint, render_template, request, session, redirect
from utils.auth import login_required
from services.payroll_engine import generate_payroll
from utils.db import get_db, release_db
from constants import PAYROLL_STATUS
from datetime import datetime
from reportlab.pdfgen import canvas
from flask import send_file
import io
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import units
from flask import send_file
import io



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

    conn, cur = get_db(True)

    # 🔥 FIXED QUERY (No id conflict now)
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
    print("DEBUG PAYROLL RUNS RAW:", payroll_runs)
    cur.execute("SELECT id, full_name FROM hrms_employees ORDER BY full_name")
    employees = cur.fetchall()

    release_db(conn, cur)

    return render_template(
        "hrms/payroll_dashboard.html",
        payroll_runs=payroll_runs,
        employees=employees
    )

# ===============================
# GENERATE
# ===============================

@payroll_bp.route("/generate", methods=["POST"])
@login_required
def generate():

    role = session.get("role")

    if role not in ["HR", "Admin"]:
        return redirect("/dashboard")

    employee_id = int(request.form["employee_id"])
    month = int(request.form["month"])
    year = int(request.form["year"])
    generated_by = session.get("user_id")

    result = generate_payroll(employee_id, month, year, generated_by)

    if "error" in result:
        return result["error"]

    return redirect("/hrms/payroll/")

# ===============================
# APPROVE
# ===============================

@payroll_bp.route("/payroll/<int:id>/approve", methods=["POST"])
@login_required
def approve_payroll(id):

    if session.get("role") != "HR":
        return redirect("/dashboard")

    conn, cur = get_db(True)

    cur.execute("SELECT status FROM payroll_runs WHERE id=%s", (id,))
    payroll = cur.fetchone()

    if not payroll or payroll["status"] != PAYROLL_STATUS["DRAFT"]:
        release_db(conn, cur)
        return "Invalid action"
    print("detect change")
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

    return redirect("/hrms/payroll/")

# ===============================
# LOCK
# ===============================

@payroll_bp.route("/payroll/<int:id>/lock", methods=["POST"])
@login_required
def lock_payroll(id):

    if session.get("role") != "Admin":
        return redirect("/dashboard")

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

    return redirect("/hrms/payroll/")

# ===============================
# DELETE
# ===============================

@payroll_bp.route("/payroll/<int:id>/delete", methods=["POST"])
@login_required
def delete_payroll(id):

    if session.get("role") != "HR":
        return redirect("/dashboard")

    conn, cur = get_db(True)

    cur.execute("SELECT status FROM payroll_runs WHERE id=%s", (id,))
    payroll = cur.fetchone()

    if not payroll or payroll["status"] != PAYROLL_STATUS["DRAFT"]:
        release_db(conn, cur)
        return "Only draft payroll can be deleted"

    cur.execute("DELETE FROM payroll_runs WHERE id=%s", (id,))
    conn.commit()

    release_db(conn, cur)

    return redirect("/hrms/payroll/")



        


@payroll_bp.route("/payroll/<int:id>/payslip")
@login_required
def download_payslip(id):

    conn, cur = get_db(True)

    cur.execute("""
        SELECT p.*, e.full_name, e.designation
        FROM payroll_runs p
        JOIN hrms_employees e ON p.employee_id = e.id
        WHERE p.id=%s
    """, (id,))

    payroll = cur.fetchone()

    if not payroll:
        return "Payslip not found"

    # 🔐 Security
    if session.get("role") == "Employee":
        if payroll["employee_id"] != session.get("employee_id"):
            return "Unauthorized"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)

    elements = []
    styles = getSampleStyleSheet()

    # Title
    elements.append(Paragraph("<b>Company Payroll Payslip</b>", styles["Title"]))
    elements.append(Spacer(1, 20))

    # Employee Info Table
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
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
    ]))

    elements.append(emp_table)
    elements.append(Spacer(1, 30))

    # Earnings Table
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
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))

    elements.append(Paragraph("<b>Earnings</b>", styles["Heading2"]))
    elements.append(Spacer(1, 10))
    elements.append(earnings_table)
    elements.append(Spacer(1, 30))

    # Deductions Table
    deductions_data = [
        ["Deductions", "Amount"],
        ["Attendance Deduction", payroll["attendance_deduction"]],
        ["PF", payroll["pf"]],
        ["Tax", payroll["tax"]],
    ]

    deductions_table = Table(deductions_data, colWidths=[250, 150])
    deductions_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))

    elements.append(Paragraph("<b>Deductions</b>", styles["Heading2"]))
    elements.append(Spacer(1, 10))
    elements.append(deductions_table)
    elements.append(Spacer(1, 30))

    # Net Pay Highlight
    elements.append(Paragraph(
        f"<b>Net Pay: ₹ {payroll['net_salary']}</b>",
        styles["Heading1"]
    ))

    doc.build(elements)

    buffer.seek(0)
    release_db(conn, cur)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="payslip.pdf",
        mimetype="application/pdf"
    )
    
@payroll_bp.route("/my-payroll")
@login_required
def my_payroll():

    if session.get("role") != "Employee":
        return redirect("/dashboard")

    conn, cur = get_db(True)

    cur.execute("""
        SELECT *
        FROM payroll_runs
        WHERE employee_id = %s
        ORDER BY year DESC, month DESC
    """, (session.get("employee_id"),))

    payrolls = cur.fetchall()

    release_db(conn, cur)

    return render_template(
        "hrms/employee_payroll.html",
        payrolls=payrolls
    )