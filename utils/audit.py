import json
import uuid
from utils.db import get_db, release_db

def log_action(actor, action, target_table=None, target_id=None, details=None):
    """
    Log a system event to the audit_log table.
    - actor: username, email or role of the actor performing the action.
    - action: string descriptor of the action (e.g., 'login', 'offer_sent').
    - target_table: name of the DB table affected (optional).
    - target_id: UUID of the row affected (optional).
    - details: dict/JSON payload of extra info (optional).
    """
    conn, cur = None, None
    valid_uuid = None
    if target_id:
        try:
            valid_uuid = str(uuid.UUID(str(target_id)))
        except (ValueError, TypeError):
            pass
            
    details_json = None
    if details is not None:
        if isinstance(details, (dict, list)):
            details_json = json.dumps(details)
        else:
            details_json = str(details)

    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("No DB connection available")
            
        cur.execute("""
            INSERT INTO audit_log (actor, action, target_table, target_id, details)
            VALUES (%s, %s, %s, %s, %s)
        """, (actor or 'System', action, target_table, valid_uuid, details_json))
        conn.commit()
    except Exception as e:
        print(f"Error writing to audit_log via DB, trying REST fallback: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            from utils import supabase_rest
            supabase_rest.insert_row("audit_log", {
                "actor": actor or 'System',
                "action": action,
                "target_table": target_table,
                "target_id": valid_uuid,
                "details": details_json
            })
        except Exception as rest_err:
            print(f"REST fallback for audit_log failed: {rest_err}")
    finally:
        if conn:
            release_db(conn, cur)

