"""
Lightweight transactional email helper for HRMS.

Uses Gmail's free SMTP relay (smtp.gmail.com:587) with an App Password —
no paid email service needed. Configure these in your .env:

    EMAIL_ADDRESS=antiai.hr@gmail.com
    EMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx   # Gmail "App Password", not your normal password
    EMAIL_SENDER_NAME=Anti AI HR Team
    COMPANY_NAME=Anti AI

How to get a Gmail App Password (free, 2 minutes):
  1. Turn on 2-Step Verification on the antiai.hr@gmail.com account
     (Google Account -> Security -> 2-Step Verification).
  2. Google Account -> Security -> App Passwords -> generate one for "Mail".
  3. Paste the 16-character password into EMAIL_APP_PASSWORD in .env
     (and in your host's environment variables in production).

If EMAIL_APP_PASSWORD isn't set yet, emails are not sent — instead the
subject/recipient/link are printed to the server log so the flow still
works end-to-end during development.
"""

import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

COMPANY_NAME = os.getenv("COMPANY_NAME", "Anti AI")
SENDER_EMAIL = os.getenv("EMAIL_ADDRESS", "antiai.hr@gmail.com")
SENDER_NAME = os.getenv("EMAIL_SENDER_NAME", f"{COMPANY_NAME} HR Team")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

BRAND_COLOR = "#3b82f6"
BRAND_DARK = "#020617"


def _logo_path():
    from flask import current_app
    path = os.path.join(current_app.root_path, "static", "images", "logo.png")
    return path if os.path.exists(path) else None


def _wrap_html(title, preheader, body_html, footer_note=None):
    """Wrap inner body HTML in a branded, dark, email-client-safe shell."""
    footer_note = footer_note or (
        "This is an automated message from the HR team. "
        "Please do not reply directly to this email."
    )
    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 10px 30px rgba(15,23,42,0.08);">

<tr>
<td style="background:linear-gradient(135deg,{BRAND_DARK},#0b1220);padding:28px 32px;text-align:center;">
<img src="cid:company_logo" alt="{COMPANY_NAME}" width="52" style="display:block;margin:0 auto 10px;border-radius:8px;">
<div style="color:#ffffff;font-size:15px;font-weight:700;letter-spacing:0.5px;">{COMPANY_NAME} &middot; Human Resources</div>
</td>
</tr>

<tr>
<td style="padding:34px 32px 8px;">
<h1 style="margin:0 0 6px;color:#0f172a;font-size:21px;font-weight:700;">{title}</h1>
</td>
</tr>

<tr>
<td style="padding:0 32px 30px;color:#334155;font-size:14.5px;line-height:1.65;">
{body_html}
</td>
</tr>

<tr>
<td style="padding:20px 32px 28px;border-top:1px solid #e2e8f0;color:#94a3b8;font-size:12px;line-height:1.6;">
{footer_note}<br>
&copy; {COMPANY_NAME}. All rights reserved.
</td>
</tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _button(label, url):
    return f"""\
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:22px 0;">
<tr><td style="border-radius:9px;background:{BRAND_COLOR};">
<a href="{url}" target="_blank"
   style="display:inline-block;padding:13px 26px;color:#ffffff;text-decoration:none;
          font-size:14.5px;font-weight:600;border-radius:9px;">{label}</a>
</td></tr>
</table>
<p style="margin:0 0 4px;font-size:12.5px;color:#94a3b8;">
If the button doesn't work, copy this link into your browser:<br>
<a href="{url}" style="color:{BRAND_COLOR};word-break:break-all;">{url}</a>
</p>"""


def send_email(to_email, subject, html_body, to_name=None):
    """Send one HTML email with the company logo inlined. Returns True/False."""
    app_password = os.getenv("EMAIL_APP_PASSWORD", "").strip()

    if not app_password:
        print("--- EMAIL NOT SENT (EMAIL_APP_PASSWORD not configured) ---")
        print(f"To: {to_name or ''} <{to_email}>")
        print(f"Subject: {subject}")
        print("--------------------------------------------------------")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((SENDER_NAME, SENDER_EMAIL))
    msg["To"] = formataddr((to_name, to_email)) if to_name else to_email
    msg.set_content("This email requires an HTML-capable email client to view.")
    msg.add_alternative(html_body, subtype="html")

    logo_path = _logo_path()
    if logo_path:
        html_part = msg.get_payload()[-1]
        with open(logo_path, "rb") as f:
            html_part.add_related(f.read(), maintype="image", subtype="png", cid="<company_logo>")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SENDER_EMAIL, app_password)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Email send failed ({to_email}): {e}")
        return False


# =====================================================================
# TRANSACTIONAL EMAILS
# =====================================================================

def send_onboarding_invite(to_email, candidate_name, invite_url, designation, department, expires_display):
    body = f"""\
<p>Hi {candidate_name},</p>
<p>Welcome aboard! We're excited to have you join {COMPANY_NAME} as
<strong>{designation}</strong>{f" in {department}" if department else ""}.</p>
<p>To get you set up, please complete your onboarding using the secure link below.
It only takes a few minutes and covers:</p>
<ul style="margin:10px 0 18px;padding-left:20px;">
<li>Your personal, emergency contact &amp; bank details</li>
<li>Setting your own HRMS login password</li>
<li>Optionally, your resume and ID documents (you can also add these later)</li>
</ul>
{_button("Start My Onboarding", invite_url)}
<p style="font-size:13px;color:#64748b;">This link is unique to you and expires on
<strong>{expires_display}</strong>. Please don't forward it to anyone else.</p>
<p>Looking forward to having you on the team!</p>
"""
    html = _wrap_html(
        title="You're invited to complete your onboarding",
        preheader=f"Complete your onboarding at {COMPANY_NAME}",
        body_html=body,
    )
    return send_email(to_email, f"Welcome to {COMPANY_NAME} — Complete Your Onboarding", html, to_name=candidate_name)


def send_submission_notice_to_hr(hr_email, candidate_name, review_url):
    body = f"""\
<p>Hi Team,</p>
<p><strong>{candidate_name}</strong> has just completed the self-onboarding form and
uploaded their documents. Their profile is now waiting on HR verification before
their account is activated.</p>
{_button("Review Submission", review_url)}
"""
    html = _wrap_html(
        title="New onboarding submission awaiting review",
        preheader=f"{candidate_name} submitted their onboarding details",
        body_html=body,
    )
    return send_email(hr_email, f"Onboarding submitted: {candidate_name}", html)


def send_submission_ack_to_candidate(to_email, candidate_name):
    body = f"""\
<p>Hi {candidate_name},</p>
<p>Thanks — we've received your onboarding details and documents. Our HR team will
verify everything and activate your account shortly. You'll get a confirmation
email the moment you're all set to log in.</p>
<p>If anything needs correcting, we'll reach out to you directly.</p>
"""
    html = _wrap_html(
        title="We've received your onboarding details",
        preheader="Your submission is under review",
        body_html=body,
    )
    return send_email(to_email, "We've received your onboarding details", html, to_name=candidate_name)


def send_activation_email(to_email, candidate_name, login_url):
    body = f"""\
<p>Hi {candidate_name},</p>
<p>Good news — your documents have been verified and your {COMPANY_NAME} HRMS
account is now <strong>active</strong>. You can log in any time using the email
and password you set during onboarding.</p>
{_button("Go to Login", login_url)}
<p>Welcome to the team — we're glad to have you here.</p>
"""
    html = _wrap_html(
        title="Your account is active — welcome to " + COMPANY_NAME,
        preheader="Your HRMS account has been activated",
        body_html=body,
    )
    return send_email(to_email, f"You're all set — Welcome to {COMPANY_NAME}!", html, to_name=candidate_name)


# =====================================================================
# OFFER LETTER / NDA / E-SIGN WORKFLOW EMAILS
# =====================================================================

def send_offer_for_approval(admin_email, candidate_name, designation, review_url, hr_name=None):
    body = f"""\
<p>Hi,</p>
<p>{hr_name or "HR"} has drafted an offer letter for <strong>{candidate_name}</strong>
({designation}) and it's waiting on your approval before it goes out for signature.</p>
{_button("Review Offer", review_url)}
"""
    html = _wrap_html(
        title="Offer letter awaiting your approval",
        preheader=f"Offer for {candidate_name} needs review",
        body_html=body,
    )
    return send_email(admin_email, f"Approval needed: Offer for {candidate_name}", html)


def send_offer_changes_requested(hr_email, candidate_name, comments, edit_url):
    body = f"""\
<p>Hi,</p>
<p>The offer letter for <strong>{candidate_name}</strong> needs a few changes before it can be approved:</p>
<blockquote style="margin:14px 0;padding:10px 16px;background:#f8fafc;border-left:3px solid {BRAND_COLOR};color:#334155;">
{comments}
</blockquote>
{_button("Update Offer", edit_url)}
"""
    html = _wrap_html(
        title="Changes requested on an offer letter",
        preheader=f"Admin requested changes for {candidate_name}'s offer",
        body_html=body,
    )
    return send_email(hr_email, f"Changes requested: Offer for {candidate_name}", html)


def send_offer_approved_notice(hr_email, candidate_name, send_url):
    body = f"""\
<p>Hi,</p>
<p>The offer letter for <strong>{candidate_name}</strong> has been approved. You can now send it
to the candidate for e-signature.</p>
{_button("Send to Candidate", send_url)}
"""
    html = _wrap_html(
        title="Offer approved — ready to send",
        preheader=f"{candidate_name}'s offer was approved",
        body_html=body,
    )
    return send_email(hr_email, f"Approved: Offer for {candidate_name}", html)


def send_offer_for_signature(to_email, candidate_name, designation, sign_url, expires_display):
    body = f"""\
<p>Hi {candidate_name},</p>
<p>Congratulations! We're delighted to offer you the position of
<strong>{designation}</strong> at {COMPANY_NAME}.</p>
<p>Please review your offer letter and sign it electronically using the secure link below.</p>
{_button("Review & Sign Offer Letter", sign_url)}
<p style="font-size:13px;color:#64748b;">This link is unique to you and expires on
<strong>{expires_display}</strong>. Please don't forward it to anyone else.</p>
<p>We're looking forward to welcoming you to the team!</p>
"""
    html = _wrap_html(
        title="Your offer letter is ready to sign",
        preheader=f"Review and e-sign your offer from {COMPANY_NAME}",
        body_html=body,
    )
    return send_email(to_email, f"Your Offer Letter from {COMPANY_NAME}", html, to_name=candidate_name)


def send_offer_awaiting_countersign(hr_email, candidate_name, countersign_url):
    body = f"""\
<p>Hi Team,</p>
<p><strong>{candidate_name}</strong> has e-signed their offer letter. It now needs an HR
countersignature before the NDA can go out.</p>
{_button("Countersign Offer", countersign_url)}
"""
    html = _wrap_html(
        title="Offer signed — your countersignature is needed",
        preheader=f"{candidate_name} signed their offer, awaiting HR countersignature",
        body_html=body,
    )
    return send_email(hr_email, f"Please countersign: Offer for {candidate_name}", html)


def send_nda_awaiting_countersign(hr_email, candidate_name, countersign_url):
    body = f"""\
<p>Hi Team,</p>
<p><strong>{candidate_name}</strong> has e-signed their NDA. It now needs an HR
countersignature — once that's done, their onboarding invite goes out automatically.</p>
{_button("Countersign NDA", countersign_url)}
"""
    html = _wrap_html(
        title="NDA signed — your countersignature is needed",
        preheader=f"{candidate_name} signed their NDA, awaiting HR countersignature",
        body_html=body,
    )
    return send_email(hr_email, f"Please countersign: NDA for {candidate_name}", html)


def send_nda_for_signature(to_email, candidate_name, sign_url, expires_display):
    body = f"""\
<p>Hi {candidate_name},</p>
<p>Thanks for signing your offer letter! One last step before we move on to onboarding —
please review and sign your Non-Disclosure Agreement below.</p>
{_button("Review & Sign NDA", sign_url)}
<p style="font-size:13px;color:#64748b;">This link is unique to you and expires on
<strong>{expires_display}</strong>. Please don't forward it to anyone else.</p>
"""
    html = _wrap_html(
        title="Please sign your NDA",
        preheader=f"Your NDA from {COMPANY_NAME} is ready to sign",
        body_html=body,
    )
    return send_email(to_email, f"Non-Disclosure Agreement — {COMPANY_NAME}", html, to_name=candidate_name)


def send_nda_signed_notice(hr_email, candidate_name):
    body = f"""\
<p>Hi Team,</p>
<p><strong>{candidate_name}</strong> has e-signed their NDA. Their onboarding invite has been
sent automatically — you'll see them appear in the Onboarding Pipeline shortly.</p>
"""
    html = _wrap_html(
        title="NDA signed — onboarding invite sent",
        preheader=f"{candidate_name} completed their NDA",
        body_html=body,
    )
    return send_email(hr_email, f"NDA signed: {candidate_name}", html)
