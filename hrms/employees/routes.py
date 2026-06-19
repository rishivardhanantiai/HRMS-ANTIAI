print("HRMS EMPLOYEES ROUTES LOADED")

from flask import Blueprint, request, render_template, jsonify, redirect, session, flash
from datetime import date
from utils.db import get_db, release_db
from utils import supabase_rest
from utils.auth import login_required
from werkzeug.security import generate_password_hash


employees_bp = Blueprint(
    "employees",
    __name__,
    url_prefix="/hrms/employees"
)


# =========================
# ROLE CHECK HELPER
# =========================
def hr_admin_required():
    return session.get("role") in ["HR", "Admin"]


# =========================
# EMPLOYEES UI
# =========================
@employees_bp.route("/ui")
@login_required
def employees_ui():

    if not hr_admin_required():
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        cur.execute("""
            SELECT 
                e.id,
                e.employee_code,
                e.full_name,
                e.email,
                e.department,
                e.designation,
                e.status,
                e.joining_date,
                e.employment_type,
                e.profile_photo_url,
                m.full_name as manager_name,
                r.role_name
            FROM hrms_employees e
            LEFT JOIN hrms_roles r ON e.role_id = r.id
            LEFT JOIN hrms_employees m ON e.manager_id = m.id
            WHERE e.status != 'Deleted'
            ORDER BY e.id DESC
        """)

        employees = cur.fetchall()

        # Calculate metrics
        metrics = {
            "total": len(employees),
            "active": sum(1 for emp in employees if emp["status"] == "Active"),
            "inactive": sum(1 for emp in employees if emp["status"] == "Inactive"),
            "on_leave": sum(1 for emp in employees if emp["status"] == "On Leave"),
            "new_joinees": sum(1 for emp in employees if emp["joining_date"] and emp["joining_date"].month == date.today().month and emp["joining_date"].year == date.today().year),
            "pending_docs": 0, # Mocked for now, can be computed by joining employee_documents
            "pending_verification": 0
        }

        release_db(conn, cur)
    except Exception as e:
        print("Error fetching employee ui data:", e)
        employees = supabase_rest.list_employees()
        metrics = {"total": 0, "active": 0, "inactive": 0, "on_leave": 0, "new_joinees": 0, "pending_docs": 0, "pending_verification": 0}

    return render_template("hrms/employees.html", employees=employees, metrics=metrics)


# =========================
# EMPLOYEES LIST API
# =========================
@employees_bp.route("/list")
@login_required
def employees_list():

    if not hr_admin_required():
        return {"error": "Unauthorized"}, 403

    try:
        conn, cur = get_db(True)

        cur.execute("""
            SELECT
                e.id,
                e.employee_code,
                e.full_name,
                e.email,
                e.department,
                e.status,
                e.joining_date,
                e.employment_type,
                e.designation,
                r.role_name,
                m.full_name as manager_name
            FROM hrms_employees e
            LEFT JOIN hrms_roles r ON e.role_id = r.id
            LEFT JOIN hrms_employees m ON e.manager_id = m.id
            WHERE e.status != 'Deleted'
            ORDER BY e.id DESC
        """)

        employees = cur.fetchall()
        
        for emp in employees:
            if emp.get("joining_date"):
                emp["joining_date"] = str(emp["joining_date"])
                
        release_db(conn, cur)
    except Exception:
        employees = supabase_rest.list_employees()

    return jsonify({"employees": employees})


# =========================
# ADD EMPLOYEE UI
# =========================
@employees_bp.route("/add/ui")
@login_required
def add_employee_ui():

    if not hr_admin_required():
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        cur.execute("SELECT id, role_name FROM hrms_roles ORDER BY role_name")
        roles = cur.fetchall()

        cur.execute("SELECT id, name FROM salary_structures ORDER BY name")
        salary_structures = cur.fetchall()

        # Fetch employees for manager dropdown
        cur.execute("SELECT id, full_name, employee_code FROM hrms_employees WHERE status != 'Deleted' ORDER BY full_name")
        managers = cur.fetchall()

        # Generate next Employee Code (e.g., EMP-0001)
        cur.execute("SELECT employee_code FROM hrms_employees WHERE employee_code LIKE 'EMP-%' ORDER BY id DESC LIMIT 1")
        last_emp = cur.fetchone()
        next_code = "EMP-0001"
        if last_emp and last_emp["employee_code"]:
            try:
                last_num = int(last_emp["employee_code"].split("-")[1])
                next_code = f"EMP-{(last_num + 1):04d}"
            except:
                pass

        release_db(conn, cur)
    except Exception as e:
        print("Error fetching add ui data:", e)
        roles = supabase_rest.list_roles()
        salary_structures = []
        managers = []
        next_code = "EMP-0001"

    return render_template(
        "hrms/add_employee.html",
        roles=roles,
        salary_structures=salary_structures,
        managers=managers,
        next_employee_code=next_code
    )


# =========================
# ADD EMPLOYEE
# =========================
# =========================
# ADD EMPLOYEE
# =========================
@employees_bp.route("/documents/api/verify/<int:doc_id>", methods=["POST"])
@login_required
def api_verify_document(doc_id):
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403

    try:
        data = request.json
        status = data.get("status")
        remarks = data.get("remarks")
        verified_by = session.get("user_id")

        if status not in ["Verified", "Rejected"]:
            return jsonify({"error": "Invalid status"}), 400

        conn, cur = get_db()
        cur.execute("""
            UPDATE employee_documents
            SET verification_status = %s, verification_remarks = %s, verified_by = %s, verified_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (status, remarks, verified_by, doc_id))
        conn.commit()
        release_db(conn, cur)

        return jsonify({"message": "Document verification updated successfully"}), 200
    except Exception as e:
        print(f"Error verifying document: {e}")
        return jsonify({"error": str(e)}), 500

@employees_bp.route("/<employee_id>/profile", methods=["GET"])
@login_required
def employee_profile(employee_id):
    if not hr_admin_required():
        return redirect("/dashboard")

    conn, cur = get_db(True)
    try:
        cur.execute("SELECT * FROM hrms_employees WHERE id = %s", (employee_id,))
        emp = cur.fetchone()
        
        cur.execute("""
            SELECT p.*, COALESCE(e2.full_name, 'HR Admin') as evaluator_name 
            FROM performance_evaluations p
            LEFT JOIN hrms_users u ON p.evaluator_id = u.id
            LEFT JOIN hrms_employees e2 ON u.employee_id = e2.id
            WHERE p.employee_id = %s
            ORDER BY p.evaluation_year DESC, p.evaluation_month DESC, p.id DESC
        """, (employee_id,))
        evals = cur.fetchall()
        
        cur.execute("SELECT * FROM employee_documents WHERE employee_id = %s", (employee_id,))
        documents = cur.fetchall()
        
        cur.execute("""
            SELECT la.*, lt.name as leave_type 
            FROM leave_applications la 
            LEFT JOIN leave_types lt ON la.leave_type_id = lt.id 
            WHERE la.employee_id = %s 
            ORDER BY la.created_at DESC
        """, (employee_id,))
        leaves = cur.fetchall()
        
        cur.execute("SELECT * FROM employee_salary WHERE employee_id = %s", (employee_id,))
        salary = cur.fetchone()
        
    finally:
        release_db(conn, cur)

    if not emp:
        flash("Employee not found", "error")
        return redirect("/hrms/employees/ui")

    return render_template("hrms/employee_profile.html", emp=emp, evals=evals, documents=documents, leaves=leaves, salary=salary)

@employees_bp.route("/add", methods=["POST"])
@login_required
def add_employee():

    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403

    data = request.form
    files = request.files

    required_fields = [
        "employee_code",
        "full_name",
        "email",
        "role_id",
        "password" # <--- Added password to required fields
    ]

    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    try:
        conn, cur = get_db(True)

        # Check duplicate emails
        cur.execute("SELECT id FROM hrms_employees WHERE email=%s", (data["email"],))
        if cur.fetchone():
            release_db(conn, cur)
            return jsonify({"error": "Employee email already exists"}), 400

        cur.execute("SELECT id FROM hrms_users WHERE email=%s", (data["email"],))
        if cur.fetchone():
            release_db(conn, cur)
            return jsonify({"error": "Login email already exists"}), 400

        plain_password = data.get("password")
        hashed_password = generate_password_hash(plain_password)
        joining_date = data.get("joining_date") or date.today()

        # Step 1: Create Employee Record
        cur.execute("""
            INSERT INTO hrms_employees
            (employee_code, full_name, email, phone, department, designation, role_id, joining_date, status, manager_id, gender, date_of_birth, office_location, employment_type)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'Active',%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            data["employee_code"],
            data["full_name"],
            data["email"],
            data.get("phone"),
            data.get("department"),
            data.get("designation", "Employee"),
            data["role_id"],
            joining_date,
            data.get("manager_id") or None,
            data.get("gender"),
            data.get("date_of_birth") or None,
            data.get("office_location"),
            data.get("employment_type", "Full Time")
        ))
        employee_id = cur.fetchone()["id"]

        # Step 2: Create Login Account
        cur.execute("""
            INSERT INTO hrms_users (email, password, role_id, employee_id)
            VALUES (%s,%s,%s,%s)
        """, (
            data["email"],
            hashed_password,
            data["role_id"],
            employee_id
        ))

        # Handle Profile Photo Upload
        profile_photo = files.get("profile_photo")
        if profile_photo and profile_photo.filename:
            res = upload_document_to_supabase(profile_photo, employee_id)
            if res:
                cur.execute("UPDATE hrms_employees SET profile_photo_url = %s WHERE id = %s", (res["public_url"], employee_id))

        # Step 3: Compensation
        annual_ctc = data.get("annual_ctc", 0)
        try:
            annual_ctc = float(annual_ctc)
        except:
            annual_ctc = 0.0

        if annual_ctc > 0:
            monthly_gross = annual_ctc / 12.0
            cur.execute("""
                INSERT INTO employee_salary (employee_id, annual_ctc, monthly_salary, effective_from)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (employee_id, annual_ctc, monthly_gross, joining_date))
            salary_id = cur.fetchone()["id"]
            
            # Save basic breakdown to employee_salary_components
            basic = annual_ctc * 0.50
            hra = annual_ctc * 0.25
            lta = annual_ctc * 0.10
            special = annual_ctc - (basic + hra + lta)

            components = [
                ("Basic", basic, basic/12),
                ("House Rent Allowance", hra, hra/12),
                ("Leave & Travel Allowance", lta, lta/12),
                ("Special Allowance", special, special/12)
            ]
            for c_name, y_amt, m_amt in components:
                cur.execute("""
                    INSERT INTO employee_salary_components (employee_id, component_name, yearly_amount, monthly_amount)
                    VALUES (%s, %s, %s, %s)
                """, (employee_id, c_name, y_amt, m_amt))

        # Step 4: Compliance
        if any([data.get("pan_number"), data.get("aadhaar_number"), data.get("uan_number")]):
            cur.execute("""
                INSERT INTO employee_compliance (employee_id, pan_number, aadhaar_number, uan_number, pf_number, esic_number)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (employee_id, data.get("pan_number"), data.get("aadhaar_number"), data.get("uan_number"), data.get("pf_number"), data.get("esic_number")))

        # Step 5: Bank Details
        if any([data.get("bank_name"), data.get("account_number")]):
            cur.execute("""
                INSERT INTO employee_bank_details (employee_id, bank_name, account_number, ifsc_code, branch_name, address, emergency_contact, emergency_contact_number)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (employee_id, data.get("bank_name"), data.get("account_number"), data.get("ifsc_code"), data.get("branch_name"), data.get("address"), data.get("emergency_contact"), data.get("emergency_contact_number")))

        # Document Uploads
        doc_fields = [
            ("doc_aadhaar", "Aadhaar Card"),
            ("doc_pan", "PAN Card"),
            ("doc_resume", "Resume"),
            ("doc_offer", "Offer/Experience Letter")
        ]
        from datetime import datetime
        for file_key, doc_title in doc_fields:
            doc_file = files.get(file_key)
            if doc_file and doc_file.filename:
                res = upload_document_to_supabase(doc_file, employee_id)
                if res:
                    cur.execute("""
                        INSERT INTO employee_documents (employee_id, document_type, document_title, file_url, created_at, verification_status, file_name, file_path, bucket_name, public_url, mime_type, uploaded_by)
                        VALUES (%s, %s, %s, %s, %s, 'Verified', %s, %s, %s, %s, %s, %s)
                    """, (employee_id, "Onboarding", doc_title, res["public_url"], datetime.now(), res["file_name"], res["file_path"], res["bucket_name"], res["public_url"], res["mime_type"], session.get("employee_id") or employee_id))

        # Audit Log
        cur.execute("""
            INSERT INTO employee_audit_logs (employee_id, action, performed_by)
            VALUES (%s, 'Employee Created via Onboarding Wizard', %s)
        """, (employee_id, session.get("employee_id") or None))

        # Status History
        cur.execute("""
            INSERT INTO employee_status_history (employee_id, status, changed_by, remarks)
            VALUES (%s, 'Active', %s, 'Initial Onboarding')
        """, (employee_id, session.get("employee_id") or None))

        conn.commit()
        release_db(conn, cur)
        
        # Email automation simulation
        print(f"--- EMAIL AUTOMATION ---")
        print(f"To: {data['email']}")
        print(f"Subject: Welcome to the Company!")
        print(f"Your Login: {data['email']}")
        print(f"Your Password: {plain_password}")
        print(f"------------------------")

        return jsonify({"success": True, "redirect": "/hrms/employees/ui"})

    except Exception as e:
        print("Add employee error:", e)
        return jsonify({"error": str(e)}), 500

# =========================
# EDIT EMPLOYEE UI (GET)
# =========================
@employees_bp.route("/<employee_id>/edit", methods=["GET"])
@login_required
def edit_employee_ui(employee_id):

    if not hr_admin_required():
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        cur.execute("""
            SELECT id, full_name, email, phone, department, role_id
            FROM hrms_employees
            WHERE id=%s AND status != 'Deleted'
        """, (employee_id,))
        employee = cur.fetchone()

        if not employee:
            release_db(conn, cur)
            return "Employee not found", 404

        cur.execute("SELECT id, role_name FROM hrms_roles ORDER BY role_name")
        roles = cur.fetchall()

        release_db(conn, cur)
    except Exception:
        employee = supabase_rest.get_employee_by_id(employee_id)
        if not employee:
            return "Employee not found", 404
        roles = supabase_rest.list_roles()

    return render_template(
        "hrms/edit_employee.html",
        employee=employee,
        roles=roles
    )


# =========================
# UPDATE EMPLOYEE (POST)
# =========================
@employees_bp.route("/<employee_id>/edit", methods=["POST"])
@login_required
def edit_employee(employee_id):

    if not hr_admin_required():
        return redirect("/dashboard")

    data = request.form
    try:
        conn, cur = get_db(True)

        # 1. Update the Employee Profile
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

        # 2. Sync the Role and Email to the Login Table
        cur.execute("""
            UPDATE hrms_users 
            SET email=%s,
                role_id=%s
            WHERE employee_id=%s
        """, (
            data["email"],
            data["role_id"],
            employee_id
        ))

        # 3. Admin Password Reset (If provided)
        new_password = data.get("password", "").strip()
        if new_password and session.get("role") == "Admin":
            hashed_new = generate_password_hash(new_password)
            cur.execute("""
                UPDATE hrms_users 
                SET password = %s 
                WHERE employee_id = %s
            """, (hashed_new, employee_id))

        conn.commit()
        release_db(conn, cur)
    except Exception:
        supabase_rest.update_employee(
            employee_id=employee_id,
            full_name=data["full_name"],
            email=data["email"],
            phone=data.get("phone"),
            department=data.get("department"),
            role_id=data["role_id"],
        )

    return redirect("/hrms/employees/ui")

# =========================
# CHANGE STATUS
# =========================
@employees_bp.route("/<employee_id>/status", methods=["POST"])
@login_required
def change_employee_status(employee_id):

    if not hr_admin_required():
        return redirect("/dashboard")

    new_status = request.form.get("status")

    if new_status not in ["Active", "Inactive"]:
        return {"error": "Invalid status"}, 400

    try:
        conn, cur = get_db(True)

        cur.execute(
            "UPDATE hrms_employees SET status=%s WHERE id=%s",
            (new_status, employee_id)
        )

        conn.commit()
        release_db(conn, cur)
    except Exception:
        supabase_rest.update_employee_status(employee_id, new_status)

    return {"message": "Status updated"}, 200


# =========================
# SOFT DELETE
# =========================
@employees_bp.route("/<employee_id>/delete", methods=["POST"])
@login_required
def delete_employee(employee_id):

    if not hr_admin_required():
        return redirect("/dashboard")

    try:
        conn, cur = get_db(True)

        cur.execute("""
            UPDATE hrms_employees
            SET status='Deleted'
            WHERE id=%s
        """, (employee_id,))

        conn.commit()
        release_db(conn, cur)
    except Exception:
        supabase_rest.soft_delete_employee(employee_id)

    return {"message": "Employee deleted"}, 200

# =========================
# DOCUMENT MANAGEMENT
# =========================
import os
import httpx
from datetime import datetime
from werkzeug.utils import secure_filename

def upload_document_to_supabase(file_storage, employee_id):
    if not file_storage or not file_storage.filename:
        return None

    from flask import current_app
    safe_name = secure_filename(file_storage.filename)
    timestamp = int(datetime.now().timestamp())
    object_key = f"documents/emp_{employee_id}_{timestamp}_{safe_name}"
    content_type = file_storage.mimetype or "application/octet-stream"

    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_key = os.getenv("SUPABASE_KEY")
    
    # Try Supabase first if configured
    if supabase_url and supabase_key:
        try:
            file_storage.stream.seek(0)
            file_bytes = file_storage.read()
            file_storage.stream.seek(0)

            bucket = os.getenv("SUPABASE_RESUME_BUCKET", "resumes")
            upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{object_key}"
            headers = {
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": content_type,
                "x-upsert": "false"
            }

            response = httpx.post(upload_url, content=file_bytes, headers=headers, timeout=30.0)
            if response.status_code in (200, 201):
                public_url = f"{supabase_url}/storage/v1/object/public/{bucket}/{object_key}"
                return {
                    "file_name": safe_name,
                    "file_path": object_key,
                    "bucket_name": bucket,
                    "public_url": public_url,
                    "mime_type": content_type
                }
        except Exception as e:
            print("Supabase upload failed, falling back to local:", e)

    # Local Fallback
    local_filename = f"emp_{employee_id}_{timestamp}_{safe_name}"
    docs_dir = os.path.join(current_app.root_path, "uploads", "docs")
    os.makedirs(docs_dir, exist_ok=True)
    
    file_storage.stream.seek(0)
    file_storage.save(os.path.join(docs_dir, local_filename))
    
    public_url = f"/hrms/employees/documents/download_local/{local_filename}"
    
    return {
        "file_name": safe_name,
        "file_path": local_filename,
        "bucket_name": "local",
        "public_url": public_url,
        "mime_type": content_type
    }


@employees_bp.route("/my-documents", methods=["GET"])
@login_required
def my_documents():
    employee_id = session.get("employee_id")
    if not employee_id:
        return redirect("/dashboard")

    conn, cur = get_db(True)
    try:
        cur.execute("SELECT * FROM employee_documents WHERE employee_id=%s ORDER BY created_at DESC", (employee_id,))
        documents = cur.fetchall()
    finally:
        release_db(conn, cur)

    return render_template("hrms/my_documents.html", documents=documents, employee_name=session.get("employee_name"))


@employees_bp.route("/documents/upload", methods=["POST"])
@login_required
def upload_document():
    employee_id = session.get("employee_id")
    if not employee_id:
        return redirect("/dashboard")

    doc_type = request.form.get("document_type")
    doc_title = request.form.get("document_title")
    description = request.form.get("description", "")
    file_attachment = request.files.get("file_attachment")

    if not doc_type or not file_attachment or not file_attachment.filename:
        from flask import flash
        flash("Type and attachment are mandatory.", "error")
        return redirect("/hrms/employees/my-documents")

    # Size limit (5MB)
    file_attachment.seek(0, os.SEEK_END)
    size_bytes = file_attachment.tell()
    file_attachment.seek(0)
    if size_bytes > 5 * 1024 * 1024:
        from flask import flash
        flash("File exceeds 5MB limit.", "error")
        return redirect("/hrms/employees/my-documents")
    try:
        res = upload_document_to_supabase(file_attachment, employee_id)
        if not res:
            raise Exception("Upload to storage failed")

        conn, cur = get_db(True)
        cur.execute("""
            INSERT INTO employee_documents (employee_id, document_type, document_title, description, file_url, file_size, uploaded_by, file_name, file_path, bucket_name, public_url, mime_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (employee_id, doc_type, doc_title, description, res["public_url"], size_bytes, employee_id, res["file_name"], res["file_path"], res["bucket_name"], res["public_url"], res["mime_type"]))
        conn.commit()
        release_db(conn, cur)
        from flask import flash
        flash("Document uploaded successfully.", "success")
    except Exception as e:
        from flask import flash
        flash(f"Upload failed: {e}", "error")

    return redirect("/hrms/employees/my-documents")

@employees_bp.route("/documents/download_local/<filename>")
@login_required
def download_local_document(filename):
    from flask import current_app, send_from_directory
    docs_dir = os.path.join(current_app.root_path, "uploads", "docs")
    return send_from_directory(docs_dir, filename, as_attachment=True)

@employees_bp.route("/documents/<doc_id>/view", methods=["GET"])
@login_required
def view_document(doc_id):
    conn, cur = get_db(True)
    try:
        cur.execute("SELECT public_url, file_url, bucket_name, file_path FROM employee_documents WHERE id=%s", (doc_id,))
        doc = cur.fetchone()
    finally:
        release_db(conn, cur)

    if not doc:
        from flask import flash
        flash("Document not found.", "error")
        return redirect(request.referrer or "/hrms/employees/ui")

    url = doc.get("public_url") or doc.get("file_url")
    if not url:
        from flask import flash
        flash("Document URL missing.", "error")
        return redirect(request.referrer or "/hrms/employees/ui")

    bucket_name = doc.get("bucket_name")
    file_path = doc.get("file_path")

    # If bucket_name or file_path is missing, try to parse it from the URL
    if not bucket_name or not file_path:
        parts = url.split("/storage/v1/object/public/")
        if len(parts) == 2:
            path_parts = parts[1].split("/", 1)
            if len(path_parts) == 2:
                bucket_name = path_parts[0]
                file_path = path_parts[1]

    if bucket_name and file_path:
        import os
        import httpx
        supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        supabase_key = os.getenv("SUPABASE_KEY")
        if supabase_url and supabase_key:
            headers = {
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json"
            }
            sign_url = f"{supabase_url}/storage/v1/object/sign/{bucket_name}/{file_path}"
            try:
                r = httpx.post(sign_url, headers=headers, json={"expiresIn": 3600}, timeout=10.0)
                if r.status_code == 200:
                    signed_path = r.json().get("signedURL")
                    if signed_path:
                        # The signed path starts with /object/sign/... so we need to append it to the supabase url
                        return redirect(f"{supabase_url}/storage/v1{signed_path}")
                else:
                    return f"Failed to sign. status={r.status_code} text={r.text} url={sign_url}", 500
            except Exception as e:
                return f"Exception in sign: {e}", 500

    # Fallback to the public URL if signed URL generation fails
    return redirect(url)


@employees_bp.route("/documents/<doc_id>/delete", methods=["POST"])
@login_required
def delete_document(doc_id):
    employee_id = session.get("employee_id")
    if not employee_id:
        return {"error": "Unauthorized"}, 403

    conn, cur = get_db(True)
    try:
        cur.execute("DELETE FROM employee_documents WHERE id=%s AND employee_id=%s", (doc_id, employee_id))
        conn.commit()
    finally:
        release_db(conn, cur)

    return {"message": "Deleted"}, 200


@employees_bp.route("/<employee_id>/documents", methods=["GET"])
@login_required
def employee_documents_hr(employee_id):
    if not hr_admin_required():
        return redirect("/dashboard")

    conn, cur = get_db(True)
    try:
        cur.execute("SELECT full_name FROM hrms_employees WHERE id=%s", (employee_id,))
        emp = cur.fetchone()
        
        cur.execute("""
            SELECT d.*, u.full_name as uploaded_by_name, v.full_name as verified_by_name 
            FROM employee_documents d
            LEFT JOIN hrms_employees u ON d.uploaded_by = u.id
            LEFT JOIN hrms_employees v ON d.verified_by = v.id
            WHERE d.employee_id=%s ORDER BY d.created_at DESC
        """, (employee_id,))
        documents = cur.fetchall()
    finally:
        release_db(conn, cur)

    return render_template("hrms/manage_documents.html", documents=documents, employee=emp)


@employees_bp.route("/documents/<doc_id>/verify", methods=["POST"])
@login_required
def verify_document(doc_id):
    if not hr_admin_required():
        return {"error": "Unauthorized"}, 403

    status = request.form.get("status")
    remarks = request.form.get("remarks", "")
    verifier_id = session.get("employee_id")

    conn, cur = get_db(True)
    try:
        cur.execute("""
            UPDATE employee_documents 
            SET verification_status=%s, remarks=%s, verified_by=%s, verified_at=CURRENT_TIMESTAMP
            WHERE id=%s
            RETURNING employee_id
        """, (status, remarks, verifier_id, doc_id))
        res = cur.fetchone()
        conn.commit()
    finally:
        release_db(conn, cur)
        
    return redirect(f"/hrms/employees/{res['employee_id']}/documents" if res else "/hrms/employees/ui")


@employees_bp.route("/documents/api/pending", methods=["GET"])
@login_required
def api_pending_documents():
    if not hr_admin_required():
        return {"error": "Unauthorized"}, 403

    conn, cur = get_db(True)
    try:
        cur.execute("""
            SELECT d.id, d.document_type, d.document_title, d.created_at, e.full_name, e.id AS employee_id
            FROM employee_documents d
            JOIN hrms_employees e ON d.employee_id = e.id
            WHERE d.verification_status = 'Pending'
            ORDER BY d.created_at DESC
        """)
        docs = cur.fetchall()
    finally:
        release_db(conn, cur)
        
    for d in docs:
        if d.get('created_at'): d['created_at'] = str(d['created_at'])

    return {"documents": docs}, 200