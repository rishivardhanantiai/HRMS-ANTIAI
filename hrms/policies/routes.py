from flask import Blueprint, render_template, session, request, redirect, flash, jsonify
from utils.db import get_db, release_db
from utils import supabase_rest
from utils.auth import login_required, role_required
from hrms.notifications.routes import create_notification
from hrms.offers.routes import _render_pdf_and_upload
from datetime import datetime

policies_bp = Blueprint("policies", __name__, url_prefix="/hrms/policies")

@policies_bp.route("/", methods=["GET"])
@login_required
def index():
    role = session.get("role")
    email = session.get("email")
    
    # If the user is HR/Admin, redirect to manage view
    if role in ["HR", "Admin"]:
        return redirect("/hrms/policies/manage")
        
    conn, cur = None, None
    pending_signatures = []
    signed_policies = []
    
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB Connection")
            
        cur.execute("""
            SELECT ps.id as sig_id, ps.status, ps.signed_at, ps.pdf_url, pd.title, pd.content_html
            FROM employee_policy_signatures ps
            JOIN policy_documents pd ON ps.policy_id = pd.id
            JOIN hrms_employees e ON ps.employee_id = e.id
            WHERE e.email = %s
            ORDER BY pd.title ASC
        """, (email,))
        rows = cur.fetchall()
        release_db(conn, cur)
        
        for r in rows:
            if r["status"] == "Signed":
                signed_policies.append(r)
            else:
                pending_signatures.append(r)
    except Exception as e:
        print("Error fetching employee policies via DB, trying REST:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            # Fallback to REST
            emp = supabase_rest.get_rows("hrms_employees", {"email": f"eq.{email}"})
            if emp:
                emp_id = emp[0]["id"]
                sigs = supabase_rest.get_rows("employee_policy_signatures", {"employee_id": f"eq.{emp_id}"})
                pols = supabase_rest.get_rows("policy_documents", {})
                pol_map = {p["id"]: p for p in pols}
                for sig in sigs:
                    p = pol_map.get(sig["policy_id"], {})
                    sig_data = {
                        "sig_id": sig["id"],
                        "status": sig["status"],
                        "signed_at": sig.get("signed_at"),
                        "pdf_url": sig.get("pdf_url"),
                        "title": p.get("title", "Unknown Policy"),
                        "content_html": p.get("content_html", "")
                    }
                    if sig["status"] == "Signed":
                        signed_policies.append(sig_data)
                    else:
                        pending_signatures.append(sig_data)
        except Exception as rest_err:
            print("REST fallback for employee policies index failed:", rest_err)
            
    return render_template("hrms/policies_employee.html", pending=pending_signatures, signed=signed_policies)


@policies_bp.route("/esign/<sig_id>", methods=["GET"])
@login_required
def esign_view(sig_id):
    conn, cur = None, None
    policy = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB Connection")
            
        cur.execute("""
            SELECT ps.id as sig_id, ps.status, pd.title, pd.content_html, e.full_name as employee_name
            FROM employee_policy_signatures ps
            JOIN policy_documents pd ON ps.policy_id = pd.id
            JOIN hrms_employees e ON ps.employee_id = e.id
            WHERE ps.id = %s
        """, (sig_id,))
        policy = cur.fetchone()
        release_db(conn, cur)
    except Exception as e:
        print("Error fetching esign policy via DB, trying REST:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            sig = supabase_rest.get_rows("employee_policy_signatures", {"id": f"eq.{sig_id}"})
            if sig:
                p = supabase_rest.get_rows("policy_documents", {"id": f"eq.{sig[0]['policy_id']}"})
                emp = supabase_rest.get_rows("hrms_employees", {"id": f"eq.{sig[0]['employee_id']}"})
                if p and emp:
                    policy = {
                        "sig_id": sig_id,
                        "status": sig[0]["status"],
                        "title": p[0]["title"],
                        "content_html": p[0]["content_html"],
                        "employee_name": emp[0]["full_name"]
                    }
        except Exception as rest_err:
            print("REST fallback for esign view failed:", rest_err)
            
    if not policy:
        return "Policy sign-off request not found", 404
        
    if policy["status"] == "Signed":
        return render_template("esign_invalid.html", reason="already_signed", doc="policy")
        
    return render_template("esign_policy.html", policy=policy, token=sig_id)


@policies_bp.route("/esign/<sig_id>", methods=["POST"])
@login_required
def esign_submit(sig_id):
    signed_name = request.form.get("signed_name")
    agree = request.form.get("agree")
    
    if not signed_name or not agree:
        return jsonify({"error": "Signature confirmation is required."}), 400
        
    ip_addr = request.remote_addr or "127.0.0.1"
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    conn, cur = None, None
    policy = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB Connection")
            
        cur.execute("""
            SELECT ps.id as sig_id, ps.employee_id, pd.title, pd.content_html, e.full_name as employee_name, e.email as employee_email
            FROM employee_policy_signatures ps
            JOIN policy_documents pd ON ps.policy_id = pd.id
            JOIN hrms_employees e ON ps.employee_id = e.id
            WHERE ps.id = %s
        """, (sig_id,))
        policy = cur.fetchone()
        release_db(conn, cur)
    except Exception as e:
        print("Error checking policy signature via DB, trying REST:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            sig = supabase_rest.get_rows("employee_policy_signatures", {"id": f"eq.{sig_id}"})
            if sig:
                p = supabase_rest.get_rows("policy_documents", {"id": f"eq.{sig[0]['policy_id']}"})
                emp = supabase_rest.get_rows("hrms_employees", {"id": f"eq.{sig[0]['employee_id']}"})
                if p and emp:
                    policy = {
                        "sig_id": sig_id,
                        "employee_id": sig[0]["employee_id"],
                        "title": p[0]["title"],
                        "content_html": p[0]["content_html"],
                        "employee_name": emp[0]["full_name"],
                        "employee_email": emp[0]["email"]
                    }
        except Exception as rest_err:
            print("REST fallback for policy check failed:", rest_err)
            
    if not policy:
        return jsonify({"error": "Policy request not found."}), 404
        
    # Append the electronic signature block to the policy content
    sig_block = f"""
    <div style="margin-top: 50px; border-top: 1.5px solid #111; padding-top: 20px; font-family: 'Times New Roman', Georgia, serif; font-size: 13px; line-height: 1.5;">
        <p style="font-weight: bold; font-size: 14px; margin-bottom: 8px;">ELECTRONIC SIGN-OFF &amp; ACKNOWLEDGMENT</p>
        <p>This document has been electronically read, acknowledged, and signed by the employee.</p>
        <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
            <tr>
                <td style="border: 1px solid #333; padding: 8px; font-weight: bold; width: 150px;">Signed By (Legal Name):</td>
                <td style="border: 1px solid #333; padding: 8px;">{signed_name}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #333; padding: 8px; font-weight: bold;">Employee Email:</td>
                <td style="border: 1px solid #333; padding: 8px;">{policy['employee_email']}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #333; padding: 8px; font-weight: bold;">Signature Timestamp:</td>
                <td style="border: 1px solid #333; padding: 8px;">{now_str}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #333; padding: 8px; font-weight: bold;">IP Address:</td>
                <td style="border: 1px solid #333; padding: 8px;">{ip_addr}</td>
            </tr>
        </table>
        <p style="font-size: 10px; color: #555; margin-top: 12px; font-style: italic;">
            This constitutes a binding electronic acknowledgment under Section 11 of the Information Technology Act, 2000 of India.
        </p>
    </div>
    """
    
    full_html = policy["content_html"] + sig_block
    
    # Render PDF and upload to Storage
    pdf_url = _render_pdf_and_upload(full_html, f"policy_{sig_id}", policy["title"])
    if not pdf_url:
        return jsonify({"error": "Failed to generate signed PDF. Please contact Admin."}), 500
        
    conn, cur = get_db()
    try:
        if not conn:
            raise Exception("No DB Connection")
            
        cur.execute("""
            UPDATE employee_policy_signatures
            SET signed_name = %s, signature_ip = %s, signed_at = %s, status = 'Signed', pdf_url = %s
            WHERE id = %s
        """, (signed_name, ip_addr, datetime.utcnow(), pdf_url, sig_id))
        
        # Also log it into employee_documents so it is searchable
        cur.execute("""
            INSERT INTO employee_documents (employee_id, document_type, document_title, file_url, verification_status)
            VALUES (%s, 'Policy', %s, %s, 'Verified')
        """, (policy["employee_id"], f"Signed Policy: {policy['title']}", pdf_url))
        
        conn.commit()
        release_db(conn, cur)
    except Exception as e:
        print("DB Policy Sign Error:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            supabase_rest.update_row("employee_policy_signatures", {"id": f"eq.{sig_id}"}, {
                "signed_name": signed_name,
                "signature_ip": ip_addr,
                "signed_at": datetime.utcnow().isoformat(),
                "status": "Signed",
                "pdf_url": pdf_url
            })
            supabase_rest.insert_row("employee_documents", {
                "employee_id": policy["employee_id"],
                "document_type": "Policy",
                "document_title": f"Signed Policy: {policy['title']}",
                "file_url": pdf_url,
                "verification_status": "Verified"
            })
        except Exception as rest_err:
            print("REST Policy Sign Error:", rest_err)
            return jsonify({"error": "Failed to save signature."}), 500
            
    return jsonify({"success": True})


@policies_bp.route("/manage", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def manage_policies():
    conn, cur = None, None
    policies = []
    signatures = []
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB Connection")
            
        cur.execute("SELECT * FROM policy_documents ORDER BY title ASC")
        policies = cur.fetchall()
        
        cur.execute("""
            SELECT ps.*, pd.title as policy_title, e.full_name as employee_name, e.department
            FROM employee_policy_signatures ps
            JOIN policy_documents pd ON ps.policy_id = pd.id
            JOIN hrms_employees e ON ps.employee_id = e.id
            ORDER BY ps.created_at DESC
        """)
        signatures = cur.fetchall()
        release_db(conn, cur)
    except Exception as e:
        print("Error loading policy manager via DB, trying REST:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            policies = supabase_rest.get_rows("policy_documents", {"order": "title.asc"})
            sigs = supabase_rest.get_rows("employee_policy_signatures", {"order": "created_at.desc"})
            emps = supabase_rest.get_rows("hrms_employees", {"select": "id,full_name,department"})
            emp_map = {emp["id"]: emp for emp in emps}
            pol_map = {p["id"]: p["title"] for p in policies}
            signatures = []
            for s in sigs:
                emp = emp_map.get(s["employee_id"], {})
                signatures.append({
                    "id": s["id"],
                    "status": s["status"],
                    "signed_at": s.get("signed_at"),
                    "pdf_url": s.get("pdf_url"),
                    "policy_title": pol_map.get(s["policy_id"], "Unknown Policy"),
                    "employee_name": emp.get("full_name", "Unknown"),
                    "department": emp.get("department", "N/A"),
                    "created_at": s.get("created_at")
                })
        except Exception as rest_err:
            print("REST fallback for policy manage failed:", rest_err)
            
    return render_template("hrms/policies_hr.html", policies=policies, signatures=signatures)


@policies_bp.route("/create", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def create_policy():
    title = request.form.get("title")
    content_html = request.form.get("content_html")
    
    if not title or not content_html:
        flash("Title and Content are required.", "error")
        return redirect("/hrms/policies/manage")
        
    conn, cur = get_db()
    try:
        if not conn:
            raise Exception("No DB Connection")
            
        cur.execute("""
            INSERT INTO policy_documents (title, content_html)
            VALUES (%s, %s)
        """, (title, content_html))
        conn.commit()
        flash("Policy document created successfully.", "success")
        release_db(conn, cur)
    except Exception as e:
        print("DB Policy Create Error:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            supabase_rest.insert_row("policy_documents", {
                "title": title,
                "content_html": content_html
            })
            flash("Policy document created successfully (REST).", "success")
        except Exception as rest_err:
            print("REST Policy Create Error:", rest_err)
            flash("Failed to create policy document.", "error")
            
    return redirect("/hrms/policies/manage")


@policies_bp.route("/<id>/assign-all", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def assign_all(id):
    conn, cur = get_db(True)
    try:
        if not conn:
            raise Exception("No DB Connection")
            
        # Get policy title
        cur.execute("SELECT title FROM policy_documents WHERE id = %s", (id,))
        pol = cur.fetchone()
        if not pol:
            raise Exception("Policy document not found")
            
        # Get active employees
        cur.execute("SELECT id, full_name FROM hrms_employees WHERE status = 'Active'")
        employees = cur.fetchall()
        
        assigned_count = 0
        for emp in employees:
            try:
                # Use INSERT ... ON CONFLICT DO NOTHING to avoid duplicate assignments
                cur.execute("""
                    INSERT INTO employee_policy_signatures (employee_id, policy_id, status)
                    VALUES (%s, %s, 'Pending')
                    ON CONFLICT (employee_id, policy_id) DO NOTHING
                """, (emp["id"], id))
                
                # Check if it was actually inserted
                if cur.rowcount > 0:
                    assigned_count += 1
                    # Send notification to the employee
                    try:
                        create_notification(
                            recipient_role="HR",
                            notif_type="policy_assigned",
                            message=f"Requested policy sign-off from {emp['full_name']}: {pol['title']}"
                        )
                    except:
                        pass
            except Exception as loop_err:
                print(f"Error assigning to {emp['full_name']}:", loop_err)
                
        conn.commit()
        flash(f"Policy '{pol['title']}' assigned to {assigned_count} employees.", "success")
        release_db(conn, cur)
    except Exception as e:
        print("DB Policy Assign Error:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            pol = supabase_rest.get_rows("policy_documents", {"id": f"eq.{id}"})
            emps = supabase_rest.get_rows("hrms_employees", {"status": "eq.Active"})
            assigned_count = 0
            for emp in emps:
                try:
                    # Supabase REST insert
                    supabase_rest.insert_row("employee_policy_signatures", {
                        "employee_id": emp["id"],
                        "policy_id": id,
                        "status": "Pending"
                    })
                    assigned_count += 1
                except:
                    # Ignore conflict exceptions
                    pass
            flash(f"Policy '{pol[0]['title']}' assigned to {assigned_count} employees (REST).", "success")
        except Exception as rest_err:
            print("REST Policy Assign Error:", rest_err)
            flash("Failed to assign policy.", "error")
            
    return redirect("/hrms/policies/manage")


@policies_bp.route("/preview/<id>", methods=["GET"])
@login_required
def preview_policy(id):
    conn, cur = None, None
    policy = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB Connection")
        cur.execute("SELECT * FROM policy_documents WHERE id = %s", (id,))
        policy = cur.fetchone()
        release_db(conn, cur)
    except Exception as e:
        print("Error fetching policy for preview via DB, trying REST:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            p = supabase_rest.get_rows("policy_documents", {"id": f"eq.{id}"})
            if p:
                policy = p[0]
        except Exception as rest_err:
            print("REST fallback for policy preview failed:", rest_err)
            
    if not policy:
        return "Policy document not found", 404
        
    return render_template("preview_policy.html", policy=policy)
