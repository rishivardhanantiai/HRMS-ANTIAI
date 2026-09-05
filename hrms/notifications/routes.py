from flask import Blueprint, jsonify, request, session, url_for
from datetime import datetime, timedelta
from utils.db import get_db, release_db

notifications_bp = Blueprint("notifications", __name__, url_prefix="/hrms/notifications")

@notifications_bp.route("/api/feed", methods=["GET"])
def get_feed():
    role = session.get("role")
    if role not in ["HR", "Admin", "Employee"]:
        return jsonify({"notifications": []})

    conn, cur = None, None
    notifications = []
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
            
        if role == "Employee":
            cur.execute("""
                SELECT id, type, message, link, read_at, created_at 
                FROM notifications 
                WHERE recipient_role = 'Employee' AND employee_id = %s 
                ORDER BY created_at DESC 
                LIMIT 20
            """, (session.get("employee_id"),))
        else:
            cur.execute("""
                SELECT id, type, message, link, read_at, created_at 
                FROM notifications 
                WHERE recipient_role = %s 
                ORDER BY created_at DESC 
                LIMIT 20
            """, (role,))
            
        rows = cur.fetchall()
        for r in rows:
            notifications.append({
                "id": str(r["id"]),
                "type": r["type"],
                "message": r["message"],
                "link": r["link"],
                "read_at": r["read_at"].isoformat() if r["read_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })
            
        # Admin aging alerts dynamically injected
        if role == "Admin":
            cur.execute("""
                SELECT COUNT(*) as count 
                FROM employee_offers 
                WHERE status = 'Pending Approval' 
                AND created_at < %s
            """, (datetime.utcnow() - timedelta(days=5),))
            row = cur.fetchone()
            aging_count = row["count"] if row else 0
            if aging_count > 0:
                notifications.insert(0, {
                    "id": "aging-alerts",
                    "type": "aging_alert",
                    "message": f"{aging_count} offers have been pending approval for 5+ days",
                    "link": url_for("offers.index"),
                    "read_at": None,
                    "created_at": datetime.utcnow().isoformat()
                })
                
    except Exception as e:
        print(f"Error fetching notifications: {e}")
    finally:
        if conn:
            release_db(conn, cur)
            
    return jsonify({"notifications": notifications})

@notifications_bp.route("/api/mark-read", methods=["POST"])
def mark_read():
    role = session.get("role")
    if role not in ["HR", "Admin", "Employee"]:
        return jsonify({"success": False}), 403
        
    data = request.json or {}
    notif_id = data.get("id")
    
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
            
        if notif_id and notif_id != "aging-alerts":
            if role == "Employee":
                cur.execute("UPDATE notifications SET read_at = %s WHERE id = %s AND recipient_role = 'Employee' AND employee_id = %s", (datetime.utcnow(), notif_id, session.get("employee_id")))
            else:
                cur.execute("UPDATE notifications SET read_at = %s WHERE id = %s AND recipient_role = %s", (datetime.utcnow(), notif_id, role))
        else:
            if role == "Employee":
                cur.execute("UPDATE notifications SET read_at = %s WHERE recipient_role = 'Employee' AND employee_id = %s AND read_at IS NULL", (datetime.utcnow(), session.get("employee_id")))
            else:
                cur.execute("UPDATE notifications SET read_at = %s WHERE recipient_role = %s AND read_at IS NULL", (datetime.utcnow(), role))
        conn.commit()
    except Exception as e:
        print(f"Error marking notification read: {e}")
        if conn:
            try: conn.rollback()
            except Exception: pass
        try:
            from utils import supabase_rest
            if notif_id and notif_id != "aging-alerts":
                supabase_rest.update_rows("notifications", {"id": f"eq.{notif_id}"}, {"read_at": datetime.utcnow().isoformat()})
            else:
                supabase_rest.update_rows("notifications", {"recipient_role": f"eq.{role}", "read_at": "is.null"}, {"read_at": datetime.utcnow().isoformat()})
        except Exception as rest_err:
            print("REST fallback for mark-read failed:", rest_err)
    finally:
        if conn:
            release_db(conn, cur)
            
    return jsonify({"success": True})

def create_notification(recipient_role, notif_type, message, link=None, employee_id=None):
    if recipient_role not in ["HR", "Admin", "Employee"]:
        return
        
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("""
                INSERT INTO notifications (recipient_role, type, message, link, employee_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (recipient_role, notif_type, message, link, employee_id))
            conn.commit()
    except Exception as e:
        print(f"DB Notification failed, trying REST: {e}")
        try:
            from utils.supabase_rest import insert_row
            insert_row("notifications", {
                "recipient_role": recipient_role,
                "type": notif_type,
                "message": message,
                "link": link,
                "employee_id": employee_id
            })
        except Exception as rest_e:
            print(f"REST Notification failed: {rest_e}")
    finally:
        if conn:
            release_db(conn, cur)
