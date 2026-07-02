print("HRMS EMPLOYEES ROUTES LOADED")

from flask import Blueprint, request, render_template, jsonify, redirect, session, flash
from datetime import date, datetime
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
        metrics = {
            "total": len(employees),
            "active": sum(1 for emp in employees if emp["status"] == "Active"),
            "inactive": sum(1 for emp in employees if emp["status"] == "Inactive"),
            "on_leave": sum(1 for emp in employees if emp["status"] == "On Leave"),
            "new_joinees": 0,
            "pending_docs": 0,
            "pending_verification": 0
        }

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
        cur.execute("SELECT employee_code FROM hrms_employees WHERE employee_code LIKE 'EMP-%' ORDER BY created_at DESC LIMIT 1")
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
        try:
            salary_structures = supabase_rest.get_rows("salary_structures", {"select": "id,name", "order": "name.asc"})
        except Exception:
            salary_structures = []
        try:
            managers = supabase_rest.get_rows("hrms_employees", {"select": "id,full_name,employee_code", "status": "not.eq.Deleted", "order": "full_name.asc"})
        except Exception:
            managers = []
        try:
            last_emp = supabase_rest.get_first_row("hrms_employees", {"select": "employee_code", "employee_code": "like.EMP-*", "order": "created_at.desc", "limit": 1})
            next_code = "EMP-0001"
            if last_emp and last_emp.get("employee_code"):
                try:
                    last_num = int(last_emp["employee_code"].split("-")[1])
                    next_code = f"EMP-{(last_num + 1):04d}"
                except:
                    pass
        except Exception:
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
@employees_bp.route("/documents/api/verify/<doc_id>", methods=["POST"])
@login_required
def api_verify_document(doc_id):
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403

    try:
        data = request.get_json(silent=True) or {}
        status = data.get("status")
        remarks = data.get("remarks")
        verified_by = session.get("user_id")

        if status not in ["Verified", "Rejected"]:
            return jsonify({"error": "Invalid status"}), 400

        conn, cur = get_db()
        cur.execute("""
            UPDATE employee_documents
            SET verification_status = %s, remarks = %s, verified_by = %s, verified_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (status, remarks, verified_by, doc_id))
        conn.commit()
        release_db(conn, cur)

        return jsonify({"message": "Document verification updated successfully"}), 200
    except Exception as e:
        print(f"Error verifying document via DB, trying REST fallback: {e}")
        try:
            res = supabase_rest.update_rows(
                "employee_documents",
                {"id": f"eq.{doc_id}"},
                {
                    "verification_status": status,
                    "remarks": remarks,
                    "verified_by": verified_by,
                    "verified_at": datetime.now().isoformat()
                }
            )
            if res:
                return jsonify({"message": "Document verification updated successfully"}), 200
            else:
                return jsonify({"error": "Document not found"}), 404
        except Exception as fallback_err:
            return jsonify({"error": str(fallback_err)}), 500

@employees_bp.route("/<employee_id>/profile", methods=["GET"])
@login_required
def employee_profile(employee_id):
    if not hr_admin_required():
        return redirect("/dashboard")

    conn, cur = None, None
    emp = evals = documents = leaves = salary = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
        
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
        
        if conn:
            release_db(conn, cur)
    except Exception as e:
        print("Error fetching employee profile from DB, trying REST fallback:", e)
        if conn:
            try:
                release_db(conn, cur)
            except:
                pass
        
        try:
            emp = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{employee_id}"})
            evals = supabase_rest.get_rows("performance_evaluations", {
                "employee_id": f"eq.{employee_id}",
                "order": "evaluation_year.desc,evaluation_month.desc,id.desc"
            })
            if evals:
                for ev in evals:
                    ev["evaluator_name"] = "HR Admin"
                    evaluator_id = ev.get("evaluator_id")
                    if evaluator_id:
                        user_row = supabase_rest.get_first_row("hrms_users", {"id": f"eq.{evaluator_id}"})
                        if user_row and user_row.get("employee_id"):
                            emp_row = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{user_row['employee_id']}"})
                            if emp_row:
                                ev["evaluator_name"] = emp_row.get("full_name") or "HR Admin"

            documents = supabase_rest.get_rows("employee_documents", {"employee_id": f"eq.{employee_id}"})
            leaves = supabase_rest.get_rows("leave_applications", {
                "employee_id": f"eq.{employee_id}",
                "order": "created_at.desc"
            })
            if leaves:
                leave_types = {str(lt["id"]): lt["name"] for lt in supabase_rest.list_leave_types()}
                for lv in leaves:
                    lv["leave_type"] = leave_types.get(str(lv.get("leave_type_id")), "Leave")

            salary = supabase_rest.get_first_row("employee_salary", {"employee_id": f"eq.{employee_id}"})
        except Exception as fallback_err:
            print("REST fallback for employee profile failed:", fallback_err)

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

        # Check duplicate emails — only check hrms_employees
        cur.execute("SELECT id FROM hrms_employees WHERE email=%s", (data["email"],))
        if cur.fetchone():
            release_db(conn, cur)
            return jsonify({"error": "Employee email already exists"}), 400

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
                        INSERT INTO employee_documents (employee_id, document_type, document_title, file_url, created_at, verification_status)
                        VALUES (%s, %s, %s, %s, %s, 'Verified')
                    """, (employee_id, "Onboarding", doc_title, res["public_url"], datetime.now()))

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
        print("Add employee error, trying REST fallback:", e)
        try:
            from datetime import datetime as _dt
            plain_password = data.get("password")
            hashed_password = generate_password_hash(plain_password)
            joining_date = data.get("joining_date") or str(date.today())

            # Duplicate checks — only check hrms_employees
            if supabase_rest.get_first_row("hrms_employees", {"select": "id", "employee_code": f"eq.{data['employee_code']}"}):
                return jsonify({"error": f"Employee code {data['employee_code']} already exists"}), 400
            if supabase_rest.get_first_row("hrms_employees", {"select": "id", "email": f"eq.{data['email']}"}):
                return jsonify({"error": "Employee email already exists"}), 400

            # Step 1: Create Employee Record
            base_payload = {
                "employee_code":   data["employee_code"],
                "full_name":       data["full_name"],
                "email":           data["email"],
                "phone":           data.get("phone"),
                "department":      data.get("department"),
                "role_id":         data["role_id"],
                "joining_date":    str(joining_date),
                "status":          "Active",
            }
            full_payload = base_payload.copy()
            full_payload.update({
                "designation":     data.get("designation", "Employee"),
                "manager_id":      data.get("manager_id") or None,
                "gender":          data.get("gender"),
                "date_of_birth":   data.get("date_of_birth") or None,
                "office_location": data.get("office_location"),
                "employment_type": data.get("employment_type", "Full Time"),
            })

            emp_row = supabase_rest.insert_row("hrms_employees", full_payload)
            if not emp_row:
                print("Failed to insert full payload, trying base payload...")
                emp_row = supabase_rest.insert_row("hrms_employees", base_payload)
                
            if not emp_row:
                return jsonify({"error": "Could not create employee record via fallback. Check Supabase logs."}), 500

            employee_id = emp_row.get("id")

            # Step 2: Create Login Account in hrms_users (no Supabase auth.users)
            supabase_rest.insert_row("hrms_users", {
                "email":       data["email"],
                "password":    hashed_password,
                "role_id":     data["role_id"],
                "employee_id": employee_id,
            })

            # Handle Profile Photo Upload
            profile_photo = files.get("profile_photo")
            if profile_photo and profile_photo.filename:
                res = upload_document_to_supabase(profile_photo, employee_id)
                if res:
                    supabase_rest.update_rows("hrms_employees", {"id": f"eq.{employee_id}"}, {"profile_photo_url": res["public_url"]})

            # Step 3: Compensation
            annual_ctc = data.get("annual_ctc", 0)
            try:
                annual_ctc = float(annual_ctc)
            except:
                annual_ctc = 0.0

            if annual_ctc > 0:
                monthly_gross = annual_ctc / 12.0
                sal_row = supabase_rest.insert_row("employee_salary", {
                    "employee_id":    employee_id,
                    "annual_ctc":     annual_ctc,
                    "monthly_salary": monthly_gross,
                    "effective_from": str(joining_date),
                })
                if not sal_row:
                    supabase_rest.insert_row("employee_salary", {
                        "employee_id":    employee_id,
                        "monthly_salary": monthly_gross,
                        "effective_from": str(joining_date),
                    })
                
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
                    supabase_rest.insert_row("employee_salary_components", {
                        "employee_id":    employee_id,
                        "component_name": c_name,
                        "yearly_amount":  y_amt,
                        "monthly_amount": m_amt,
                    })

            # Step 4: Compliance
            if any([data.get("pan_number"), data.get("aadhaar_number"), data.get("uan_number")]):
                supabase_rest.insert_row("employee_compliance", {
                    "employee_id":    employee_id,
                    "pan_number":     data.get("pan_number"),
                    "aadhaar_number": data.get("aadhaar_number"),
                    "uan_number":     data.get("uan_number"),
                    "pf_number":      data.get("pf_number"),
                    "esic_number":    data.get("esic_number"),
                })

            # Step 5: Bank Details
            if any([data.get("bank_name"), data.get("account_number")]):
                supabase_rest.insert_row("employee_bank_details", {
                    "employee_id":              employee_id,
                    "bank_name":                data.get("bank_name"),
                    "account_number":           data.get("account_number"),
                    "ifsc_code":                data.get("ifsc_code"),
                    "branch_name":              data.get("branch_name"),
                    "address":                  data.get("address"),
                    "emergency_contact":        data.get("emergency_contact"),
                    "emergency_contact_number": data.get("emergency_contact_number"),
                })

            # Document Uploads
            doc_fields = [
                ("doc_aadhaar", "Aadhaar Card"),
                ("doc_pan", "PAN Card"),
                ("doc_resume", "Resume"),
                ("doc_offer", "Offer/Experience Letter")
            ]
            for file_key, doc_title in doc_fields:
                doc_file = files.get(file_key)
                if doc_file and doc_file.filename:
                    res = upload_document_to_supabase(doc_file, employee_id)
                    if res:
                        supabase_rest.insert_row("employee_documents", {
                            "employee_id":         employee_id,
                            "document_type":       "Onboarding",
                            "document_title":      doc_title,
                            "file_url":            res["public_url"],
                            "created_at":          _dt.now().isoformat(),
                            "verification_status": "Verified"
                        })

            # Audit Log
            supabase_rest.insert_row("employee_audit_logs", {
                "employee_id":  employee_id,
                "action":       "Employee Created via Onboarding Wizard (REST Fallback)",
                "performed_by": session.get("employee_id") or None,
            })

            # Status History
            supabase_rest.insert_row("employee_status_history", {
                "employee_id": employee_id,
                "status":      "Active",
                "changed_by":  session.get("employee_id") or None,
                "remarks":     "Initial Onboarding",
            })

            # Email automation simulation
            print(f"--- EMAIL AUTOMATION (REST Fallback) ---")
            print(f"To: {data['email']}")
            print(f"Subject: Welcome to the Company!")
            print(f"Your Login: {data['email']}")
            print(f"Your Password: {plain_password}")
            print(f"----------------------------------------")

            return jsonify({"success": True, "redirect": "/hrms/employees/ui"})
        except Exception as rest_err:
            print("Add employee REST fallback also failed:", rest_err)
            return jsonify({"error": f"Failed to create employee: {str(rest_err)}"}), 500

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
        if not conn:
            raise psycopg2.OperationalError("Database connection failed")

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
        if not conn:
            raise psycopg2.OperationalError("Database connection failed")

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
    except Exception as e:
        print("Error updating employee via DB, trying REST fallback:", e)
        try:
            # 1. Update the Employee Profile
            supabase_rest.update_employee(
                employee_id=employee_id,
                full_name=data["full_name"],
                email=data["email"],
                phone=data.get("phone"),
                department=data.get("department"),
                role_id=data["role_id"],
            )

            # 2. Sync the Role and Email to the Login Table (hrms_users)
            supabase_rest.update_rows(
                "hrms_users",
                {"employee_id": f"eq.{employee_id}"},
                {
                    "email": data["email"],
                    "role_id": data["role_id"]
                }
            )

            # 3. Admin Password Reset (If provided)
            new_password = data.get("password", "").strip()
            if new_password and session.get("role") == "Admin":
                hashed_new = generate_password_hash(new_password)
                supabase_rest.update_rows(
                    "hrms_users",
                    {"employee_id": f"eq.{employee_id}"},
                    {"password": hashed_new}
                )
        except Exception as rest_err:
            print("REST fallback for editing employee failed:", rest_err)

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
        if not conn:
            raise psycopg2.OperationalError("Database connection failed")

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

    conn = None
    cur = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise psycopg2.OperationalError("Database connection failed")

        # 1. Soft delete the employee profile
        cur.execute("""
            UPDATE hrms_employees
            SET status='Deleted'
            WHERE id=%s
        """, (employee_id,))

        # 2. Delete the login credentials from hrms_users to revoke login & free up the email
        cur.execute("DELETE FROM hrms_users WHERE employee_id=%s", (employee_id,))

        conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        print("DB delete error, trying REST fallback:", e)
        # Fallback via Supabase REST
        supabase_rest.soft_delete_employee(employee_id)
        supabase_rest.delete_rows("hrms_users", {"employee_id": f"eq.{employee_id}"})
    finally:
        if conn and cur:
            release_db(conn, cur)

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

    conn, cur = None, None
    documents = []
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
        
        cur.execute("SELECT * FROM employee_documents WHERE employee_id=%s ORDER BY created_at DESC", (employee_id,))
        documents = cur.fetchall()
        if conn:
            release_db(conn, cur)
    except Exception as e:
        print("Error fetching my documents via DB, trying REST fallback:", e)
        if conn:
            try:
                release_db(conn, cur)
            except:
                pass
        try:
            documents = supabase_rest.get_rows("employee_documents", {
                "employee_id": f"eq.{employee_id}",
                "order": "created_at.desc"
            })
        except Exception as rest_err:
            print("REST fallback for my documents failed:", rest_err)

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
    request_id = request.form.get("request_id")
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
        if not conn:
            raise Exception("No DB connection")
            
        if request_id:
            cur.execute("""
                UPDATE employee_documents 
                SET file_url = %s, verification_status = 'Pending', document_title = %s, document_type = %s
                WHERE id = %s AND employee_id = %s
            """, (res["public_url"], doc_title, doc_type, request_id, employee_id))
        else:
            cur.execute("""
                INSERT INTO employee_documents (employee_id, document_type, document_title, file_url, verification_status)
                VALUES (%s, %s, %s, %s, 'Pending')
            """, (employee_id, doc_type, doc_title, res["public_url"]))
        conn.commit()
        release_db(conn, cur)
        from flask import flash
        flash("Document uploaded successfully.", "success")
    except Exception as e:
        print("Error saving document info to DB, trying REST fallback:", e)
        try:
            if 'res' in locals() and res:
                if request_id:
                    supabase_rest.update_rows("employee_documents", 
                        {"id": f"eq.{request_id}", "employee_id": f"eq.{employee_id}"},
                        {
                            "file_url": res["public_url"],
                            "verification_status": "Pending",
                            "document_title": doc_title,
                            "document_type": doc_type
                        }
                    )
                else:
                    supabase_rest.insert_row("employee_documents", {
                        "employee_id": employee_id,
                        "document_type": doc_type,
                        "document_title": doc_title,
                        "file_url": res["public_url"],
                        "verification_status": "Pending"
                    })
                from flask import flash
                flash("Document uploaded successfully.", "success")
            else:
                from flask import flash
                flash(f"Upload failed: {e}", "error")
        except Exception as rest_err:
            print("REST fallback for document upload failed:", rest_err)
            from flask import flash
            flash(f"Upload failed: {rest_err}", "error")

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
    conn, cur = None, None
    doc = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
            
        cur.execute("SELECT file_url FROM employee_documents WHERE id=%s", (doc_id,))
        doc = cur.fetchone()
        if conn:
            release_db(conn, cur)
    except Exception as e:
        print("Error fetching document info from DB, trying REST fallback:", e)
        if conn:
            try:
                release_db(conn, cur)
            except:
                pass
        try:
            doc = supabase_rest.get_first_row("employee_documents", {
                "select": "file_url",
                "id": f"eq.{doc_id}"
            })
        except Exception as rest_err:
            print("REST fallback for viewing document failed:", rest_err)

    if not doc:
        from flask import flash
        flash("Document not found.", "error")
        return redirect(request.referrer or "/hrms/employees/ui")

    url = doc.get("file_url")
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
                    return "Document preview unavailable. Please try again later.", 503
            except Exception:
                return "Document preview unavailable. Please try again later.", 503

    # Fallback to the public URL if signed URL generation fails
    return redirect(url)


@employees_bp.route("/documents/<doc_id>/delete", methods=["POST"])
@login_required
def delete_document(doc_id):
    employee_id = session.get("employee_id")
    if not employee_id:
        return {"error": "Unauthorized"}, 403

    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
        cur.execute("DELETE FROM employee_documents WHERE id=%s AND employee_id=%s", (doc_id, employee_id))
        conn.commit()
        if conn:
            release_db(conn, cur)
    except Exception as e:
        print("Error deleting document from DB, trying REST fallback:", e)
        if conn:
            try:
                release_db(conn, cur)
            except:
                pass
        try:
            success = supabase_rest.delete_rows("employee_documents", {
                "id": f"eq.{doc_id}",
                "employee_id": f"eq.{employee_id}"
            })
            if not success:
                return {"error": "Failed to delete document"}, 500
        except Exception as rest_err:
            print("REST fallback for deleting document failed:", rest_err)
            return {"error": str(rest_err)}, 500

    return {"message": "Deleted"}, 200


@employees_bp.route("/<employee_id>/documents", methods=["GET"])
@login_required
def employee_documents_hr(employee_id):
    if not hr_admin_required():
        return redirect("/dashboard")

    conn, cur = None, None
    emp = None
    documents = []
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
        cur.execute("SELECT full_name FROM hrms_employees WHERE id=%s", (employee_id,))
        emp = cur.fetchone()
        
        cur.execute("""
            SELECT d.id, d.employee_id, d.document_title, d.document_type, d.file_url, d.verification_status, d.created_at 
            FROM employee_documents d
            WHERE d.employee_id=%s ORDER BY d.created_at DESC
        """, (employee_id,))
        documents = cur.fetchall()
        if conn:
            release_db(conn, cur)
    except Exception as e:
        print("Error fetching employee documents via DB, trying REST fallback:", e)
        if conn:
            try:
                release_db(conn, cur)
            except:
                pass
        try:
            emp = supabase_rest.get_first_row("hrms_employees", {
                "select": "full_name",
                "id": f"eq.{employee_id}"
            })
            documents = supabase_rest.get_rows("employee_documents", {
                "employee_id": f"eq.{employee_id}",
                "order": "created_at.desc"
            })
            if documents:
                for doc in documents:
                    doc["uploaded_by_name"] = "System"
                    doc["verified_by_name"] = "System"
        except Exception as rest_err:
            print("REST fallback for employee documents HR failed:", rest_err)

    return render_template("hrms/manage_documents.html", documents=documents, employee=emp)


@employees_bp.route("/documents/<doc_id>/verify", methods=["POST"])
@login_required
def verify_document(doc_id):
    if not hr_admin_required():
        return {"error": "Unauthorized"}, 403

    status = request.form.get("status")
    remarks = request.form.get("remarks", "")
    verifier_id = session.get("employee_id")

    conn, cur = None, None
    res = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
        cur.execute("""
            UPDATE employee_documents 
            SET verification_status=%s, remarks=%s, verified_by=%s, verified_at=CURRENT_TIMESTAMP
            WHERE id=%s
            RETURNING employee_id
        """, (status, remarks, verifier_id, doc_id))
        res = cur.fetchone()
        conn.commit()
        if conn:
            release_db(conn, cur)
    except Exception as e:
        print("Error verifying document via DB, trying REST fallback:", e)
        if conn:
            try:
                release_db(conn, cur)
            except:
                pass
        try:
            doc = supabase_rest.get_first_row("employee_documents", {"select": "employee_id", "id": f"eq.{doc_id}"})
            if doc:
                res = {"employee_id": doc.get("employee_id")}
                supabase_rest.update_rows(
                    "employee_documents",
                    {"id": f"eq.{doc_id}"},
                    {
                        "verification_status": status,
                        "remarks": remarks,
                        "verified_by": verifier_id,
                        "verified_at": datetime.now().isoformat()
                    }
                )
        except Exception as rest_err:
            print("REST fallback for document verification failed:", rest_err)
        
    return redirect(f"/hrms/employees/{res['employee_id']}/documents" if res else "/hrms/employees/ui")


@employees_bp.route("/documents/api/pending", methods=["GET"])
@login_required
def api_pending_documents():
    if not hr_admin_required():
        return {"error": "Unauthorized"}, 403

    conn, cur = None, None
    docs = []
    try:
        conn, cur = get_db(True)
        if not conn:
            raise psycopg2.OperationalError("Database connection failed")
        cur.execute("""
            SELECT d.id, d.document_type, d.document_title, d.created_at, e.full_name, e.id AS employee_id
            FROM employee_documents d
            JOIN hrms_employees e ON d.employee_id = e.id
            WHERE d.verification_status = 'Pending'
            ORDER BY d.created_at DESC
        """)
        docs = cur.fetchall()
    except Exception as e:
        print("Error fetching pending documents:", e)
        try:
            raw_docs = supabase_rest.get_rows("employee_documents", {"verification_status": "eq.Pending", "order": "created_at.desc"})
            for d in raw_docs:
                docs.append({
                    "id": d.get("id"),
                    "document_type": d.get("document_type"),
                    "document_title": d.get("document_title"),
                    "created_at": d.get("created_at"),
                    "full_name": "Employee", 
                    "employee_id": d.get("employee_id")
                })
        except Exception as ex:
            print("Supabase fallback failed for pending docs:", ex)
    finally:
        if conn:
            release_db(conn, cur)
        
    for d in docs:
        if d.get('created_at'): d['created_at'] = str(d['created_at'])

    return {"documents": docs}, 200

# =========================
# DOCUMENTS HUB (HR)
# =========================
@employees_bp.route("/documents-hub", methods=["GET"])
@login_required
def documents_hub():
    if not hr_admin_required():
        return "Unauthorized", 403

    status_filter = request.args.get("status", "")
    role_filter = request.args.get("role", "")
    search_filter = request.args.get("search", "").lower()

    conn, cur = None, None
    documents = []
    roles = []
    all_employees = []
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No database connection available")
        
        # Fetch Roles
        cur.execute("SELECT id, role_name FROM hrms_roles ORDER BY role_name")
        roles = cur.fetchall()

        # Fetch Employees for the modal
        cur.execute("SELECT id, full_name, employee_code FROM hrms_employees WHERE status='Active' ORDER BY full_name")
        all_employees = cur.fetchall()

        # Build query
        query = """
            SELECT d.*, e.full_name as employee_name, e.employee_code, r.role_name
            FROM employee_documents d
            JOIN hrms_employees e ON d.employee_id = e.id
            LEFT JOIN hrms_roles r ON e.role_id = r.id
            WHERE 1=1
        """
        params = []
        if status_filter:
            query += " AND d.verification_status = %s"
            params.append(status_filter)
        if role_filter:
            query += " AND r.id = %s"
            params.append(role_filter)
        
        query += " ORDER BY d.created_at DESC"
        cur.execute(query, tuple(params))
        documents = cur.fetchall()

        if search_filter:
            documents = [d for d in documents if search_filter in d.get("employee_name", "").lower() or search_filter in d.get("employee_code", "").lower()]

    except Exception as e:
        print("Error fetching documents hub via DB, trying REST fallback:", e)
        try:
            roles = supabase_rest.get_rows("hrms_roles", {"order": "role_name.asc"})
            all_employees = supabase_rest.get_rows("hrms_employees", {"status": "eq.Active", "order": "full_name.asc", "select": "id, full_name, employee_code, role_id"})
            
            role_name_map = {r["id"]: r["role_name"] for r in roles}
            emp_map = {e["id"]: e for e in all_employees}

            docs_query = {"order": "created_at.desc"}
            if status_filter:
                docs_query["verification_status"] = f"eq.{status_filter}"
            
            raw_docs = supabase_rest.get_rows("employee_documents", docs_query)
            
            documents = []
            for d in raw_docs:
                emp = emp_map.get(d.get("employee_id"), {})
                emp_name = emp.get("full_name", "Unknown")
                emp_code = emp.get("employee_code", "")
                
                role_id = emp.get("role_id")
                r_name = role_name_map.get(role_id, "")

                if role_filter and str(role_id) != str(role_filter):
                    continue

                if search_filter:
                    if search_filter not in emp_name.lower() and search_filter not in emp_code.lower():
                        continue

                d["employee_name"] = emp_name
                d["employee_code"] = emp_code
                d["role_name"] = r_name
                documents.append(d)

        except Exception as rest_err:
            print("REST fallback for documents hub failed:", rest_err)
    finally:
        if conn: release_db(conn, cur)

    return render_template("hrms/documents_hub.html", documents=documents, roles=roles, all_employees=all_employees)

@employees_bp.route("/documents/request", methods=["POST"])
@login_required
def request_document():
    if not hr_admin_required():
        return "Unauthorized", 403

    employee_id = request.form.get("employee_id")
    document_type = request.form.get("document_type")
    document_title = request.form.get("document_title") or document_type

    conn, cur = get_db()
    try:
        if not conn:
            raise Exception("No DB Connection")
        cur.execute("""
            INSERT INTO employee_documents (employee_id, document_type, document_title, verification_status)
            VALUES (%s, %s, %s, 'Requested')
        """, (employee_id, document_type, document_title))
        flash("Document requested successfully.", "success")
    except Exception as e:
        print("DB Request Document Error:", e)
        try:
            supabase_rest.insert_row("employee_documents", {
                "employee_id": employee_id,
                "document_type": document_type,
                "document_title": document_title,
                "verification_status": "Requested"
            })
            flash("Document requested successfully (REST).", "success")
        except Exception as rest_err:
            print("REST Request Document Error:", rest_err)
            flash("Failed to request document.", "error")
    finally:
        if conn: release_db(conn, cur)

    return redirect("/hrms/employees/documents-hub")