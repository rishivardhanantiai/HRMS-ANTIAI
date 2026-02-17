from functools import wraps
from flask import session, redirect

def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not session.get("hr_logged_in"):
            return redirect("/")
        return f(*args, **kwargs)
    return wrap

from functools import wraps
from flask import session

def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if session.get("role") not in allowed_roles:
                return "Unauthorized", 403
            return f(*args, **kwargs)
        return wrapper
    return decorator
