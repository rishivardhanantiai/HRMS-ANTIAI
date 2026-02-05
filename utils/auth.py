from functools import wraps
from flask import session, redirect

def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not session.get("hr_logged_in"):
            return redirect("/")
        return f(*args, **kwargs)
    return wrap
