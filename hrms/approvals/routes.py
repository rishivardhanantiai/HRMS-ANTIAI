from flask import Blueprint, render_template, request, jsonify, session, redirect
from datetime import datetime
import json
from utils.auth import login_required, role_required
from utils.db import get_db, release_db
from hrms.notifications.routes import create_notification
from hrms.offers.routes import _save_offer_template, _update_company_settings

approvals_bp = Blueprint("approvals", __name__, url_prefix="/hrms/approvals")

# ─────────────────────────────────────────────────────────────────────────────
# UTILITY: Create Approval Request  (DB → REST fallback)
# ─────────────────────────────────────────────────────────────────────────────
def create_approval_request(action_type, target_table, target_id, payload_before, payload_after, auto_approve=False):
    status = "Approved" if auto_approve else "Pending"
    resolved_by = session.get("user", "Admin") if auto_approve else None
    req_id = None

    # ── 1. Direct DB ──────────────────────────────────────────────────────────
    conn, cur = None, None
    db_success = False
    try:
        conn, cur = get_db(True)
        if conn:
            resolved_at = "NOW()" if auto_approve else "NULL"
            cur.execute(f"""
                INSERT INTO admin_approval_queue
                (action_type, target_table, target_id, payload_before, payload_after, requested_by, status, resolved_by, resolved_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, {resolved_at})
                RETURNING id
            """, (action_type, target_table, target_id,
                  json.dumps(payload_before), json.dumps(payload_after),
                  session.get("user", "HR"), status, resolved_by))
            req_id = cur.fetchone()["id"]
            conn.commit()
            db_success = True
    except Exception as e:
        print(f"[Approvals] DB insert failed, trying REST fallback: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            release_db(conn, cur)

    # ── 2. REST API Fallback ──────────────────────────────────────────────────
    if not db_success:
        try:
            from utils import supabase_rest
            payload = {
                "action_type": action_type,
                "target_table": target_table,
                "target_id": str(target_id) if target_id else None,
                "payload_before": json.dumps(payload_before),
                "payload_after": json.dumps(payload_after),
                "requested_by": session.get("user", "HR"),
                "status": status,
                "resolved_by": resolved_by,
            }
            if auto_approve:
                payload["resolved_at"] = datetime.utcnow().isoformat()
            row = supabase_rest.insert_row("admin_approval_queue", payload)
            if row:
                req_id = row.get("id")
                db_success = True
            else:
                print("[Approvals] REST insert returned None — approval not recorded.")
        except Exception as rest_err:
            print(f"[Approvals] REST fallback for create_approval_request failed: {rest_err}")

    if not db_success:
        return False

    # ── Post-insert: audit log + notification ─────────────────────────────────
    try:
        from utils.audit import log_action
        log_action(
            actor=session.get("email") or session.get("role") or "System",
            action="approval_request_created",
            target_table="admin_approval_queue",
            target_id=req_id,
            details={
                "action_type": action_type,
                "target_table": target_table,
                "target_id": str(target_id) if target_id else None,
                "auto_approved": auto_approve,
            },
        )
    except Exception as audit_err:
        print(f"[Approvals] Audit log failed (non-fatal): {audit_err}")

    if not auto_approve:
        try:
            action_names = {
                "template_edit": "Template edit",
                "appearance_change": "Appearance change",
                "company_settings_change": "Company settings change",
                "delete_offer": "Delete offer request",
                "bulk_send": "Bulk email send",
            }
            create_notification(
                "Admin", "approval_queue",
                f"{action_names.get(action_type, 'Action')} awaiting your review",
                "/hrms/approvals/",
            )
        except Exception as notif_err:
            print(f"[Approvals] Notification failed (non-fatal): {notif_err}")

    return True


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: Approvals Index  (DB → REST fallback)
# ─────────────────────────────────────────────────────────────────────────────
@approvals_bp.route("/")
@login_required
@role_required(["Admin"])
def index():
    pending = []
    history = []

    # ── 1. Direct DB ──────────────────────────────────────────────────────────
    conn, cur = None, None
    db_success = False
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("SELECT * FROM admin_approval_queue WHERE status = 'Pending' ORDER BY created_at ASC")
            pending = cur.fetchall() or []
            cur.execute("SELECT * FROM admin_approval_queue WHERE status != 'Pending' ORDER BY resolved_at DESC LIMIT 50")
            history = cur.fetchall() or []
            db_success = True
    except Exception as e:
        print(f"[Approvals] DB fetch failed, trying REST fallback: {e}")
    finally:
        if conn:
            release_db(conn, cur)

    # ── 2. REST API Fallback ──────────────────────────────────────────────────
    if not db_success:
        try:
            from utils import supabase_rest
            pending = supabase_rest.get_rows(
                "admin_approval_queue",
                {"status": "eq.Pending", "order": "created_at.asc"}
            ) or []
            history = supabase_rest.get_rows(
                "admin_approval_queue",
                {"status": "neq.Pending", "order": "resolved_at.desc", "limit": "50"}
            ) or []
        except Exception as rest_err:
            print(f"[Approvals] REST fallback for index failed: {rest_err}")

    return render_template("hrms/approvals.html", pending=pending, history=history)


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: Review UI  (DB → REST fallback)
# ─────────────────────────────────────────────────────────────────────────────
@approvals_bp.route("/<req_id>/review")
@login_required
@role_required(["Admin"])
def review_ui(req_id):
    req = None

    # ── 1. Direct DB ──────────────────────────────────────────────────────────
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("SELECT * FROM admin_approval_queue WHERE id = %s", (req_id,))
            req = cur.fetchone()
    except Exception as e:
        print(f"[Approvals] DB fetch for review_ui failed, trying REST fallback: {e}")
    finally:
        if conn:
            release_db(conn, cur)

    # ── 2. REST API Fallback ──────────────────────────────────────────────────
    if not req:
        try:
            from utils import supabase_rest
            req = supabase_rest.get_first_row(
                "admin_approval_queue", {"id": f"eq.{req_id}"}
            )
        except Exception as rest_err:
            print(f"[Approvals] REST fallback for review_ui failed: {rest_err}")

    if not req:
        return redirect("/hrms/approvals/")

    return render_template("hrms/approval_review.html", req=req)


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: Resolve Request  (DB → REST fallback, including action execution)
# ─────────────────────────────────────────────────────────────────────────────
@approvals_bp.route("/<req_id>/resolve", methods=["POST"])
@login_required
@role_required(["Admin"])
def resolve_request(req_id):
    data = request.json or {}
    status = data.get("status")
    comment = data.get("comment", "")

    if status not in ["Approved", "Rejected"]:
        return jsonify({"error": "Invalid status"}), 400
    if status == "Rejected" and not comment.strip():
        return jsonify({"error": "Comment is required when rejecting."}), 400

    req = None

    # ── 1. Fetch the pending request (DB → REST) ───────────────────────────────
    conn, cur = None, None
    using_db = False
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("SELECT * FROM admin_approval_queue WHERE id = %s", (req_id,))
            req = cur.fetchone()
            using_db = True
    except Exception as e:
        print(f"[Approvals] DB fetch in resolve_request failed, trying REST: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        # Don't release yet — we may still need conn for the action below
        if conn:
            release_db(conn, cur)
            conn, cur = None, None

    if not req and not using_db:
        try:
            from utils import supabase_rest
            req = supabase_rest.get_first_row(
                "admin_approval_queue", {"id": f"eq.{req_id}"}
            )
        except Exception as rest_err:
            print(f"[Approvals] REST fallback for fetch in resolve_request failed: {rest_err}")

    if not req:
        if conn:
            release_db(conn, cur)
        return jsonify({"error": "Request not found or database unavailable."}), 404

    # Normalise: RealDictRow or plain dict both support .get()
    req_dict = dict(req)
    if req_dict.get("status") != "Pending":
        if conn:
            release_db(conn, cur)
        return jsonify({"error": "Request not found or already resolved."}), 404

    # Decode JSON strings coming from REST (DB returns parsed dicts already)
    def _decode(val):
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return val
        return val

    payload_before = _decode(req_dict.get("payload_before"))
    payload_after = _decode(req_dict.get("payload_after"))
    action_type = req_dict.get("action_type")

    # ── 2. Execute the approved action (DB → REST per action) ─────────────────
    if status == "Approved":
        try:
            if action_type == "template_edit":
                _save_offer_template(req_dict["target_id"], payload_after["content"])

            elif action_type in ("appearance_change", "company_settings_change"):
                _update_company_settings(payload_after)

            elif action_type == "delete_offer":
                _executed = False
                # Try direct DB first
                if using_db and conn:
                    try:
                        cur.execute("DELETE FROM employee_offers WHERE id=%s", (req_dict["target_id"],))
                        if payload_before and "employee_id" in payload_before:
                            cur.execute(
                                "DELETE FROM hrms_employees WHERE id=%s AND status='Offer Pending'",
                                (payload_before["employee_id"],),
                            )
                        _executed = True
                    except Exception as del_e:
                        print(f"[Approvals] DB delete_offer failed: {del_e}")
                # REST fallback
                if not _executed:
                    from utils import supabase_rest
                    supabase_rest.delete_rows("employee_offers", {"id": f"eq.{req_dict['target_id']}"})
                    if payload_before and "employee_id" in payload_before:
                        supabase_rest.delete_rows(
                            "hrms_employees",
                            {"id": f"eq.{payload_before['employee_id']}", "status": "eq.Offer Pending"},
                        )

            elif action_type == "delete_candidate":
                _executed = False
                if using_db and conn:
                    try:
                        cur.execute("DELETE FROM applications WHERE id=%s", (req_dict["target_id"],))
                        _executed = True
                    except Exception as del_e:
                        print(f"[Approvals] DB delete_candidate failed: {del_e}")
                if not _executed:
                    from utils import supabase_rest
                    supabase_rest.delete_rows("applications", {"id": f"eq.{req_dict['target_id']}"})

            elif action_type == "bulk_send":
                subject = payload_after.get("subject")
                body_html = payload_after.get("body_html")
                recipients = payload_after.get("recipients", [])
                requested_by = req_dict.get("requested_by", session.get("user"))
                _executed = False
                if using_db and conn:
                    try:
                        for rcpt in recipients:
                            personalized_body = (
                                body_html
                                .replace("{{candidate_name}}", rcpt["name"])
                                .replace("{{employee_name}}", rcpt["name"])
                            )
                            cur.execute("""
                                INSERT INTO outbound_messages (subject, body_html, recipient_email, status, created_by)
                                VALUES (%s, %s, %s, 'Queued', %s)
                            """, (subject, personalized_body, rcpt["email"], requested_by))
                        _executed = True
                    except Exception as bulk_e:
                        print(f"[Approvals] DB bulk_send insert failed: {bulk_e}")
                if not _executed:
                    from utils import supabase_rest
                    for rcpt in recipients:
                        personalized_body = (
                            body_html
                            .replace("{{candidate_name}}", rcpt["name"])
                            .replace("{{employee_name}}", rcpt["name"])
                        )
                        supabase_rest.insert_row("outbound_messages", {
                            "subject": subject,
                            "body_html": personalized_body,
                            "recipient_email": rcpt["email"],
                            "status": "Queued",
                            "created_by": requested_by,
                        })
            else:
                raise Exception(f"Unknown action_type {action_type}")

        except Exception as action_e:
            print(f"[Approvals] Failed to execute action {action_type}: {action_e}")
            if conn:
                release_db(conn, cur)
            return jsonify({"error": "Failed to execute the requested action. See logs."}), 500

    # ── 3. Mark request as resolved (DB → REST) ────────────────────────────────
    resolved_ok = False
    if using_db and conn:
        try:
            cur.execute("""
                UPDATE admin_approval_queue
                SET status = %s, admin_comment = %s, resolved_by = %s, resolved_at = NOW()
                WHERE id = %s
            """, (status, comment, session.get("user", "Admin"), req_id))
            conn.commit()
            resolved_ok = True
        except Exception as upd_e:
            print(f"[Approvals] DB update for resolve failed: {upd_e}")
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            release_db(conn, cur)
            conn, cur = None, None

    if not resolved_ok:
        try:
            from utils import supabase_rest
            supabase_rest.update_rows(
                "admin_approval_queue",
                {"id": f"eq.{req_id}"},
                {
                    "status": status,
                    "admin_comment": comment,
                    "resolved_by": session.get("user", "Admin"),
                    "resolved_at": datetime.utcnow().isoformat(),
                },
            )
            resolved_ok = True
        except Exception as rest_upd_err:
            print(f"[Approvals] REST fallback for resolve update failed: {rest_upd_err}")

    if not resolved_ok:
        return jsonify({"error": "Failed to update approval status. See logs."}), 500

    # ── 4. Audit log + notification (non-fatal) ────────────────────────────────
    try:
        from utils.audit import log_action
        log_action(
            actor=session.get("email") or session.get("role") or "Admin",
            action=f"approval_{status.lower()}",
            target_table="admin_approval_queue",
            target_id=req_id,
            details={
                "action_type": action_type,
                "target_table": req_dict.get("target_table"),
                "target_id": str(req_dict.get("target_id")) if req_dict.get("target_id") else None,
                "requested_by": req_dict.get("requested_by"),
            },
        )
    except Exception as audit_err:
        print(f"[Approvals] Audit log failed (non-fatal): {audit_err}")

    try:
        action_names = {
            "template_edit": "Template edit",
            "appearance_change": "Appearance change",
            "company_settings_change": "Company settings change",
            "delete_offer": "Delete offer request",
            "bulk_send": "Bulk announcement send",
        }
        notif_msg = f"Your {action_names.get(action_type, 'action')} was {status.lower()}"
        if status == "Rejected":
            notif_msg += f" — {comment}"
        create_notification("HR", "queue_resolved", notif_msg)
    except Exception as notif_err:
        print(f"[Approvals] Notification failed (non-fatal): {notif_err}")

    return jsonify({"success": True})
