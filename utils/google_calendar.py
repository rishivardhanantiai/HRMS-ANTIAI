import os
# Only allow insecure HTTP transport in local dev — never in production
if not os.getenv("VERCEL") and os.getenv("FLASK_ENV", "development") != "production":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
import json
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from utils.encryption import encrypt_token, decrypt_token
from utils.db import get_db, release_db

SECRETS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "utils", "client_secrets.json")
SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_oauth_flow(redirect_uri=None):
    env_secrets = os.getenv("GOOGLE_CLIENT_SECRETS_JSON")
    if env_secrets:
        try:
            client_config = json.loads(env_secrets)
            return Flow.from_client_config(
                client_config,
                scopes=SCOPES,
                redirect_uri=redirect_uri,
                autogenerate_code_verifier=False
            )
        except Exception as e:
            print("Error loading Google OAuth flow from environment variable GOOGLE_CLIENT_SECRETS_JSON:", e)
            
    if not os.path.exists(SECRETS_PATH):
        raise FileNotFoundError(f"Google OAuth client_secrets.json not found at {SECRETS_PATH} and GOOGLE_CLIENT_SECRETS_JSON environment variable is not set")
    flow = Flow.from_client_secrets_file(
        SECRETS_PATH,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False
    )
    return flow

def save_credentials(user_email, credentials):
    """Encrypts and stores OAuth credentials in the database."""
    token_dict = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    encrypted_data = encrypt_token(json.dumps(token_dict))
    
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("""
                INSERT INTO google_calendar_tokens (user_email, token_data, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (user_email) DO UPDATE 
                SET token_data = EXCLUDED.token_data, updated_at = now()
            """, (user_email, encrypted_data))
            conn.commit()
    finally:
        if conn:
            release_db(conn, cur)

def get_credentials(user_email):
    """Retrieves and decrypts OAuth credentials from the database."""
    conn, cur = None, None
    encrypted_data = None
    try:
        conn, cur = get_db(True)
        if conn:
            # Query for the requested user
            cur.execute("SELECT token_data FROM google_calendar_tokens WHERE user_email = %s", (user_email,))
            row = cur.fetchone()
            if row:
                encrypted_data = row['token_data']
    finally:
        if conn:
            release_db(conn, cur)
            
    if not encrypted_data:
        # Fallback: grab any connected token if specific email isn't configured (shared HR calendar case)
        try:
            conn, cur = get_db(True)
            if conn:
                cur.execute("SELECT token_data FROM google_calendar_tokens LIMIT 1")
                row = cur.fetchone()
                if row:
                    encrypted_data = row['token_data']
        finally:
            if conn:
                release_db(conn, cur)
                
    if not encrypted_data:
        return None
        
    try:
        decrypted_json = decrypt_token(encrypted_data)
        token_dict = json.loads(decrypted_json)
        creds = Credentials(
            token=token_dict.get('token'),
            refresh_token=token_dict.get('refresh_token'),
            token_uri=token_dict.get('token_uri'),
            client_id=token_dict.get('client_id'),
            client_secret=token_dict.get('client_secret'),
            scopes=token_dict.get('scopes')
        )
        # Auto refresh if expired
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save refreshed credentials
            save_credentials(user_email, creds)
        return creds
    except Exception as e:
        print(f"Error loading credentials: {e}")
        return None

def delete_credentials(user_email):
    """Deletes credentials from database."""
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("DELETE FROM google_calendar_tokens WHERE user_email = %s", (user_email,))
            conn.commit()
    finally:
        if conn:
            release_db(conn, cur)

def get_calendar_service(user_email):
    creds = get_credentials(user_email)
    if not creds:
        return None
    try:
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f"Error building Google Calendar service: {e}")
        return None

def sync_calendar_event(user_email, summary, description, start_time, end_time, attendees, event_id=None):
    """Creates or updates a Google Calendar event.
    Returns the google event_id on success, or None on failure.
    """
    service = get_calendar_service(user_email)
    if not service:
        print("Calendar service not available.")
        return None
        
    event_body = {
        'summary': summary,
        'description': description,
        'start': {
            'dateTime': start_time.isoformat(),
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': end_time.isoformat(),
            'timeZone': 'UTC',
        },
        'attendees': [{'email': email} for email in attendees],
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'email', 'minutes': 24 * 60},
                {'method': 'popup', 'minutes': 30},
            ],
        },
    }
    
    try:
        if event_id:
            event = service.events().update(
                calendarId='primary',
                eventId=event_id,
                body=event_body,
                sendUpdates='all'
            ).execute()
        else:
            event = service.events().insert(
                calendarId='primary',
                body=event_body,
                sendUpdates='all'
            ).execute()
        return event.get('id')
    except Exception as e:
        print(f"Error syncing Google Calendar event: {e}")
        return None

def cancel_calendar_event(user_email, event_id):
    """Deletes a Google Calendar event."""
    if not event_id:
        return False
    service = get_calendar_service(user_email)
    if not service:
        return False
    try:
        service.events().delete(
            calendarId='primary',
            eventId=event_id,
            sendUpdates='all'
        ).execute()
        return True
    except Exception as e:
        print(f"Error deleting Google Calendar event: {e}")
        return False
