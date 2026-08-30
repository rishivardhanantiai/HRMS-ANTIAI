from flask import Blueprint, render_template, session, request, redirect, flash, jsonify
from utils.db import get_db, release_db
from utils import supabase_rest
from utils.auth import login_required, role_required
from hrms.notifications.routes import create_notification
from datetime import datetime

helpdesk_bp = Blueprint("helpdesk", __name__, url_prefix="/hrms/helpdesk")

@helpdesk_bp.route("/", methods=["GET"])
@login_required
def index():
    role = session.get("role")
    email = session.get("email")
    conn, cur = None, None
    queries = []
    
    # If the user is HR/Admin, redirect to manage view
    if role in ["HR", "Admin"]:
        return redirect("/hrms/helpdesk/manage")
        
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB Connection")
            
        cur.execute("""
            SELECT q.*, e.full_name as employee_name
            FROM employee_queries q
            JOIN hrms_employees e ON q.employee_id = e.id
            WHERE e.email = %s
            ORDER BY q.created_at DESC
        """, (email,))
        queries = cur.fetchall()
        release_db(conn, cur)
    except Exception as e:
        print("Error fetching employee helpdesk queries via DB, trying REST:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            # Fallback to REST: get employee first
            emp = supabase_rest.get_rows("hrms_employees", {"email": f"eq.{email}"})
            if emp:
                emp_id = emp[0]["id"]
                queries = supabase_rest.get_rows("employee_queries", {
                    "employee_id": f"eq.{emp_id}",
                    "order": "created_at.desc"
                })
                for q in queries:
                    q["employee_name"] = emp[0]["full_name"]
        except Exception as rest_err:
            print("REST fallback for helpdesk index failed:", rest_err)
            
    return render_template("hrms/helpdesk_employee.html", queries=queries)


@helpdesk_bp.route("/create", methods=["POST"])
@login_required
def create_query():
    email = session.get("email")
    subject = request.form.get("subject")
    description = request.form.get("description")
    
    if not subject or not description:
        flash("Subject and Description are required.", "error")
        return redirect("/hrms/helpdesk/")
        
    conn, cur = get_db(True)
    try:
        if not conn:
            raise Exception("No DB Connection")
            
        # Get employee ID
        cur.execute("SELECT id, full_name FROM hrms_employees WHERE email = %s", (email,))
        emp = cur.fetchone()
        if not emp:
            raise Exception("Employee record not found")
            
        cur.execute("""
            INSERT INTO employee_queries (employee_id, subject, description, status)
            VALUES (%s, %s, %s, 'Open')
            RETURNING id
        """, (emp["id"], subject, description))
        conn.commit()
        
        # Trigger notification to HR
        try:
            create_notification(
                recipient_role="HR",
                notif_type="query_created",
                message=f"New query from {emp['full_name']}: {subject}",
                link="/hrms/helpdesk/manage"
            )
        except Exception as notif_err:
            print("Failed to raise helpdesk notification:", notif_err)
            
        flash("Your query ticket has been raised successfully.", "success")
        release_db(conn, cur)
    except Exception as e:
        print("DB Helpdesk Create Error:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            emp = supabase_rest.get_rows("hrms_employees", {"email": f"eq.{email}"})
            if emp:
                res = supabase_rest.insert_row("employee_queries", {
                    "employee_id": emp[0]["id"],
                    "subject": subject,
                    "description": description,
                    "status": "Open"
                })
                # Trigger notification
                try:
                    create_notification(
                        recipient_role="HR",
                        notif_type="query_created",
                        message=f"New query from {emp[0]['full_name']}: {subject}",
                        link="/hrms/helpdesk/manage"
                    )
                except:
                    pass
                flash("Your query ticket has been raised successfully (REST).", "success")
            else:
                flash("Could not locate employee record.", "error")
        except Exception as rest_err:
            print("REST Helpdesk Create Error:", rest_err)
            flash("Failed to raise query.", "error")
            
    return redirect("/hrms/helpdesk/")


@helpdesk_bp.route("/manage", methods=["GET"])
@login_required
@role_required(["HR", "Admin"])
def manage_queries():
    conn, cur = None, None
    queries = []
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB Connection")
            
        cur.execute("""
            SELECT q.*, e.full_name as employee_name, e.department, e.designation
            FROM employee_queries q
            JOIN hrms_employees e ON q.employee_id = e.id
            ORDER BY 
                CASE q.status 
                    WHEN 'Open' THEN 1 
                    WHEN 'In Progress' THEN 2 
                    WHEN 'Resolved' THEN 3 
                END,
                q.created_at DESC
        """)
        queries = cur.fetchall()
        release_db(conn, cur)
    except Exception as e:
        print("Error fetching helpdesk queries via DB, trying REST:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            queries = supabase_rest.get_rows("employee_queries", {"order": "created_at.desc"})
            # Fetch employees to map names
            emps = supabase_rest.get_rows("hrms_employees", {"select": "id,full_name,department,designation"})
            emp_map = {emp["id"]: emp for emp in emps}
            for q in queries:
                emp = emp_map.get(q.get("employee_id"), {})
                q["employee_name"] = emp.get("full_name", "Unknown")
                q["department"] = emp.get("department", "N/A")
                q["designation"] = emp.get("designation", "N/A")
        except Exception as rest_err:
            print("REST fallback for helpdesk manage failed:", rest_err)
            
    return render_template("hrms/helpdesk_hr.html", queries=queries)


@helpdesk_bp.route("/<id>/respond", methods=["POST"])
@login_required
@role_required(["HR", "Admin"])
def respond_query(id):
    hr_response = request.form.get("hr_response")
    status = request.form.get("status", "Resolved")
    
    if not hr_response:
        flash("Response body cannot be empty.", "error")
        return redirect("/hrms/helpdesk/manage")
        
    resolved_at = datetime.utcnow() if status == "Resolved" else None
    
    conn, cur = get_db()
    try:
        if not conn:
            raise Exception("No DB Connection")
            
        cur.execute("""
            UPDATE employee_queries
            SET hr_response = %s, status = %s, resolved_at = %s
            WHERE id = %s
        """, (hr_response, status, resolved_at, id))
        conn.commit()
        flash(f"Ticket response submitted. Status updated to {status}.", "success")
        release_db(conn, cur)
    except Exception as e:
        print("DB Helpdesk Respond Error:", e)
        if conn:
            try: release_db(conn, cur)
            except: pass
        try:
            payload = {
                "hr_response": hr_response,
                "status": status
            }
            if resolved_at:
                payload["resolved_at"] = resolved_at.isoformat()
            supabase_rest.update_row("employee_queries", {"id": f"eq.{id}"}, payload)
            flash(f"Ticket response submitted (REST). Status updated to {status}.", "success")
        except Exception as rest_err:
            print("REST Helpdesk Respond Error:", rest_err)
            flash("Failed to respond to query.", "error")
            
    return redirect("/hrms/helpdesk/manage")
