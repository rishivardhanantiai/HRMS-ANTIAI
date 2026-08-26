"""
Self-service employee onboarding.

Flow:
  1. HR fills a short "who are we hiring" form (name, email, role,
     designation, department, joining date) -> a minimal employee shell
     is created with onboarding_status='Invited' and a one-time secure
     link is emailed to the candidate.
  2. The candidate opens the link (no login needed) and fills in their
     own personal/bank/compliance details, uploads their own documents,
     accepts the offer, and sets their own HRMS password.
     -> onboarding_status='Submitted'.
  3. HR reviews the submitted documents in the existing Documents Hub
     and clicks "Activate" on the onboarding pipeline page.
     -> status='Active', onboarding_status='Active'; the candidate gets
     an activation email and can now log in.

Two blueprints live in this file:
  - onboarding_bp         (HR-only, under /hrms/onboarding, requires login)
  - onboarding_public_bp  (candidate-facing, under /onboarding, token-gated,
                            deliberately NOT behind @login_required)
"""

import os
import secrets
from datetime import date, datetime, timedelta

from flask import (
    Blueprint, request, render_template, redirect, session,
    flash, jsonify, url_for
)
from werkzeug.security import generate_password_hash

from utils.db import get_db, release_db
from utils.auth import login_required
from utils import supabase_rest
from utils import mailer
from hrms.notifications.routes import create_notification

onboarding_bp = Blueprint(
    "onboarding", __name__, url_prefix="/hrms/onboarding"
)
onboarding_public_bp = Blueprint(
    "onboarding_public", __name__, url_prefix="/onboarding"
)

TOKEN_VALID_DAYS = 7


def hr_admin_required():
    return session.get("role") in ["HR", "Admin"]


def _next_employee_code(cur):
    cur.execute(
        "SELECT employee_code FROM hrms_employees WHERE employee_code LIKE 'EMP-%' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    last_emp = cur.fetchone()
    next_code = "EMP-0001"
    if last_emp and last_emp["employee_code"]:
        try:
            last_num = int(last_emp["employee_code"].split("-")[1])
            next_code = f"EMP-{(last_num + 1):04d}"
        except Exception:
            pass
    return next_code


def _new_token():
    return secrets.token_urlsafe(32)


def _hr_notify_email():
    return os.getenv("HR_NOTIFY_EMAIL", os.getenv("EMAIL_ADDRESS", "antiai.hr@gmail.com"))


# =====================================================================
# HR SIDE — invite candidates, track the pipeline, activate accounts
# =====================================================================

@onboarding_bp.route("/", methods=["GET"])
@login_required
def pipeline():
    if not hr_admin_required():
        return redirect("/dashboard")

    conn, cur = None, None
    invitees = []
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
        cur.execute("""
            SELECT id, employee_code, full_name, email, department, designation,
                   onboarding_status, invited_at, submitted_at, activated_at,
                   onboarding_token_expires_at, offer_accepted
            FROM hrms_employees
            WHERE onboarding_status IS NOT NULL AND status != 'Deleted'
            ORDER BY invited_at DESC NULLS LAST
        """)
        invitees = cur.fetchall()
    except Exception as e:
        print("Error fetching onboarding pipeline via DB, trying REST fallback:", e)
        try:
            rows = supabase_rest.get_rows("hrms_employees", {
                "select": "id,employee_code,full_name,email,department,designation,"
                          "onboarding_status,invited_at,submitted_at,activated_at,"
                          "onboarding_token_expires_at,offer_accepted",
                "onboarding_status": "not.is.null",
                "status": "not.eq.Deleted",
                "order": "invited_at.desc",
            })
            invitees = rows or []
        except Exception as rest_err:
            print("REST fallback for onboarding pipeline failed:", rest_err)
    finally:
        if conn:
            release_db(conn, cur)

    for inv in invitees:
        exp = inv.get("onboarding_token_expires_at")
        if exp:
            if isinstance(exp, str):
                exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if exp.tzinfo:
                exp = exp.replace(tzinfo=None)
            inv["onboarding_token_expires_at"] = exp

    return render_template("hrms/onboarding_pipeline.html", invitees=invitees, now=datetime.utcnow())


@onboarding_bp.route("/invite/ui", methods=["GET"])
@login_required
def invite_ui():
    if not hr_admin_required():
        return redirect("/dashboard")

    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
        cur.execute("SELECT id, role_name FROM hrms_roles ORDER BY role_name")
        roles = cur.fetchall()
        cur.execute("""
            SELECT id, full_name, employee_code FROM hrms_employees
            WHERE status != 'Deleted' ORDER BY full_name
        """)
        managers = cur.fetchall()
    except Exception as e:
        print("Error fetching invite ui data, trying REST fallback:", e)
        roles = supabase_rest.list_roles()
        try:
            managers = supabase_rest.get_rows("hrms_employees", {
                "select": "id,full_name,employee_code",
                "status": "not.eq.Deleted",
                "order": "full_name.asc",
            })
        except Exception:
            managers = []
    finally:
        if conn:
            release_db(conn, cur)

    return render_template("hrms/onboarding_invite.html", roles=roles, managers=managers)


@onboarding_bp.route("/invite", methods=["POST"])
@login_required
def send_invite():
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403

    data = request.form
    required = ["full_name", "email", "role_id", "designation"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field.replace('_', ' ').title()} is required"}), 400

    token = _new_token()
    expires_at = datetime.utcnow() + timedelta(days=TOKEN_VALID_DAYS)
    joining_date = data.get("joining_date") or date.today()
    invited_by = session.get("employee_id")

    employee_id = None
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")

        cur.execute("SELECT id FROM hrms_employees WHERE email=%s AND status != 'Deleted'", (data["email"],))
        if cur.fetchone():
            release_db(conn, cur)
            return jsonify({"error": "An employee with this email already exists"}), 400

        employee_code = _next_employee_code(cur)

        cur.execute("""
            INSERT INTO hrms_employees
            (employee_code, full_name, email, department, designation, role_id,
             joining_date, status, manager_id, employment_type,
             onboarding_status, onboarding_token, onboarding_token_expires_at,
             invited_at, invited_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'Onboarding',%s,%s,'Invited',%s,%s,%s,%s)
            RETURNING id
        """, (
            employee_code, data["full_name"], data["email"], data.get("department"),
            data["designation"], data["role_id"], joining_date,
            data.get("manager_id") or None, data.get("employment_type", "Full Time"),
            token, expires_at, datetime.utcnow(), invited_by,
        ))
        employee_id = cur.fetchone()["id"]
        conn.commit()
    except Exception as e:
        print("Error creating onboarding invite via DB, trying REST fallback:", e)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            if supabase_rest.get_first_row("hrms_employees", {"select": "id", "email": f"eq.{data['email']}", "status": "not.eq.Deleted"}):
                return jsonify({"error": "An employee with this email already exists"}), 400
            fake_cur = type("C", (), {})()
            employee_code = supabase_rest.get_first_row("hrms_employees", {
                "select": "employee_code", "employee_code": "like.EMP-*", "order": "created_at.desc", "limit": 1
            })
            next_code = "EMP-0001"
            if employee_code and employee_code.get("employee_code"):
                try:
                    next_code = f"EMP-{(int(employee_code['employee_code'].split('-')[1]) + 1):04d}"
                except Exception:
                    pass
            row = supabase_rest.insert_row("hrms_employees", {
                "employee_code": next_code,
                "full_name": data["full_name"],
                "email": data["email"],
                "department": data.get("department"),
                "designation": data["designation"],
                "role_id": data["role_id"],
                "joining_date": str(joining_date),
                "status": "Onboarding",
                "manager_id": data.get("manager_id") or None,
                "employment_type": data.get("employment_type", "Full Time"),
                "onboarding_status": "Invited",
                "onboarding_token": token,
                "onboarding_token_expires_at": expires_at.isoformat(),
                "invited_at": datetime.utcnow().isoformat(),
                "invited_by": invited_by,
            })
            if not row:
                return jsonify({"error": "Could not create the onboarding invite. Check server logs."}), 500
            employee_id = row.get("id")
        except Exception as rest_err:
            print("REST fallback for onboarding invite failed:", rest_err)
            return jsonify({"error": f"Failed to create invite: {rest_err}"}), 500
    finally:
        if conn and cur:
            release_db(conn, cur)

    invite_url = url_for("onboarding_public.onboarding_form", token=token, _external=True)
    mailer.send_onboarding_invite(
        to_email=data["email"],
        candidate_name=data["full_name"],
        invite_url=invite_url,
        designation=data["designation"],
        department=data.get("department"),
        expires_display=expires_at.strftime("%d %b %Y"),
    )
    create_notification("HR", "invite_sent", f"Onboarding invite sent to {data['full_name']}", url_for("onboarding.pipeline"))

    return jsonify({"success": True, "redirect": "/hrms/onboarding/", "employee_id": employee_id})


@onboarding_bp.route("/<employee_id>/resend", methods=["POST"])
@login_required
def resend_invite(employee_id):
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403

    # "Resend" re-sends the SAME link whenever it's still valid, rather than
    # minting a new token every time — otherwise a candidate who still has an
    # earlier email open gets a dead link the moment HR clicks resend again.
    # A fresh token is only generated if the old one is missing/expired, or
    # if the candidate had already submitted and HR wants to re-open the form.
    conn, cur = None, None
    emp = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
        cur.execute("""
            SELECT full_name, email, designation, department, onboarding_status,
                   onboarding_token, onboarding_token_expires_at
            FROM hrms_employees
            WHERE id=%s AND onboarding_status != 'Active'
        """, (employee_id,))
        emp = cur.fetchone()

        if not emp:
            release_db(conn, cur)
            return jsonify({"error": "Employee not found or already active"}), 404

        existing_token = emp.get("onboarding_token")
        expires_at = emp.get("onboarding_token_expires_at")
        if expires_at and isinstance(expires_at, datetime) and expires_at.tzinfo:
            expires_at = expires_at.replace(tzinfo=None)

        needs_new_token = (
            not existing_token
            or not expires_at
            or datetime.utcnow() > expires_at
            or emp["onboarding_status"] == "Submitted"
        )

        if needs_new_token:
            token = _new_token()
            expires_at = datetime.utcnow() + timedelta(days=TOKEN_VALID_DAYS)
            cur.execute("""
                UPDATE hrms_employees
                SET onboarding_token=%s, onboarding_token_expires_at=%s,
                    invited_at=%s, onboarding_status='Invited'
                WHERE id=%s
            """, (token, expires_at, datetime.utcnow(), employee_id))
            conn.commit()
        else:
            token = existing_token

    except Exception as e:
        print("Error resending invite via DB, trying REST fallback:", e)
        try:
            row = supabase_rest.get_first_row("hrms_employees", {
                "select": "full_name,email,designation,department,onboarding_status,"
                          "onboarding_token,onboarding_token_expires_at",
                "id": f"eq.{employee_id}",
            })
            if not row:
                return jsonify({"error": "Employee not found or already active"}), 404
            emp = row
            existing_token = row.get("onboarding_token")
            expires_raw = row.get("onboarding_token_expires_at")
            expires_at = datetime.fromisoformat(expires_raw.replace("Z", "+00:00")).replace(tzinfo=None) if expires_raw else None
            needs_new_token = (not existing_token or not expires_at or datetime.utcnow() > expires_at
                               or row.get("onboarding_status") == "Submitted")
            if needs_new_token:
                token = _new_token()
                expires_at = datetime.utcnow() + timedelta(days=TOKEN_VALID_DAYS)
                supabase_rest.update_rows("hrms_employees", {"id": f"eq.{employee_id}"}, {
                    "onboarding_token": token,
                    "onboarding_token_expires_at": expires_at.isoformat(),
                    "invited_at": datetime.utcnow().isoformat(),
                    "onboarding_status": "Invited",
                })
            else:
                token = existing_token
        except Exception as rest_err:
            print("REST fallback for resend invite failed:", rest_err)
            return jsonify({"error": "Failed to resend invite"}), 500
    finally:
        if conn:
            release_db(conn, cur)

    if not emp:
        return jsonify({"error": "Employee not found or already active"}), 404

    invite_url = url_for("onboarding_public.onboarding_form", token=token, _external=True)
    mailer.send_onboarding_invite(
        to_email=emp["email"],
        candidate_name=emp["full_name"],
        invite_url=invite_url,
        designation=emp.get("designation"),
        department=emp.get("department"),
        expires_display=expires_at.strftime("%d %b %Y"),
    )
    create_notification("HR", "invite_sent", f"Onboarding invite resent to {emp['full_name']}", url_for("onboarding.pipeline"))
    return jsonify({"success": True})


@onboarding_bp.route("/<employee_id>/edit/ui", methods=["GET"])
@login_required
def edit_invite_ui(employee_id):
    if not hr_admin_required():
        return redirect("/dashboard")

    conn, cur = None, None
    emp, roles, managers = None, [], []
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
        cur.execute("""
            SELECT id, full_name, email, designation, department, role_id,
                   manager_id, employment_type, joining_date, onboarding_status
            FROM hrms_employees WHERE id=%s
        """, (employee_id,))
        emp = cur.fetchone()
        cur.execute("SELECT id, role_name FROM hrms_roles ORDER BY role_name")
        roles = cur.fetchall()
        cur.execute("""
            SELECT id, full_name, employee_code FROM hrms_employees
            WHERE status != 'Deleted' AND id != %s ORDER BY full_name
        """, (employee_id,))
        managers = cur.fetchall()
    except Exception as e:
        print("Error fetching invite edit data, trying REST fallback:", e)
        try:
            emp = supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{employee_id}"})
            roles = supabase_rest.list_roles()
            managers = supabase_rest.get_rows("hrms_employees", {
                "select": "id,full_name,employee_code", "status": "not.eq.Deleted", "order": "full_name.asc"
            })
        except Exception as rest_err:
            print("REST fallback for invite edit data failed:", rest_err)
    finally:
        if conn:
            release_db(conn, cur)

    if not emp or emp.get("onboarding_status") not in ("Invited", "Submitted"):
        flash("This candidate can no longer be edited from here.", "error")
        return redirect("/hrms/onboarding/")

    return render_template("hrms/onboarding_edit_invite.html", emp=emp, roles=roles, managers=managers)


@onboarding_bp.route("/<employee_id>/edit", methods=["POST"])
@login_required
def edit_invite(employee_id):
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403

    data = request.form
    for field in ("full_name", "email", "designation", "role_id"):
        if not data.get(field):
            return jsonify({"error": f"{field.replace('_', ' ').title()} is required"}), 400

    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")

        cur.execute("""
            SELECT id FROM hrms_employees
            WHERE email=%s AND id != %s AND status != 'Deleted'
        """, (data["email"], employee_id))
        if cur.fetchone():
            release_db(conn, cur)
            return jsonify({"error": "Another employee already uses this email"}), 400

        cur.execute("""
            UPDATE hrms_employees
            SET full_name=%s, email=%s, designation=%s, department=%s, role_id=%s,
                manager_id=%s, employment_type=%s, joining_date=%s
            WHERE id=%s AND onboarding_status IN ('Invited','Submitted')
        """, (
            data["full_name"], data["email"], data["designation"], data.get("department"),
            data["role_id"], data.get("manager_id") or None, data.get("employment_type", "Full Time"),
            data.get("joining_date") or None, employee_id,
        ))
        conn.commit()
    except Exception as e:
        print("Error editing invite via DB, trying REST fallback:", e)
        try:
            if supabase_rest.get_first_row("hrms_employees", {"select": "id", "email": f"eq.{data['email']}", "status": "not.eq.Deleted"}):
                pass  # best-effort — REST path can't easily exclude the current id server-side here
            supabase_rest.update_rows("hrms_employees", {"id": f"eq.{employee_id}"}, {
                "full_name": data["full_name"],
                "email": data["email"],
                "designation": data["designation"],
                "department": data.get("department"),
                "role_id": data["role_id"],
                "manager_id": data.get("manager_id") or None,
                "employment_type": data.get("employment_type", "Full Time"),
                "joining_date": data.get("joining_date") or None,
            })
        except Exception as rest_err:
            print("REST fallback for editing invite failed:", rest_err)
            return jsonify({"error": "Failed to save changes"}), 500
    finally:
        if conn:
            release_db(conn, cur)

    return jsonify({"success": True})


@onboarding_bp.route("/<employee_id>/delete", methods=["POST"])
@login_required
def delete_invite(employee_id):
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403

    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")

        cur.execute("SELECT onboarding_status FROM hrms_employees WHERE id=%s", (employee_id,))
        row = cur.fetchone()
        if not row:
            release_db(conn, cur)
            return jsonify({"error": "Candidate not found"}), 404
        if row["onboarding_status"] == "Active":
            release_db(conn, cur)
            return jsonify({"error": "This person is already an active employee — use Exit Management to remove them instead."}), 400

        # Clean up anything the candidate may have already submitted, then
        # the employee shell itself. All scoped to this one employee_id.
        for table in (
            "hrms_users", "employee_bank_details", "employee_compliance",
            "employee_documents", "employee_audit_logs", "employee_status_history",
            "employee_salary_components", "employee_salary",
        ):
            cur.execute(f"DELETE FROM {table} WHERE employee_id=%s", (employee_id,))

        cur.execute("DELETE FROM hrms_employees WHERE id=%s", (employee_id,))
        conn.commit()
    except Exception as e:
        print("Error deleting invite via DB, trying REST fallback:", e)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            for table in (
                "hrms_users", "employee_bank_details", "employee_compliance",
                "employee_documents", "employee_audit_logs", "employee_status_history",
                "employee_salary_components", "employee_salary",
            ):
                supabase_rest.delete_rows(table, {"employee_id": f"eq.{employee_id}"})
            supabase_rest.delete_rows("hrms_employees", {"id": f"eq.{employee_id}"})
        except Exception as rest_err:
            print("REST fallback for deleting invite failed:", rest_err)
            return jsonify({"error": "Failed to delete candidate"}), 500
    finally:
        if conn:
            release_db(conn, cur)

    return jsonify({"success": True})


@onboarding_bp.route("/<employee_id>/activate", methods=["POST"])
@login_required
def activate(employee_id):
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403

    conn, cur = None, None
    emp = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
        cur.execute("""
            UPDATE hrms_employees
            SET status='Active', onboarding_status='Active', activated_at=%s,
                onboarding_token=NULL
            WHERE id=%s AND onboarding_status='Submitted'
            RETURNING full_name, email, role_id
        """, (datetime.utcnow(), employee_id))
        emp = cur.fetchone()
        if emp and emp.get("role_id"):
            cur.execute("SELECT role_name FROM hrms_roles WHERE id=%s", (emp["role_id"],))
            role_row = cur.fetchone()
            emp["role_name"] = role_row["role_name"] if role_row else "Employee"

        if emp:
            cur.execute("SELECT * FROM employee_offers WHERE employee_id = %s ORDER BY created_at DESC LIMIT 1", (employee_id,))
            offer = cur.fetchone()
            if offer and offer.get("ctc_annual") and float(offer.get("ctc_annual")) > 0:
                annual_ctc = float(offer["ctc_annual"])
                cur.execute("DELETE FROM employee_salary WHERE employee_id = %s", (employee_id,))
                cur.execute("DELETE FROM employee_salary_components WHERE employee_id = %s", (employee_id,))
                cur.execute("""
                    INSERT INTO employee_salary (employee_id, annual_ctc, monthly_salary, effective_from)
                    VALUES (%s, %s, %s, %s)
                """, (employee_id, annual_ctc, annual_ctc / 12.0, datetime.utcnow().date()))
                components = [
                    ("Basic Salary", offer.get("basic_monthly")),
                    ("House Rent Allowance", offer.get("hra_monthly")),
                    ("Special Allowance", offer.get("special_allowance_monthly")),
                    ("Provident Fund", offer.get("pf_monthly")),
                    ("Performance Bonus", offer.get("bonus_monthly"))
                ]
                for c_name, m_amt in components:
                    m_amt = float(m_amt or 0)
                    if m_amt > 0:
                        cur.execute("""
                            INSERT INTO employee_salary_components (employee_id, component_name, yearly_amount, monthly_amount)
                            VALUES (%s, %s, %s, %s)
                        """, (employee_id, c_name, m_amt * 12.0, m_amt))
        conn.commit()
    except Exception as e:
        print("Error activating employee via DB, trying REST fallback:", e)
        try:
            row = supabase_rest.update_rows("hrms_employees", {"id": f"eq.{employee_id}"}, {
                "status": "Active",
                "onboarding_status": "Active",
                "activated_at": datetime.utcnow().isoformat(),
                "onboarding_token": None,
            })
            emp = row[0] if isinstance(row, list) and row else row
            if emp and emp.get("role_id"):
                role_row = supabase_rest.get_first_row("hrms_roles", {"id": f"eq.{emp['role_id']}"})
                emp["role_name"] = role_row["role_name"] if role_row else "Employee"

            offer = supabase_rest.get_first_row("employee_offers", {"employee_id": f"eq.{employee_id}", "order": "created_at.desc"})
            if offer and offer.get("ctc_annual") and float(offer.get("ctc_annual")) > 0:
                annual_ctc = float(offer["ctc_annual"])
                supabase_rest.delete_rows("employee_salary", {"employee_id": f"eq.{employee_id}"})
                supabase_rest.delete_rows("employee_salary_components", {"employee_id": f"eq.{employee_id}"})
                supabase_rest.insert_row("employee_salary", {
                    "employee_id": employee_id, "annual_ctc": annual_ctc, "monthly_salary": annual_ctc / 12.0, "effective_from": str(datetime.utcnow().date())
                })
                for c_name, key in [("Basic Salary", "basic_monthly"), ("House Rent Allowance", "hra_monthly"), ("Special Allowance", "special_allowance_monthly"), ("Provident Fund", "pf_monthly"), ("Performance Bonus", "bonus_monthly")]:
                    m_amt = float(offer.get(key) or 0)
                    if m_amt > 0:
                        supabase_rest.insert_row("employee_salary_components", {
                            "employee_id": employee_id, "component_name": c_name, "yearly_amount": m_amt * 12.0, "monthly_amount": m_amt
                        })
        except Exception as rest_err:
            print("REST fallback for activation failed:", rest_err)
    finally:
        if conn:
            release_db(conn, cur)

    if not emp:
        return jsonify({"error": "Employee not found, or not yet submitted by the candidate"}), 400

    login_url = url_for("login", role=emp.get("role_name", "Employee"), _external=True)
    mailer.send_activation_email(emp["email"], emp["full_name"], login_url)
    create_notification("HR", "onboarding_completed", f"Onboarding activated for {emp['full_name']}", url_for("employees.employees_ui"))

    return jsonify({"success": True})


# =====================================================================
# CANDIDATE SIDE — public, token-gated, no login required
# =====================================================================

def _lookup_by_token(token):
    conn, cur = None, None
    emp = None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
        cur.execute("SELECT * FROM hrms_employees WHERE onboarding_token=%s", (token,))
        emp = cur.fetchone()
    except Exception as e:
        print("Error looking up onboarding token via DB, trying REST fallback:", e)
        try:
            emp = supabase_rest.get_first_row("hrms_employees", {"onboarding_token": f"eq.{token}"})
        except Exception as rest_err:
            print("REST fallback for token lookup failed:", rest_err)
    finally:
        if conn:
            release_db(conn, cur)
    return emp


@onboarding_public_bp.route("/<token>", methods=["GET"])
def onboarding_form(token):
    emp = _lookup_by_token(token)
    if not emp:
        return render_template("onboarding_invalid.html", reason="not_found"), 404

    if emp.get("onboarding_status") == "Submitted":
        return render_template("onboarding_invalid.html", reason="already_submitted", employee=emp)
    if emp.get("onboarding_status") == "Active":
        return render_template("onboarding_invalid.html", reason="already_active", employee=emp)

    expires_at = emp.get("onboarding_token_expires_at")
    if expires_at:
        expiry_dt = expires_at if isinstance(expires_at, datetime) else datetime.fromisoformat(str(expires_at))
        if expiry_dt.tzinfo:
            expiry_dt = expiry_dt.replace(tzinfo=None)
        if datetime.utcnow() > expiry_dt:
            return render_template("onboarding_invalid.html", reason="expired", employee=emp)

    return render_template("onboarding_form.html", employee=emp, token=token)


@onboarding_public_bp.route("/<token>", methods=["POST"])
def onboarding_submit(token):
    emp = _lookup_by_token(token)
    if not emp or emp.get("onboarding_status") not in ("Invited",):
        flash("This onboarding link is no longer valid.", "error")
        return redirect(f"/onboarding/{token}")

    expires_at = emp.get("onboarding_token_expires_at")
    if expires_at:
        expiry_dt = expires_at if isinstance(expires_at, datetime) else datetime.fromisoformat(str(expires_at))
        if expiry_dt.tzinfo:
            expiry_dt = expiry_dt.replace(tzinfo=None)
        if datetime.utcnow() > expiry_dt:
            return render_template("onboarding_invalid.html", reason="expired", employee=emp)

    data = request.form
    files = request.files
    employee_id = emp["id"]

    required_fields = ["phone", "date_of_birth", "gender", "address",
                        "emergency_contact", "emergency_contact_number",
                        "bank_name", "account_number", "ifsc_code",
                        "password", "confirm_password"]
    for field in required_fields:
        if not data.get(field):
            flash(f"{field.replace('_', ' ').title()} is required.", "error")
            return redirect(f"/onboarding/{token}")

    if data["password"] != data["confirm_password"]:
        flash("Passwords do not match.", "error")
        return redirect(f"/onboarding/{token}")

    if len(data["password"]) < 8:
        flash("Password must be at least 8 characters.", "error")
        return redirect(f"/onboarding/{token}")

    # Documents are optional at this stage — HR can request specific ones
    # later via the Documents Hub if anything's still missing.

    if not data.get("offer_accepted"):
        flash("Please accept the offer terms to continue.", "error")
        return redirect(f"/onboarding/{token}")

    from hrms.employees.routes import upload_document_to_supabase

    hashed_password = generate_password_hash(data["password"])
    now = datetime.utcnow()

    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")

        cur.execute("""
            UPDATE hrms_employees
            SET phone=%s, gender=%s, date_of_birth=%s, office_location=%s, blood_group=%s,
                onboarding_status='Submitted', submitted_at=%s,
                offer_accepted=TRUE, offer_accepted_at=%s
            WHERE id=%s
        """, (
            data["phone"], data["gender"], data["date_of_birth"],
            data.get("office_location"), data.get("blood_group") or None, now, now, employee_id,
        ))

        cur.execute("""
            INSERT INTO hrms_users (email, password, role_id, employee_id)
            VALUES (%s,%s,%s,%s)
        """, (emp["email"], hashed_password, emp["role_id"], employee_id))

        cur.execute("""
            INSERT INTO employee_bank_details
            (employee_id, bank_name, account_number, ifsc_code, branch_name,
             address, emergency_contact, emergency_contact_number)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            employee_id, data["bank_name"], data["account_number"], data["ifsc_code"],
            data.get("branch_name"), data["address"],
            data.get("emergency_contact"), data.get("emergency_contact_number"),
        ))

        if any([data.get("pan_number"), data.get("aadhaar_number"), data.get("uan_number")]):
            cur.execute("""
                INSERT INTO employee_compliance (employee_id, pan_number, aadhaar_number, uan_number)
                VALUES (%s,%s,%s,%s)
            """, (employee_id, data.get("pan_number"), data.get("aadhaar_number"), data.get("uan_number")))

        doc_fields = [
            ("profile_photo", "Profile Photo"),
            ("doc_id_proof", "Government ID Proof"),
            ("doc_pan", "PAN Card"),
            ("doc_education", "Education Certificate"),
        ]
        for file_key, doc_title in doc_fields:
            doc_file = files.get(file_key)
            if doc_file and doc_file.filename:
                res = upload_document_to_supabase(doc_file, employee_id)
                if res:
                    if file_key == "profile_photo":
                        cur.execute("UPDATE hrms_employees SET profile_photo_url=%s WHERE id=%s",
                                    (res["public_url"], employee_id))
                    else:
                        cur.execute("""
                            INSERT INTO employee_documents
                            (employee_id, document_type, document_title, file_url, created_at, verification_status)
                            VALUES (%s,'Onboarding',%s,%s,%s,'Pending')
                        """, (employee_id, doc_title, res["public_url"], now))

        cur.execute("""
            INSERT INTO employee_audit_logs (employee_id, action, performed_by)
            VALUES (%s, 'Completed self-service onboarding', %s)
        """, (employee_id, employee_id))

        conn.commit()
    except Exception as e:
        print("Onboarding submission error:", e)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        flash("Something went wrong while saving your details. Please try again or contact HR.", "error")
        return redirect(f"/onboarding/{token}")
    finally:
        if conn:
            release_db(conn, cur)

    mailer.send_submission_ack_to_candidate(emp["email"], emp["full_name"])
    review_url = url_for("onboarding.pipeline", _external=True)
    mailer.send_submission_notice_to_hr(_hr_notify_email(), emp["full_name"], review_url)
    create_notification("HR", "onboarding_submitted", f"Candidate {emp['full_name']} submitted onboarding details", review_url)

    return render_template("onboarding_success.html", employee=emp)
