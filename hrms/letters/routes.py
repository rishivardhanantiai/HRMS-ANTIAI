from flask import Blueprint, render_template, request, redirect, flash, session, current_app, jsonify, send_file
from utils.auth import login_required, role_required
from utils.db import get_db, release_db
import os
import time
from datetime import date, datetime
from utils.supabase_rest import upload_file_bytes
import json
import decimal
from playwright.sync_api import sync_playwright

letters_bp = Blueprint("letters_bp", __name__, url_prefix="/hrms/letters")

# ─── Default template HTML for auto-seeding ───────────────────────────────────

EXPERIENCE_LETTER_HTML = """<h2 style="text-align:center; margin-bottom:5px;">EXPERIENCE CERTIFICATE</h2>
<hr style="border:1px solid #333; margin-bottom:25px;">

<p style="text-align:right;"><strong>Date:</strong> [Date_of_issue]</p>

<p><strong>To Whomsoever It May Concern</strong></p>

<p>This is to certify that <strong>[Employee_Name]</strong> (Employee ID: <strong>[Employee_ID]</strong>) was employed with <strong>[Company_Name]</strong> as <strong>[Designation]</strong> in the <strong>[Department]</strong> department from <strong>[Joining_Date]</strong> to <strong>[Last_Working_Date]</strong>.</p>

<p>During their tenure with us, we found them to be sincere, hardworking, and dedicated towards their work. Their conduct and character have been found satisfactory throughout their employment period.</p>

<p>We wish them all the best in their future endeavors.</p>

<br><br>

<p>Yours sincerely,</p>
<br><br>
<p><strong>[HR_Name]</strong><br>
Human Resources Department<br>
<strong>[Company_Name]</strong></p>"""

FNF_LETTER_HTML = """<h2 style="text-align:center; margin-bottom:5px;">FULL &amp; FINAL SETTLEMENT STATEMENT</h2>
<hr style="border:1px solid #333; margin-bottom:25px;">

<p style="text-align:right;"><strong>Date:</strong> [Settlement_Date]</p>

<table style="width:100%; margin-bottom:20px; border-collapse:collapse;">
<tr><td style="padding:5px;"><strong>Employee Name:</strong></td><td style="padding:5px;">[Employee_Name]</td></tr>
<tr><td style="padding:5px;"><strong>Employee ID:</strong></td><td style="padding:5px;">[Employee_ID]</td></tr>
<tr><td style="padding:5px;"><strong>Designation:</strong></td><td style="padding:5px;">[Designation]</td></tr>
<tr><td style="padding:5px;"><strong>Department:</strong></td><td style="padding:5px;">[Department]</td></tr>
<tr><td style="padding:5px;"><strong>Last Working Date:</strong></td><td style="padding:5px;">[Last_Working_Date]</td></tr>
</table>

<h3>Settlement Details</h3>
<table style="width:100%; border-collapse:collapse; border:1px solid #333;">
<thead>
<tr style="background:#f0f0f0;">
<th style="border:1px solid #333; padding:8px; text-align:left;">Component</th>
<th style="border:1px solid #333; padding:8px; text-align:right;">Amount (Rs.)</th>
</tr>
</thead>
<tbody>
<tr><td style="border:1px solid #333; padding:8px;">Pending Salary</td><td style="border:1px solid #333; padding:8px; text-align:right;">[Pending_Salary]</td></tr>
<tr><td style="border:1px solid #333; padding:8px;">Leave Encashment</td><td style="border:1px solid #333; padding:8px; text-align:right;">[Leave_Encashment]</td></tr>
<tr><td style="border:1px solid #333; padding:8px;">Bonus / Incentives</td><td style="border:1px solid #333; padding:8px; text-align:right;">[Bonus]</td></tr>
<tr><td style="border:1px solid #333; padding:8px;">Reimbursements</td><td style="border:1px solid #333; padding:8px; text-align:right;">[Reimbursements]</td></tr>
<tr><td style="border:1px solid #333; padding:8px;">Deductions</td><td style="border:1px solid #333; padding:8px; text-align:right;">(-) [Deductions]</td></tr>
<tr style="background:#f0f0f0; font-weight:bold;">
<td style="border:1px solid #333; padding:8px;">Net Payable Amount</td>
<td style="border:1px solid #333; padding:8px; text-align:right;">Rs. [FNF_Amount]</td>
</tr>
</tbody>
</table>

<br>
<p>The above amount will be processed to your registered bank account within 3 working days of the settlement date.</p>
<p>For any queries regarding the above, please contact the HR Department.</p>

<br><br>
<p><strong>[HR_Name]</strong><br>
Human Resources Department<br>
<strong>[Company_Name]</strong></p>"""

LOR_HTML = """<h2 style="text-align:center; margin-bottom:5px;">LETTER OF RECOMMENDATION</h2>
<hr style="border:1px solid #333; margin-bottom:25px;">

<p style="text-align:right;"><strong>Date:</strong> [Date_of_issue]</p>

<p><strong>To Whom It May Concern</strong></p>

<p>I am pleased to recommend <strong>[Employee_Name]</strong>, who served as <strong>[Designation]</strong> in the <strong>[Department]</strong> department at <strong>[Company_Name]</strong> from <strong>[Joining_Date]</strong> to <strong>[Last_Working_Date]</strong>.</p>

<p>During their time with us, they demonstrated excellent professional skills including <strong>[Key_Skills]</strong>. They made significant contributions to the following projects: <strong>[Projects]</strong>.</p>

<p>They are a self-motivated individual with strong analytical and problem-solving abilities. They consistently delivered high-quality work, met deadlines, and collaborated effectively with both technical and non-technical team members.</p>

<p>I am confident that they will be a valuable asset to any organization and I highly recommend them without reservation.</p>

<br><br>

<p>Sincerely,</p>
<br><br>
<p><strong>[HR_Name]</strong><br>
Human Resources Department<br>
<strong>[Company_Name]</strong></p>"""

DEFAULT_TEMPLATES = {
    "Experience Letter": EXPERIENCE_LETTER_HTML,
    "FNF Letter": FNF_LETTER_HTML,
    "LOR": LOR_HTML,
}


def _get_company(cur):
    """Fetch company settings or return defaults."""
    try:
        cur.execute("SELECT * FROM company_settings LIMIT 1")
        company = cur.fetchone()
        if company:
            return company
    except Exception:
        pass
    return {
        "company_name": "ANTI.AI PRIVATE LIMITED",
        "company_address": "73 ROSE VILLA RAJENDRA NAGAR BHARATPUR RAJASTHAN, Rajasthan, 321001",
        "company_email": "hr@antlai.com",
        "company_phone": "+91-0000000000",
        "company_website": "www.antlai.com",
        "logo_url": None,
    }


def _ensure_templates(cur):
    """Auto-seed default templates if missing."""
    cur.execute("SELECT template_name FROM letter_templates")
    existing = [r["template_name"] for r in cur.fetchall()]
    for name, html in DEFAULT_TEMPLATES.items():
        if name not in existing:
            cur.execute(
                "INSERT INTO letter_templates (template_name, template_content) VALUES (%s, %s)",
                (name, html),
            )


# ─── Generator Page ──────────────────────────────────────────────────────────

@letters_bp.route("/generator", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def generator():
    conn, cur = get_db(True)
    if not conn:
        return redirect("/dashboard")
    try:
        _ensure_templates(cur)

        cur.execute("SELECT * FROM letter_templates ORDER BY id")
        templates = cur.fetchall()

        cur.execute("""
            SELECT id, employee_code, full_name, department, designation, joining_date
            FROM hrms_employees
            WHERE status = 'Active'
            ORDER BY full_name
        """)
        employees = cur.fetchall()

        company = _get_company(cur)

        return render_template(
            "hrms/letters/generator.html",
            templates=templates,
            employees=employees,
            company=company,
        )
    except Exception as e:
        print("Error in generator:", e)
        import traceback; traceback.print_exc()
        return redirect("/dashboard")
    finally:
        release_db(conn, cur)


# ─── Employee API (JSON) ─────────────────────────────────────────────────────

@letters_bp.route("/api/employee/<int:emp_id>")
@login_required
def api_get_employee(emp_id):
    print(f"SERVER LOG: Employee selected (ID: {emp_id})")
    conn, cur = get_db(True)
    if not conn:
        return jsonify({"error": "DB error"}), 500
    try:
        cur.execute("""
            SELECT e.id, e.employee_code, e.full_name, e.department,
                   e.designation, e.joining_date, e.employment_type,
                   m.full_name AS manager_name,
                   r.role_name
            FROM hrms_employees e
            LEFT JOIN hrms_roles r ON e.role_id = r.id
            LEFT JOIN hrms_employees m ON e.manager_id = m.id
            WHERE e.id = %s
        """, (emp_id,))
        emp = cur.fetchone()
        if not emp:
            print(f"SERVER LOG: Employee not found (ID: {emp_id})")
            return jsonify({"error": "Not found"}), 404

        print(f"SERVER LOG: Employee found: {emp['full_name']}")
        result = {}
        for k, v in emp.items():
            if isinstance(v, (date, datetime)):
                result[k] = v.strftime("%Y-%m-%d")
            elif isinstance(v, decimal.Decimal):
                result[k] = float(v)
            else:
                result[k] = v

        # FNF data
        try:
            cur.execute(
                "SELECT * FROM employee_fnf_records WHERE employee_id = %s ORDER BY calculated_at DESC LIMIT 1",
                (emp_id,),
            )
            fnf = cur.fetchone()
            if fnf:
                fnf_dict = {}
                for k, v in fnf.items():
                    if isinstance(v, (date, datetime)):
                        fnf_dict[k] = v.strftime("%Y-%m-%d")
                    elif isinstance(v, decimal.Decimal):
                        fnf_dict[k] = float(v)
                    else:
                        fnf_dict[k] = v
                result["fnf"] = fnf_dict
        except Exception as fnf_err:
            print("FNF fetch note:", fnf_err)
            pass  # table may not exist or have different schema

        # Company info
        company = _get_company(cur)
        result["_company_name"] = "ANTI.AI PRIVATE LIMITED"

        print("SERVER LOG: Data returned to frontend:", result)
        return jsonify(result)
    except Exception as e:
        print("API employee error:", e)
        return jsonify({"error": str(e)}), 500
    finally:
        release_db(conn, cur)


# ─── Template Editor ─────────────────────────────────────────────────────────

@letters_bp.route("/templates", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def template_editor():
    conn, cur = get_db(True)
    if not conn:
        return redirect("/dashboard")
    try:
        _ensure_templates(cur)
        cur.execute("SELECT * FROM letter_templates ORDER BY id")
        templates = cur.fetchall()
        return render_template("hrms/letters/template_editor.html", templates=templates)
    except Exception as e:
        print("Error in templates:", e)
        return redirect("/dashboard")
    finally:
        release_db(conn, cur)


@letters_bp.route("/templates/save", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def save_template():
    template_name = request.form.get("template_name", "").strip()
    template_content = request.form.get("template_content", "").strip()
    user = session.get("user", "System")

    if not template_name or not template_content:
        flash("Template name and content are required.", "error")
        return redirect("/hrms/letters/templates")

    conn, cur = get_db(True)
    try:
        # Version history: save old version before overwriting
        cur.execute("SELECT * FROM letter_templates WHERE template_name = %s", (template_name,))
        old = cur.fetchone()
        if old:
            try:
                cur.execute("""
                    INSERT INTO letter_templates_history (template_name, template_content, updated_by)
                    VALUES (%s, %s, %s)
                """, (old["template_name"], old["template_content"], old.get("updated_by", "System")))
            except Exception:
                pass  # history table might not exist yet

        cur.execute("""
            INSERT INTO letter_templates (template_name, template_content, updated_by)
            VALUES (%s, %s, %s)
            ON CONFLICT (template_name) DO UPDATE
            SET template_content = EXCLUDED.template_content,
                updated_by = EXCLUDED.updated_by,
                updated_at = CURRENT_TIMESTAMP
        """, (template_name, template_content, user))
        flash("Template saved successfully.", "success")
    except Exception as e:
        print("Error saving template:", e)
        flash("Could not save template.", "error")
    finally:
        release_db(conn, cur)

    return redirect("/hrms/letters/templates")


@letters_bp.route("/templates/delete/<int:tid>", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def delete_template(tid):
    conn, cur = get_db(True)
    try:
        cur.execute("DELETE FROM letter_templates WHERE id = %s", (tid,))
        flash("Template deleted.", "success")
    except Exception as e:
        print("Error deleting template:", e)
        flash("Could not delete template.", "error")
    finally:
        release_db(conn, cur)
    return redirect("/hrms/letters/templates")


# ─── Preview (AJAX) ──────────────────────────────────────────────────────────

@letters_bp.route("/preview", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def preview_pdf():
    html_content = request.form.get("html_content", "")
    conn, cur = get_db()
    try:
        company = _get_company(cur)
    except Exception:
        company = _get_company(None)
    finally:
        if conn:
            release_db(conn, cur)

    full_html = render_template(
        "hrms/letters/letterhead_base.html",
        content=html_content,
        company=company,
    )
    return full_html


# ─── PDF Generation ──────────────────────────────────────────────────────────

@letters_bp.route("/generate_pdf", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def generate_pdf():
    html_content = request.form.get("html_content", "")
    document_type = request.form.get("document_type", "Document")
    emp_id = request.form.get("employee_id")
    exit_id = request.form.get("exit_id")

    conn, cur = get_db()
    try:
        company = _get_company(cur)
        cur.execute("SELECT employee_code FROM hrms_employees WHERE id = %s", (emp_id,))
        row = cur.fetchone()
        emp_code = row["employee_code"] if row else f"EMP{emp_id}"
    except Exception:
        company = _get_company(None)
        emp_code = f"EMP{emp_id}"
    finally:
        if conn:
            release_db(conn, cur)

    full_html = render_template(
        "hrms/letters/letterhead_base.html",
        content=html_content,
        company=company,
    )

    os.makedirs(os.path.join(current_app.root_path, "uploads"), exist_ok=True)
    pdf_path = os.path.join(current_app.root_path, "uploads", f"doc_{int(time.time())}.pdf")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(full_html, wait_until="networkidle")
            page.pdf(path=pdf_path, format="A4", print_background=True,
                     margin={"top": "20px", "bottom": "20px", "left": "20px", "right": "20px"})
            browser.close()

        with open(pdf_path, "rb") as f:
            file_bytes = f.read()

        safe_type = document_type.replace(" ", "_")
        file_name = f"{emp_code}_{safe_type}.pdf"
        object_key = f"letters/{int(time.time())}_{file_name}"
        pdf_url = upload_file_bytes(file_bytes, object_key)

        if pdf_url:
            print("LOG: Storage upload success to", pdf_url)
            conn2, cur2 = get_db(True)
            try:
                # Lookup uploaded_by employee_id
                uploader_employee_id = None
                user_id = session.get("user_id")
                if user_id:
                    try:
                        cur2.execute("SELECT employee_id FROM users WHERE id = %s", (user_id,))
                        user_rec = cur2.fetchone()
                        if user_rec and user_rec.get("employee_id"):
                            uploader_employee_id = user_rec["employee_id"]
                    except Exception as e:
                        print("Error looking up uploader employee_id:", e)
                        
                file_size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0
                
                cur2.execute("""
                    INSERT INTO generated_letters (employee_id, document_type, pdf_url, generated_by, status, pdf_path, file_size)
                    VALUES (%s, %s, %s, %s, 'Generated', %s, %s)
                """, (emp_id, document_type, pdf_url, session.get("user", "System"), pdf_path, file_size))
                print("LOG: generated_letters insert success")

                # Also insert into employee_documents so it shows up in Employee Profile
                try:
                    cur2.execute("""
                        INSERT INTO employee_documents (employee_id, document_name, document_type, description, file_url, file_size, uploaded_by, file_name, file_path, s3_url, mime_type)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        emp_id, 
                        f"{document_type}", 
                        "Other", 
                        f"System generated letter via HRMS", 
                        pdf_url, 
                        file_size, 
                        uploader_employee_id, 
                        file_name, 
                        object_key, 
                        pdf_url, 
                        "application/pdf"
                    ))
                    print("LOG: employee_documents insert success")
                except Exception as doc_err:
                    print(f"Error inserting to employee_documents: {str(doc_err)}")
                    raise doc_err

                if exit_id:
                    try:
                        cur2.execute("""
                            INSERT INTO employee_exit_documents (employee_id, exit_id, document_type, pdf_url, generated_by)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (emp_id, exit_id, document_type, pdf_url, session.get("user", "System")))
                    except Exception:
                        pass
            finally:
                if conn2:
                    release_db(conn2, cur2)

        return send_file(pdf_path, as_attachment=True, download_name=file_name)

    except Exception as e:
        print("PDF Generation Error, using browser print fallback:", e)
        import traceback; traceback.print_exc()
        session["fallback_html"] = full_html
        session["fallback_doc_type"] = document_type
        session["fallback_emp_id"] = emp_id
        session["fallback_exit_id"] = exit_id
        return redirect(url_for("letters.print_fallback"))

@letters_bp.route("/print-fallback")
@login_required
def print_fallback():
    html = session.pop("fallback_html", "<h3>No document content found</h3>")
    doc_type = session.pop("fallback_doc_type", "Document")
    emp_id = session.pop("fallback_emp_id", None)
    exit_id = session.pop("fallback_exit_id", None)
    
    if emp_id:
        try:
            conn, cur = get_db(True)
            cur.execute("""
                INSERT INTO generated_letters (employee_id, document_type, pdf_url, generated_by)
                VALUES (%s, %s, %s, %s)
            """, (emp_id, doc_type, "Browser Printed (Check Printer)", session.get("user", "System")))
            if exit_id:
                try:
                    cur.execute("""
                        INSERT INTO employee_exit_documents (employee_id, exit_id, document_type, pdf_url, generated_by)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (emp_id, exit_id, doc_type, "Browser Printed (Check Printer)", session.get("user", "System")))
                except Exception:
                    pass
            conn.commit()
            release_db(conn, cur)
        except Exception as e:
            print("Error saving printed letter in DB:", e)
            
    return render_template("hrms/letters/print_fallback.html", html=html, doc_type=doc_type)


# ─── Document History ─────────────────────────────────────────────────────────

@letters_bp.route("/history")
@login_required
@role_required(["HR", "Admin"])
def letters_history():
    conn, cur = get_db(True)
    if not conn:
        return redirect("/dashboard")
    try:
        emp_filter = request.args.get("emp", "")
        doc_filter = request.args.get("doc", "")
        date_filter = request.args.get("date", "")

        query = """
            SELECT gl.*, e.full_name, e.employee_code
            FROM generated_letters gl
            JOIN hrms_employees e ON gl.employee_id = e.id
            WHERE 1=1
        """
        params = []
        if emp_filter:
            query += " AND e.id = %s"
            params.append(emp_filter)
        if doc_filter:
            query += " AND gl.document_type = %s"
            params.append(doc_filter)
        if date_filter:
            query += " AND DATE(gl.generated_at) = %s"
            params.append(date_filter)

        query += " ORDER BY gl.generated_at DESC"
        cur.execute(query, tuple(params))
        letters = cur.fetchall()

        cur.execute("SELECT id, full_name, employee_code FROM hrms_employees ORDER BY full_name")
        employees = cur.fetchall()

        cur.execute("SELECT DISTINCT document_type FROM generated_letters ORDER BY document_type")
        doc_types = [r["document_type"] for r in cur.fetchall()]

        # Calculate statistics
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN document_type = 'Experience Letter' THEN 1 ELSE 0 END) as exp_count,
                SUM(CASE WHEN document_type = 'FNF Letter' THEN 1 ELSE 0 END) as fnf_count,
                SUM(CASE WHEN document_type = 'LOR' THEN 1 ELSE 0 END) as lor_count
            FROM generated_letters
        """)
        stats = cur.fetchone()

        return render_template("hrms/letters/history.html", letters=letters, employees=employees, doc_types=doc_types, stats=stats)
    except Exception as e:
        print("History error:", e)
        return render_template("hrms/letters/history.html", letters=[], employees=[], doc_types=[], stats={})
    finally:
        release_db(conn, cur)


@letters_bp.route("/history/delete/<int:lid>", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def delete_letter(lid):
    conn, cur = get_db(True)
    try:
        cur.execute("DELETE FROM generated_letters WHERE id = %s", (lid,))
        flash("Record deleted.", "success")
    except Exception as e:
        flash("Could not delete record.", "error")
    finally:
        release_db(conn, cur)
    return redirect("/hrms/letters/history")
