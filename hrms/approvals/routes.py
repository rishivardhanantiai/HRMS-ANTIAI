from flask import Blueprint, render_template, request, jsonify, session, redirect
from datetime import datetime
import json
from utils.auth import login_required, role_required
from utils.db import get_db, release_db
from hrms.notifications.routes import create_notification
from hrms.offers.routes import _save_offer_template, _update_company_settings

approvals_bp = Blueprint("approvals", __name__, url_prefix="/hrms/approvals")

def create_approval_request(action_type, target_table, target_id, payload_before, payload_after):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
            
        cur.execute("""
            INSERT INTO admin_approval_queue 
            (action_type, target_table, target_id, payload_before, payload_after, requested_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (action_type, target_table, target_id, json.dumps(payload_before), json.dumps(payload_after), session.get("user", "HR")))
        
        req_id = cur.fetchone()["id"]
        conn.commit()
        
        # Notify Admin
        action_names = {
            "template_edit": "Template edit",
            "appearance_change": "Appearance change",
            "delete_offer": "Delete offer request"
        }
        create_notification("Admin", "approval_queue", f"{action_names.get(action_type, 'Action')} awaiting your review", "/hrms/approvals/")
        return True
    except Exception as e:
        print(f"Error creating approval request: {e}")
        return False
    finally:
        if conn:
            release_db(conn, cur)

@approvals_bp.route("/")
@login_required
@role_required(["Admin"])
def index():
    conn, cur = None, None
    pending = []
    history = []
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("SELECT * FROM admin_approval_queue WHERE status = 'Pending' ORDER BY created_at ASC")
            pending = cur.fetchall()
            
            cur.execute("SELECT * FROM admin_approval_queue WHERE status != 'Pending' ORDER BY resolved_at DESC LIMIT 50")
            history = cur.fetchall()
    except Exception as e:
        print("Error fetching approval queue:", e)
    finally:
        if conn:
            release_db(conn, cur)
            
    return render_template("hrms/approvals.html", pending=pending, history=history)

@approvals_bp.route("/<req_id>/review")
@login_required
@role_required(["Admin"])
def review_ui(req_id):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("SELECT * FROM admin_approval_queue WHERE id = %s", (req_id,))
        req = cur.fetchone()
        if not req:
            return redirect("/hrms/approvals/")
        return render_template("hrms/approval_review.html", req=req)
    except Exception as e:
        print("Error fetching approval request:", e)
        return redirect("/hrms/approvals/")
    finally:
        if conn:
            release_db(conn, cur)

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
        
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
            
        cur.execute("SELECT * FROM admin_approval_queue WHERE id = %s", (req_id,))
        req = cur.fetchone()
        if not req or req["status"] != "Pending":
            return jsonify({"error": "Request not found or already resolved."}), 404
            
        # If approved, execute the underlying action
        if status == "Approved":
            try:
                if req["action_type"] == "template_edit":
                    _save_offer_template(req["target_id"], req["payload_after"]["content"])
                elif req["action_type"] == "appearance_change":
                    _update_company_settings(req["payload_after"])
                elif req["action_type"] == "delete_offer":
                    # Delete the offer
                    cur.execute("DELETE FROM employee_offers WHERE id=%s", (req["target_id"],))
                    if req["payload_before"] and "employee_id" in req["payload_before"]:
                        cur.execute("DELETE FROM hrms_employees WHERE id=%s AND status='Offer Pending'", (req["payload_before"]["employee_id"],))
                else:
                    raise Exception(f"Unknown action_type {req['action_type']}")
            except Exception as action_e:
                print(f"Failed to execute action {req['action_type']}: {action_e}")
                return jsonify({"error": "Failed to execute the requested action. See logs."}), 500
                
        # Update the queue
        cur.execute("""
            UPDATE admin_approval_queue 
            SET status = %s, admin_comment = %s, resolved_by = %s, resolved_at = NOW() 
            WHERE id = %s
        """, (status, comment, session.get("user", "Admin"), req_id))
        
        conn.commit()
        
        # Notify HR
        action_names = {
            "template_edit": "Template edit",
            "appearance_change": "Appearance change",
            "delete_offer": "Delete offer request"
        }
        notif_msg = f"Your {action_names.get(req['action_type'], 'action')} was {status.lower()}"
        if status == "Rejected":
            notif_msg += f" — {comment}"
        create_notification("HR", "queue_resolved", notif_msg)
        
        return jsonify({"success": True})
        
    except Exception as e:
        print(f"Error resolving approval request: {e}")
        return jsonify({"error": "Server error"}), 500
    finally:
        if conn:
            release_db(conn, cur)
