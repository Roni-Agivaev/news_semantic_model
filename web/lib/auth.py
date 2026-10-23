"""
Single-password login for the dashboard.

The password lives in the DASHBOARD_PASSWORD env var. Logging in sets an
HttpOnly cookie holding an HMAC derived from that password, so changing the
password signs out every device. Without DASHBOARD_PASSWORD set, nobody can log in.
"""
import hashlib
import hmac
import os
from http.cookies import SimpleCookie

COOKIE_NAME = "dash_session"
MAX_AGE = 365 * 24 * 3600  # stay signed in for a year


def _password():
    return os.environ.get("DASHBOARD_PASSWORD", "")


def _session_token():
    return hmac.new(_password().encode(), b"dashboard-session-v1", hashlib.sha256).hexdigest()


def check_password(given):
    pw = _password()
    return bool(pw) and hmac.compare_digest((given or "").encode(), pw.encode())


def is_logged_in(headers):
    if not _password():
        return False
    cookie = SimpleCookie(headers.get("Cookie", ""))
    value = cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else ""
    return hmac.compare_digest(value, _session_token())


def login_cookie():
    return f"{COOKIE_NAME}={_session_token()}; Path=/; Max-Age={MAX_AGE}; HttpOnly; Secure; SameSite=Lax"


def logout_cookie():
    return f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax"
