"""
Offer Letter -> Admin Approval -> Candidate E-Sign -> HR Countersign
  -> NDA (auto-sent + candidate e-sign + HR countersign) -> Onboarding (auto-trigger)

Flow:
  1. HR fills out an offer letter form for a candidate, picking an Offer Type
     (Full Time / Contract / Intern — each uses its own template, since the
     compensation section differs). This creates a minimal `hrms_employees`
     shell row (status='Offer Pending') plus an `employee_offers` row
     (status='Draft'), with the offer letter content rendered from the
     matching editable `offer_templates` row.
  2. HR submits the offer for Admin review -> status='Pending Approval'.
  3. Admin reviews the rendered letter and either Approves (-> 'Approved') or
     Requests Changes with a comment (-> 'Changes Requested', back to HR).
  4. HR sends the approved offer to the candidate for e-signature -> 'Sent'.
     A one-time secure link is emailed to the candidate (no login needed).
  5. Candidate reviews the offer, types their legal name, and clicks "I Accept".
     We capture name + timestamp + IP as an audit trail. -> 'Signed' (awaiting
     HR countersignature).
  6. HR reviews the signed offer and countersigns (types their name) ->
     'Countersigned' — the offer is now fully executed and the final PDF
     (with both signatures) is generated. This automatically creates and
     sends an NDA (fixed boilerplate, no separate approval cycle).
  7. Candidate e-signs the NDA the same way -> 'Signed' (awaiting HR
     countersignature). HR countersigns -> 'Countersigned'. The moment the
     NDA is fully countersigned, the existing self-service onboarding invite
     is fired automatically for that same employee row — no manual "Send
     Invite" click.

E-signature here is an in-app click-to-accept signature (name + timestamp +
IP captured and embedded in the PDF) — a valid electronic signature under
India's IT Act, but NOT an Aadhaar-eSign/DSC-grade signature (that needs a
paid third party). This keeps the whole flow free.

Blueprints:
  - offers_bp          (HR/Admin, under /hrms/offers, requires login)
  - offers_public_bp    (candidate-facing e-sign pages, under /sign, token-gated,
                          deliberately NOT behind @login_required)
"""

import os
import time
import base64
import secrets
from io import BytesIO
from datetime import date, datetime, timedelta

from flask import (
    Blueprint, request, render_template, redirect, session,
    jsonify, url_for, current_app, Response, flash
)

from utils.db import get_db, release_db
from utils.auth import login_required
from utils import supabase_rest
from utils import mailer
from hrms.notifications.routes import create_notification

try:
    from xhtml2pdf import pisa
    PDF_GENERATOR_AVAILABLE = True
except Exception:
    PDF_GENERATOR_AVAILABLE = False

offers_bp = Blueprint("offers", __name__, url_prefix="/hrms/offers")
offers_public_bp = Blueprint("offers_public", __name__, url_prefix="/sign")

TOKEN_VALID_DAYS = 7
OFFER_TYPES = ["Full Time", "Contract", "Intern"]

# The full registered entity name as it appears in the company's actual signed
# offer letters/NDA — distinct from the short "Anti AI" brand name used
# elsewhere in the app (emails, sidebar, etc).
LEGAL_ENTITY_NAME = os.getenv("LEGAL_ENTITY_NAME", "ANTI.AI PRIVATE LIMITED")


# =====================================================================
# Helpers
# =====================================================================

def hr_admin_required():
    return session.get("role") in ["HR", "Admin"]


def admin_required():
    return session.get("role") == "Admin"


def _new_token():
    return secrets.token_urlsafe(32)


def _hr_notify_email():
    return os.getenv("HR_NOTIFY_EMAIL", os.getenv("EMAIL_ADDRESS", "antiai.hr@gmail.com"))


def _client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


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


def _b64_image(filename):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                         "static", "images", filename)
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception as e:
        print(f"Could not load logo asset {filename}:", e)
        return None


# Loaded once at import time — inlined as data URIs so PDF generation never
# depends on a network fetch for the letterhead assets (logos or fonts).
_LOGO_WORDMARK_B64 = _b64_image("logo_wordmark.png")
_LOGO_WATERMARK_B64 = _b64_image("logo_globe_watermark.png")


def _b64_font(filename):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                         "static", "fonts", filename)
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception as e:
        print(f"Could not load font asset {filename}:", e)
        return None


_FONT_SERIF_B64 = _b64_font("DejaVuSerif.ttf")
_FONT_SERIF_BOLD_B64 = _b64_font("DejaVuSerif-Bold.ttf")


# =====================================================================
# Default templates — modelled directly on the company's existing signed
# offer letter format: numbered clauses, a full-width rule after each one,
# and the same section order for every Offer Type (Full Time / Contract /
# Intern) — only the position/compensation clauses (2 & 3) read differently.
# =====================================================================

_RULE = '<hr class="sec-divider">'

# =====================================================================
# NOTE: the three offer templates below are modelled directly, section for
# section and clause for clause, on the company's own reference documents
# (Offer_Letter_1_1.docx, CONTRACT_AGREEMENT_Eva_FIXED.docx,
# Internship_Agreement_1.docx, 2026_Sample_NDA.docx) — Full Time, Contract
# and Intern are genuinely different document types in those references
# (an offer letter vs. a commission-based contract vs. a full internship
# agreement), not one shared shape with a different compensation clause.
# =====================================================================

DEFAULT_OFFER_TEMPLATE_FULLTIME = f"""\
<p>Dear {{{{candidate_name}}}},</p>
<p>We are pleased to formally confirm your appointment as a Full-Time Employee at {{{{company_name}}}}. Based on
your performance, contribution, and alignment with the organization's leadership and strategic objectives, we are
offering you the position under the following terms and conditions:</p>
{_RULE}

<h3>1. Position &amp; Department</h3>
<p>You are appointed as <strong>{{{{designation}}}}</strong> in the <strong>{{{{department}}}}</strong> at
{{{{company_name}}}}.</p>
<p>You will report directly to the Founder/Management and are expected to adhere to company standards, reporting
structures, and internal policies.</p>
{_RULE}

<h3>2. Effective Date of Employment</h3>
<p>Your full-time employment is effective from <strong>{{{{effective_date}}}}</strong>.</p>
{_RULE}

<h3>3. Compensation &amp; CTC</h3>
<p><strong>A. Current Compensation</strong></p>
<ul>
<li>Monthly Gross Salary: <strong>{{{{monthly_gross}}}}</strong></li>
<li>Annual CTC: <strong>{{{{ctc_annual}}}}</strong></li>
</ul>
<p>This CTC represents the total cost to the company on an annualized basis and may include fixed and applicable
statutory components.</p>
<p><strong>B. Proposed Salary Revision (Subject to Conditions)</strong></p>
<p>Subject to company financial capacity, operational stability, and performance evaluation, your compensation may
be revised following a formal internal review. This revision is conditional and shall not be considered automatic
or guaranteed.</p>
{_RULE}

<h3>4. Work Location &amp; Working Hours</h3>
<p>Your role may require online, hybrid, or onsite presence as per operational requirements.</p>
<p>Company working hours are generally from <strong>10:00 AM to 7:00 PM (Monday to Saturday)</strong>. You are
expected to adhere to official working hours and obtain prior approval for any deviations.</p>
{_RULE}

<h3>5. Probation &amp; Confirmation</h3>
<p>You will be on probation for a period of <strong>3 months</strong> from the effective date of employment.</p>
<p>Your performance will be reviewed periodically. Upon successful completion of probation, your employment will be
confirmed in writing. The probation period may be extended if performance expectations are not met.</p>
{_RULE}

<h3>6. Roles &amp; Responsibilities</h3>
<p>Your responsibilities will include, but are not limited to:</p>
{{{{responsibilities_html}}}}
<p>You are expected to maintain a high standard of ownership, discretion, and accountability.</p>
{_RULE}

<h3>7. Leave Policy</h3>
<p>You shall be entitled to leave as per company policy, which may include:</p>
<ul>
<li>Privilege/Planned Leaves</li>
<li>Casual Leaves</li>
<li>Sick Leaves</li>
<li>Statutory Holidays</li>
<li>Weekly Off: Sunday</li>
</ul>
<p>Leave structure and accrual details will be governed by internal HR policy.</p>
{_RULE}

<h3>8. Code of Conduct &amp; HR Policies</h3>
<p>You are required to adhere strictly to the company's code of conduct, including:</p>
<ul>
<li>Professional workplace behaviour</li>
<li>Confidentiality and intellectual property protection</li>
<li>Non-disclosure of sensitive company data</li>
<li>Ethical standards in internal and external communications</li>
<li>Compliance with company IT and data security policies</li>
</ul>
{_RULE}

<h3>9. Confidentiality &amp; Intellectual Property</h3>
<p>All information, documents, strategies, systems, and data accessed or created during your employment shall
remain the sole property of {{{{company_name}}}}.</p>
<p>You shall not disclose any confidential information during or after employment without written authorization.</p>
{_RULE}

<h3>10. Conflict of Interest</h3>
<p>You must not engage in any business or activity that competes with or conflicts with the interests of
{{{{company_name}}}} during your employment.</p>
{_RULE}

<h3>11. Termination &amp; Notice Period</h3>
<p>Either party may terminate this employment by providing <strong>45 days' written notice</strong>.</p>
<p>In cases of misconduct, breach of confidentiality, policy violations, or unethical behaviour, the company
reserves the right to terminate employment with immediate effect.</p>
<p>If an employee resigns without serving the notice period, compensation in lieu of notice may be applicable as
per company policy.</p>
{_RULE}

<h3>12. Performance Appraisal &amp; Growth</h3>
<p>Performance reviews will be conducted periodically. Salary revisions, incentives, and role expansions shall be
based on measurable performance, contribution, and company capacity.</p>
{_RULE}

<h3>13. IT &amp; Data Security Policy</h3>
<p>You must:</p>
<ul>
<li>Use official communication channels for work</li>
<li>Avoid unauthorized sharing of company data</li>
<li>Report any security breaches immediately</li>
<li>Use company assets strictly for official purposes</li>
</ul>
{_RULE}

<h3>14. Exit Formalities</h3>
<p>In case of separation, you will be required to complete all exit formalities, including knowledge transfer,
return of company assets, and departmental clearances prior to final settlement.</p>
{_RULE}

<h3>15. Compensation Details (All Components in INR)</h3>
{{{{compensation_table}}}}

<h3>Acceptance &amp; Acknowledgment</h3>
<p>Please sign and return a copy of this letter as confirmation of your acceptance of the above terms.</p>
<p>We look forward to having you on board and are confident that this will be a meaningful and enriching experience
for you. We wish you success and growth during your tenure with {{{{company_name}}}}.</p>
<p>Best Regards,<br><strong>Divya Sharma</strong><br>Vice President &ndash; Strategy and Operations<br>
{{{{company_name}}}}</p>
"""

DEFAULT_OFFER_TEMPLATE_CONTRACT = f"""\
<p>This Contract for Commission Based Engagement &amp; Performance Evaluation ("Agreement") is executed on
<strong>{{{{effective_date}}}}</strong>,</p>
<p><strong>BY AND BETWEEN</strong></p>
<p><strong>{{{{company_name}}}}</strong>, having its registered office at <strong>73 Rose Villa, Rajendra Nagar,
Bharatpur City, Rajasthan, India, 321001</strong>, hereinafter referred to as the "Company"</p>
<p><strong>AND</strong></p>
<p><strong>{{{{candidate_name}}}}</strong>, hereinafter referred to as the "Service Provider"</p>
{_RULE}

<h3>1. Purpose of Engagement</h3>
<p>The Company agrees to engage the Service Provider under a commission-based arrangement in the role of
<strong>{{{{designation}}}}</strong>.</p>
<p>The scope of work includes, but is not limited to, the responsibilities set out below:</p>
{{{{responsibilities_html}}}}
<p>This Agreement is solely for evaluation of suitability, performance, and alignment. It does not constitute an
employment offer.</p>
{_RULE}

<h3>2. Contract Engagement Period</h3>
<ul>
<li>The contract period shall commence on <strong>{{{{effective_date}}}}</strong>.</li>
<li>During this period, the Service Provider shall work on assigned tasks, learning modules, and operational
activities as directed by the Company.</li>
</ul>
{_RULE}

<h3>3. Commission Structure</h3>
<ul>
<li>The Service Provider shall be entitled to commission payments linked to successful deliverables agreed with
the Company.</li>
<li>Commission range for {{{{candidate_first_name}}}}: <strong>{{{{commission_min}}}} to {{{{commission_max}}}}</strong>
per successful deal.</li>
<li>Commission rates and payout schedules shall be communicated separately by the Company and may vary depending
on the role, client, and scope of work.</li>
<li>No fixed stipend or salary shall be payable under this Agreement.</li>
</ul>
{_RULE}

<h3>4. Confidentiality</h3>
<p>The Service Provider agrees to maintain strict confidentiality regarding all Company information, including but
not limited to client requirements and data, internal strategies and communication records, and internal
operations and onboarding details.</p>
<p>This obligation shall survive termination or completion of this Agreement.</p>
{_RULE}

<h3>5. Performance Evaluation</h3>
<p>The Service Provider's performance shall be reviewed on an ongoing basis, with a formal evaluation conducted
after two weeks of the engagement period.</p>
<p>Evaluation parameters may include, but are not limited to, quality and timeliness of delivery, effectiveness of
outreach and client communication, smoothness of coordination, and alignment with Company expectations and
workflows.</p>
{_RULE}

<h3>6. Post-Contract Decision</h3>
<p>Based on the evaluation outcomes, the Company may, at its sole discretion, initiate discussions regarding
compensation, role definition, and continuation under a paid engagement or employment contract &mdash; or the
Company may decide to discontinue the engagement if the Service Provider does not meet the required standards or
alignment.</p>
<p>No obligation shall arise on the Company to offer compensation or continued engagement.</p>
{_RULE}

<h3>7. Discontinuation</h3>
<p>The Company reserves the right to discontinue the engagement at any time during the contract period, without
notice, in case of unsatisfactory performance, misconduct, or misalignment with requirements.</p>
<p>The Service Provider may also withdraw from the contract by informing the Company. Upon discontinuation, no
compensation or claims shall be applicable from either party.</p>
{_RULE}

<h3>8. Intellectual Property</h3>
<p>Any strategies, reports, or materials created during the contract period shall remain the exclusive property of
the Company, unless otherwise agreed in writing.</p>
{_RULE}

<h3>9. No Employment Relationship</h3>
<p>Nothing contained in this Agreement shall be construed as creating an employer-employee relationship. The
Service Provider shall not represent themselves as an employee of the Company during the contract period.</p>
{_RULE}

<h3>10. Governing Law</h3>
<p>This Agreement shall be governed by and construed in accordance with the laws of India. Any disputes shall be
subject to the jurisdiction of the competent courts in India.</p>
{_RULE}

<h3>11. Acceptance</h3>
<p>By signing below, the Service Provider confirms that they have read, understood, and voluntarily agree to all
terms and conditions stated herein.</p>
<p>Name: {{{{sig_line}}}}<br>Designation: {{{{sig_line}}}}<br>Date: {{{{sig_line}}}}</p>
"""

DEFAULT_OFFER_TEMPLATE_INTERN = f"""\
<p>This Internship Agreement (the "Agreement") is entered into between <strong>{{{{company_name}}}}</strong> (the
"Company") and <strong>{{{{candidate_name}}}}</strong>, residing at <strong>{{{{candidate_address}}}}</strong>
(the "Intern"). The purpose of this internship is for the Intern to gain professional experience and academic
insight while contributing to the Company's strategic initiatives. The Company and the Intern shall collectively
be referred to as the "Parties".</p>
{_RULE}

<h3>1. Position and Department</h3>
<ul>
<li><strong>Role:</strong> The Intern is appointed as a <strong>{{{{designation}}}}</strong>.</li>
<li><strong>Department:</strong> The Intern will work primarily within the <strong>{{{{department}}}}</strong>
Department and may collaborate across multiple departments.</li>
</ul>
{_RULE}

<h3>2. Purpose of Internship</h3>
<p>The purpose of this internship is to provide the Intern with practical exposure, hands-on experience, and skill
development in a professional work environment.</p>
<p>This internship is intended for educational and training purposes and does not constitute employment.</p>
{_RULE}

<h3>3. Scope of Work &amp; Responsibilities</h3>
<p>The Intern may be assigned responsibilities across multiple functional areas depending on business
requirements, academic background, and project needs, including but not limited to:</p>
{{{{responsibilities_html}}}}
<p>The scope of work may evolve based on organizational requirements, project priorities, and the Intern's
performance.</p>
{_RULE}

<h3>4. Internship Duration</h3>
<p>The internship shall commence on <strong>{{{{effective_date}}}}</strong> and run for
<strong>{{{{duration_months}}}}</strong>, subject to satisfactory performance and mutual agreement on extension.</p>
<p>The Company reserves the right to extend or modify the duration based on performance and business needs.</p>
{_RULE}

<h3>5. Stipend &amp; Compensation</h3>
<p>The Intern shall receive a monthly stipend of <strong>{{{{stipend_monthly}}}}</strong> for the duration of the
internship, which may include a fixed component and a performance-based variable component.</p>
<p>The variable component, if applicable, shall be based on performance, initiative, and contribution, evaluated
periodically.</p>
{_RULE}

<h3>6. Work Arrangement</h3>
<p>The internship may be remote, on-site, or hybrid, as determined by the Company. The Intern is expected to
adhere to assigned working hours, maintain regular communication with reporting managers, and ensure timely
completion of tasks.</p>
{_RULE}

<h3>7. Confidentiality &amp; Non-Disclosure</h3>
<p>The Intern agrees to maintain strict confidentiality of all company information, not disclose, copy, or misuse
any proprietary data, and use company information solely for assigned work. This obligation shall continue during
and after the internship.</p>
{_RULE}

<h3>8. Intellectual Property (IP Rights)</h3>
<p>All work, documents, reports, data, systems, or intellectual property created during the internship shall be
the sole property of the Company. The Intern shall have no ownership rights over such work.</p>
{_RULE}

<h3>9. Code of Conduct &amp; Company Policies</h3>
<p>The Intern agrees to comply with company policies and guidelines, professional and ethical standards, data
security and IT policies, and workplace behaviour expectations. Any violation may result in disciplinary action or
termination.</p>
{_RULE}

<h3>10. IT &amp; Data Security</h3>
<p>The Intern shall use only authorized systems and tools, avoid sharing company data externally, follow
cybersecurity best practices, and report any security breaches immediately.</p>
{_RULE}

<h3>11. Conflict of Interest</h3>
<p>The Intern shall not engage in any activity, employment, or business that creates a conflict of interest with
the Company.</p>
{_RULE}

<h3>12. Performance Evaluation</h3>
<p>The Intern's performance may be evaluated based on task completion and quality of work, initiative and
problem-solving ability, and professional conduct and collaboration. Based on performance, the Intern may be
considered for future opportunities.</p>
{_RULE}

<h3>13. Internship Completion</h3>
<p>Upon successful completion and satisfactory performance, the Intern may receive an Internship Completion
Certificate and a Letter of Recommendation, if applicable.</p>
{_RULE}

<h3>14. Termination</h3>
<p>The Company reserves the right to terminate the internship under circumstances including misconduct or
unprofessional behaviour, breach of confidentiality, poor performance, or violation of company policies. The
Intern may also terminate the internship with prior written notice.</p>
{_RULE}

<h3>15. Exit Formalities</h3>
<p>Upon completion or termination, the Intern must submit all deliverables and reports, return or delete company
data and materials, complete knowledge transfer (if required), and surrender access to company systems. Completion
of exit formalities is mandatory.</p>
{_RULE}

<h3>16. No Employment Guarantee</h3>
<p>This internship does not constitute an offer of employment and does not guarantee future employment with the
Company.</p>
{_RULE}

<h3>17. Liability &amp; Indemnity</h3>
<p>The Intern agrees that the Company shall not be liable for any personal loss, damage, or injury arising during
the internship. The Intern agrees to indemnify the Company against any loss caused due to breach of this
Agreement.</p>
{_RULE}

<h3>18. Governing Law &amp; Jurisdiction</h3>
<p>This Agreement shall be governed by the laws of India. Any disputes shall be subject to the jurisdiction of
courts in Rajasthan.</p>
{_RULE}

<h3>19. Stipend Details</h3>
{{{{compensation_table}}}}

<h3>Acceptance &amp; Acknowledgment</h3>
<p>By signing below, both parties agree to the terms and conditions of this Agreement.</p>
<p><strong>{{{{company_name}}}}</strong><br>Name: {{{{sig_line}}}}<br>Designation: {{{{sig_line}}}}<br>
Signature: {{{{sig_line}}}}</p>
<p><strong>Intern</strong><br>Name: {{{{sig_line}}}}<br>Signature: {{{{sig_line}}}}</p>
<p>The Intern confirms that they have read, understood, and agreed to all terms outlined in this Agreement.</p>
<p>"We look forward to having you on board and are confident that this internship will be a meaningful and
enriching experience for you. We wish you success and growth during your tenure with {{{{company_name}}}}."</p>
"""

DEFAULT_NDA_TEMPLATE = f"""\
<h3>PARTIES:</h3>
<p>This Non-Disclosure Agreement (hereinafter referred to as the "Agreement") is entered on
<strong>{{{{today_date}}}}</strong> by and between <strong>{{{{company_name}}}}</strong>, with an address of
<strong>73, Rose Villa, Rajendra Nagar, Bharatpur, Rajasthan</strong> (hereinafter referred to as the "Disclosing
Party") and <strong>{{{{candidate_name}}}}</strong> with an address of <strong>{{{{candidate_address}}}}</strong>
(hereinafter referred to as the "Receiving Party") (collectively referred to as the "Parties").</p>
{_RULE}

<h3>CONFIDENTIAL INFORMATION</h3>
<p>The Receiving Party agrees not to disclose, copy, clone, or modify any confidential information related to the
Disclosing Party and agrees not to use any such information without obtaining written consent.</p>
<p>Information related to the company will be kept undisclosed and should not be shared with any party or
individual under this agreement. Information includes (code, functionality of software, product description, idea
of the technology and algorithms used, etc.).</p>
<p>"Confidential information" refers to any data or information that is related to the Disclosing Party, in any
form, including but not limited to oral or written. Such confidential information includes, but is not limited to,
any information related to the business or industry of the Disclosing Party, such as discoveries, processes,
techniques, programs, knowledge bases, customer lists, potential customers, business partners, affiliated
partners, leads, know-how, or any other services related to the Disclosing Party.</p>
{_RULE}

<h3>RETURN OF CONFIDENTIAL INFORMATION</h3>
<p>The Receiving Party agrees to return all the confidential information to the Disclosing Party upon the
termination of this Agreement. The Receiving Party further agrees not to use or disclose the confidential
information of the Disclosing Party in the public domain and shall not take any undue advantage of the
confidential information of the Disclosing Party.</p>
{_RULE}

<h3>OWNERSHIP</h3>
<p>This Agreement is not transferable and may only be transferred with written consent provided by both Parties.</p>
{_RULE}

<h3>GOVERNING LAW</h3>
<p>This Agreement shall be governed by and construed in accordance with the laws of the Indian Constitution.</p>
{_RULE}

<h3>SIGNATURE AND DATE</h3>
<p>The Parties hereby agree to the terms and conditions set forth in this Agreement and such is demonstrated by
their signatures below:</p>
<p><strong>Disclosing Party</strong><br>Name: {{{{sig_line}}}}<br>Date: {{{{sig_line}}}}<br>
Signature: {{{{sig_line}}}}</p>
<p><strong>Receiving Party</strong><br>Name: {{{{sig_line}}}}<br>Date: {{{{sig_line}}}}<br>
Signature: {{{{sig_line}}}}</p>
"""

TEMPLATE_DEFAULTS = {
    "offer_letter_fulltime": DEFAULT_OFFER_TEMPLATE_FULLTIME,
    "offer_letter_contract": DEFAULT_OFFER_TEMPLATE_CONTRACT,
    "offer_letter_intern": DEFAULT_OFFER_TEMPLATE_INTERN,
    "nda": DEFAULT_NDA_TEMPLATE,
}


def _template_key_for_offer_type(offer_type):
    return {
        "Full Time": "offer_letter_fulltime",
        "Contract": "offer_letter_contract",
        "Intern": "offer_letter_intern",
    }.get(offer_type, "offer_letter_fulltime")


def _get_offer_template(template_type):
    """Fetch the editable template row, seeding it with the default on first use (cached per request)."""
    from flask import g
    if not hasattr(g, "offer_templates_cache"):
        g.offer_templates_cache = {}
    if template_type in g.offer_templates_cache:
        return g.offer_templates_cache[template_type]
    res = _get_offer_template_uncached(template_type)
    g.offer_templates_cache[template_type] = res
    return res

def _get_offer_template_uncached(template_type):
    default_content = TEMPLATE_DEFAULTS.get(template_type, DEFAULT_OFFER_TEMPLATE_FULLTIME)
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("Database connection failed")
        cur.execute("SELECT * FROM offer_templates WHERE template_type = %s", (template_type,))
        row = cur.fetchone()
        if row:
            return row["template_content"]
        cur.execute(
            "INSERT INTO offer_templates (template_type, template_content, updated_by) VALUES (%s,%s,%s)",
            (template_type, default_content, "System"),
        )
        conn.commit()
        return default_content
    except Exception as e:
        print(f"Error fetching offer_templates via DB ({template_type}), trying REST:", e)
        try:
            row = supabase_rest.get_first_row("offer_templates", {"template_type": f"eq.{template_type}"})
            if row:
                return row["template_content"]
            supabase_rest.insert_row("offer_templates", {
                "template_type": template_type, "template_content": default_content, "updated_by": "System",
            })
            return default_content
        except Exception as rest_err:
            print("REST fallback for offer_templates failed:", rest_err)
            return default_content
    finally:
        if conn:
            release_db(conn, cur)


def _indian_number(v):
    """Format with Indian digit grouping (lakhs/crores) — e.g. 550000 -> '5,50,000',
    matching the reference offer letter's number formatting."""
    try:
        v = float(v)
    except Exception:
        return "0"
    neg = v < 0
    v = abs(v)
    int_part = str(int(round(v)))
    if len(int_part) <= 3:
        grouped = int_part
    else:
        last3, rest = int_part[-3:], int_part[:-3]
        parts = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        grouped = ",".join(parts) + "," + last3
    return ("-" if neg else "") + grouped


def _fmt_money(v):
    """A full '₹X,XX,XXX/-' figure for headline sentences. The bundled DejaVu Serif
    font (embedded into the PDF) includes the ₹ glyph, unlike xhtml2pdf's base-14 fonts."""
    try:
        float(v)
    except Exception:
        return "-"
    return f"₹{_indian_number(v)}/-"


def _compensation_table(basic, hra, special, bonus, pf=0):
    """The Total row is always the sum of the components — never a separately
    typed figure — so the table can never contradict itself. Bare Indian-grouped
    numbers in the cells (no ₹ or /-), matching the reference letter's table."""
    basic = basic or 0
    hra = hra or 0
    special = special or 0
    bonus = bonus or 0
    pf = pf or 0
    total_monthly = float(basic) + float(hra) + float(special) + float(pf) + float(bonus)
    rows = [
        ("BASIC SALARY", basic),
        ("HOUSE RENT ALLOWANCE", hra),
        ("SPECIAL ALLOWANCE", special),
        ("PROVIDENT FUND", pf),
        ("PERFORMANCE BONUS", bonus),
    ]
    body = "".join(
        f"<tr><td>{name}</td><td>{_indian_number(v)}</td><td>{_indian_number(float(v) * 12)}</td></tr>"
        for name, v in rows
    )
    return f"""\
<table>
<tr><th>Component</th><th>Amount (Month)</th><th>Amount (Annum)</th></tr>
{body}
<tr><td><strong>Total CTC</strong></td><td><strong>{_indian_number(total_monthly)}</strong></td>
<td><strong>{_indian_number(total_monthly * 12)}</strong></td></tr>
</table>""", total_monthly * 12


def _fill(template, ctx):
    out = template
    for key, val in ctx.items():
        out = out.replace("{{" + key + "}}", val if val is not None else "")
    return out


def _fmt_date(d):
    if not d:
        return "-"
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d.replace("Z", "+00:00"))
        except Exception:
            return d
    try:
        return d.strftime("%d %b %Y")
    except Exception:
        return str(d)


def _render_offer_content(offer_data):
    offer_type = offer_data.get("offer_type") or "Full Time"
    tpl = _get_offer_template(_template_key_for_offer_type(offer_type))
    responsibilities = offer_data.get("responsibilities") or ""
    resp_items = [line.strip("-• ").strip() for line in responsibilities.splitlines() if line.strip()]
    resp_html = "<ul>" + "".join(f"<li>{r}</li>" for r in resp_items) + "</ul>" if resp_items else "<p>As assigned by your reporting manager.</p>"

    if offer_type == "Intern":
        stipend = offer_data.get("stipend_monthly") or 0
        months = offer_data.get("duration_months") or 1
        comp_table_html = f"""\
<table>
<tr><th>Component</th><th>Amount (Month)</th><th>Amount (Total)</th></tr>
<tr><td>Monthly Stipend</td><td>{_indian_number(stipend)}</td><td>{_indian_number(float(stipend) * float(months))}</td></tr>
</table>"""
        computed_ctc_annual = float(stipend) * 12
    elif offer_type == "Contract":
        comp_table_html = ""  # Contract Agreement has no CTC table — commission-based only
        computed_ctc_annual = 0
    else:
        comp_table_html, computed_ctc_annual = _compensation_table(
            offer_data.get("basic_monthly"), offer_data.get("hra_monthly"),
            offer_data.get("special_allowance_monthly"), offer_data.get("bonus_monthly"),
            offer_data.get("pf_monthly"),
        )

    ctx = {
        "today_date": datetime.utcnow().strftime("%d %b %Y"),
        "candidate_name": offer_data.get("candidate_name", ""),
        "candidate_first_name": (offer_data.get("candidate_name") or "").split(" ")[0],
        "candidate_address": offer_data.get("candidate_address") or "[Address]",
        "company_name": LEGAL_ENTITY_NAME,
        "designation": offer_data.get("designation", ""),
        "department": offer_data.get("department") or "the relevant",
        "effective_date": _fmt_date(offer_data.get("effective_date")),
        "responsibilities_html": resp_html,
        "monthly_gross": _fmt_money(computed_ctc_annual / 12 if computed_ctc_annual else 0),
        # Always the sum of the monthly components — never a separately typed
        # figure — so the headline sentence can never contradict the table below it.
        "ctc_annual": _fmt_money(computed_ctc_annual),
        "compensation_table": comp_table_html,
        "contract_end_date": _fmt_date(offer_data.get("contract_end_date")),
        "commission_min": _fmt_money(offer_data.get("commission_min")),
        "commission_max": _fmt_money(offer_data.get("commission_max")),
        "duration_months": f"{offer_data.get('duration_months')} month(s)" if offer_data.get("duration_months") else "the agreed duration",
        "stipend_monthly": _fmt_money(offer_data.get("stipend_monthly")),
        "sig_line": "_" * 30,
    }
    return _fill(tpl, ctx)


def _render_nda_content(candidate_name, candidate_address, designation):
    tpl = _get_offer_template("nda")
    ctx = {
        "today_date": datetime.utcnow().strftime("%d %b %Y"),
        "candidate_name": candidate_name or "",
        "candidate_address": candidate_address or "[Address]",
        "designation": designation or "",
        "company_name": LEGAL_ENTITY_NAME,
        "sig_line": "_" * 30,
    }
    return _fill(tpl, ctx)


def _get_company(cur=None):
    try:
        if cur:
            cur.execute("SELECT * FROM company_settings LIMIT 1")
            row = cur.fetchone()
            if row:
                return row
    except Exception:
        pass
    try:
        row = supabase_rest.get_first_row("company_settings", {})
        if row:
            return row
    except Exception:
        pass
    return {"company_name": LEGAL_ENTITY_NAME, "company_address": "73, Rose Villa, Rajendra Nagar, Bharatpur"}


def _update_company_settings(fields):
    """Upsert into the single company_settings row — used by the Document
    Appearance panel (watermark/logo image + sizing overrides)."""
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        set_clause = ", ".join(f"{k}=%s" for k in fields)
        cur.execute(f"UPDATE company_settings SET {set_clause}", list(fields.values()))
        if cur.rowcount == 0:
            cols = ", ".join(fields.keys())
            placeholders = ", ".join(["%s"] * len(fields))
            cur.execute(f"INSERT INTO company_settings ({cols}) VALUES ({placeholders})", list(fields.values()))
        conn.commit()
        return True
    except Exception as e:
        print("Error updating company_settings via DB, trying REST:", e)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            row = supabase_rest.get_first_row("company_settings", {})
            if row:
                supabase_rest.update_rows("company_settings", {"id": f"eq.{row['id']}"}, fields)
            else:
                supabase_rest.insert_row("company_settings", fields)
            return True
        except Exception as rest_err:
            print("REST fallback for company_settings update failed:", rest_err)
            return False
    finally:
        if conn:
            release_db(conn, cur)


def _save_offer_template(template_type, content):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("SELECT id FROM offer_templates WHERE template_type = %s", (template_type,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE offer_templates SET template_content=%s, updated_by=%s, updated_at=NOW() WHERE template_type=%s",
                (content, session.get("user", "HR"), template_type),
            )
        else:
            cur.execute(
                "INSERT INTO offer_templates (template_type, template_content, updated_by) VALUES (%s,%s,%s)",
                (template_type, content, session.get("user", "HR")),
            )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error saving offer_templates ({template_type}) via DB, trying REST:", e)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            row = supabase_rest.get_first_row("offer_templates", {"template_type": f"eq.{template_type}"})
            if row:
                supabase_rest.update_rows("offer_templates", {"template_type": f"eq.{template_type}"},
                                           {"template_content": content, "updated_by": session.get("user", "HR")})
            else:
                supabase_rest.insert_row("offer_templates", {
                    "template_type": template_type, "template_content": content, "updated_by": session.get("user", "HR"),
                })
            return True
        except Exception as rest_err:
            print("REST fallback for saving offer template failed:", rest_err)
            return False
    finally:
        if conn:
            release_db(conn, cur)


def _signature_block(title, signed_name, signed_at, ip):
    return f"""\
<h3>{title}</h3>
<table>
<tr><td>Signed Name</td><td>{signed_name}</td></tr>
<tr><td>Signed At</td><td>{signed_at.strftime('%d %b %Y, %H:%M UTC')}</td></tr>
<tr><td>IP Address</td><td>{ip}</td></tr>
</table>
<p style="font-size:9pt;color:#6b7280;">Electronically signed via {os.getenv('COMPANY_NAME','Anti AI')} HRMS.
This constitutes a valid electronic signature under the Indian IT Act, 2000.</p>
"""


def _render_pdf_and_upload(content_html, file_label, doc_title=""):
    """Wrap content_html in the branded offer letterhead (logo, watermark,
    repeating per-page signature footer) and upload the rendered PDF to Storage."""
    if not PDF_GENERATOR_AVAILABLE:
        return None
    conn, cur = get_db(True)
    try:
        if not conn:
            raise Exception("no db")
        company = _get_company(cur)
    except Exception:
        company = _get_company(None)
    finally:
        if conn:
            try:
                release_db(conn, cur)
            except Exception:
                pass

    full_html = render_template(
        "hrms/offers_letterhead.html",
        content=content_html,
        company=company,
        doc_title=doc_title,
        # A custom logo/watermark uploaded via Offer Letters -> Edit Templates ->
        # Document Appearance overrides the bundled defaults; otherwise fall back
        # to the images shipped with the app.
        logo_wordmark_b64=company.get("offer_logo_wordmark_b64") or _LOGO_WORDMARK_B64,
        watermark_b64=company.get("offer_watermark_b64") or _LOGO_WATERMARK_B64,
        watermark_opacity=company.get("offer_watermark_opacity") if company.get("offer_watermark_opacity") is not None else 1.0,
        watermark_width_cm=company.get("offer_watermark_width_cm") or 13.5,
        logo_width_px=company.get("offer_logo_width_px") or 95,
        font_serif_b64=_FONT_SERIF_B64,
        font_serif_bold_b64=_FONT_SERIF_BOLD_B64,
    )
    import tempfile
    if os.getenv("VERCEL") == "1":
        upload_dir = os.path.join(tempfile.gettempdir(), "uploads")
    else:
        upload_dir = os.path.join(current_app.root_path, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    pdf_path = os.path.join(upload_dir, f"{file_label}_{int(time.time())}.pdf")
    try:
        with open(pdf_path, "w+b") as result_file:
            pisa_status = pisa.CreatePDF(full_html, dest=result_file)
            if pisa_status.err:
                raise Exception("xhtml2pdf error")
        with open(pdf_path, "rb") as f:
            file_bytes = f.read()
        object_key = f"offers/{int(time.time())}_{file_label}.pdf"
        return supabase_rest.upload_file_bytes(file_bytes, object_key)
    except Exception as e:
        print("PDF generation/upload failed:", e)
        return None


def _fire_onboarding_invite(employee_row):
    """Reuse the self-service onboarding invite flow, once the NDA is fully countersigned."""
    from hrms.onboarding.routes import _new_token as onb_token, TOKEN_VALID_DAYS as ONB_DAYS

    token = onb_token()
    expires_at = datetime.utcnow() + timedelta(days=ONB_DAYS)
    employee_id = employee_row["id"]

    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("""
            UPDATE hrms_employees SET status='Onboarding', onboarding_status='Invited',
                onboarding_token=%s, onboarding_token_expires_at=%s, invited_at=%s
            WHERE id=%s
        """, (token, expires_at, datetime.utcnow(), employee_id))
        conn.commit()
    except Exception as e:
        print("Error firing onboarding invite via DB, trying REST:", e)
        try:
            supabase_rest.update_rows("hrms_employees", {"id": f"eq.{employee_id}"}, {
                "status": "Onboarding", "onboarding_status": "Invited",
                "onboarding_token": token, "onboarding_token_expires_at": expires_at.isoformat(),
                "invited_at": datetime.utcnow().isoformat(),
            })
        except Exception as rest_err:
            print("REST fallback for firing onboarding invite failed:", rest_err)
    finally:
        if conn:
            release_db(conn, cur)

    invite_url = url_for("onboarding_public.onboarding_form", token=token, _external=True)
    mailer.send_onboarding_invite(
        to_email=employee_row["email"],
        candidate_name=employee_row["full_name"],
        invite_url=invite_url,
        designation=employee_row.get("designation"),
        department=employee_row.get("department"),
        expires_display=expires_at.strftime("%d %b %Y"),
    )


# =====================================================================
# HR / ADMIN SIDE
# =====================================================================

TEMPLATE_LABELS = {
    "offer_letter_fulltime": "Full Time — Offer Letter",
    "offer_letter_contract": "Contract — Contract Agreement",
    "offer_letter_intern": "Intern — Internship Agreement",
    "nda": "Non-Disclosure Agreement",
}

TEMPLATE_PLACEHOLDERS = {
    "offer_letter_fulltime": [
        "candidate_name", "company_name", "designation", "department", "effective_date",
        "monthly_gross", "ctc_annual", "responsibilities_html", "compensation_table", "sig_line",
    ],
    "offer_letter_contract": [
        "candidate_name", "candidate_first_name", "company_name", "designation", "effective_date",
        "responsibilities_html", "commission_min", "commission_max", "sig_line",
    ],
    "offer_letter_intern": [
        "candidate_name", "candidate_address", "company_name", "designation", "department",
        "effective_date", "duration_months", "stipend_monthly", "responsibilities_html",
        "compensation_table", "sig_line",
    ],
    "nda": ["today_date", "candidate_name", "candidate_address", "company_name", "sig_line"],
}

_PREVIEW_DUMMY_OFFER_DATA = {
    "offer_letter_fulltime": dict(
        candidate_name="Jordan Sample", candidate_email="jordan@example.com", designation="Software Engineer",
        department="Technical", effective_date=date.today().isoformat(), offer_type="Full Time",
        basic_monthly=30000, hra_monthly=12000, special_allowance_monthly=5000, pf_monthly=3600, bonus_monthly=5000,
        responsibilities="Sample responsibility one\nSample responsibility two",
    ),
    "offer_letter_contract": dict(
        candidate_name="Jordan Sample", candidate_email="jordan@example.com", designation="HR Recruiter",
        department="HR", effective_date=date.today().isoformat(), offer_type="Contract",
        commission_min=30000, commission_max=80000,
        responsibilities="Sample responsibility one\nSample responsibility two",
    ),
    "offer_letter_intern": dict(
        candidate_name="Jordan Sample", candidate_email="jordan@example.com", designation="Management Intern",
        department="Founder's Office", effective_date=date.today().isoformat(), offer_type="Intern",
        stipend_monthly=10000, duration_months=3, candidate_address="123 Sample Street, Sample City",
        responsibilities="Sample responsibility one\nSample responsibility two",
    ),
}


@offers_bp.route("/templates/ui", methods=["GET"])
@login_required
def templates_ui():
    """Self-service editor for the four document templates (raw HTML with
    {{placeholders}}) and the shared watermark/logo appearance — no code
    changes or restart needed to update wording, spacing, or branding."""
    if not hr_admin_required():
        return redirect("/dashboard")
    templates = {key: _get_offer_template(key) for key in TEMPLATE_DEFAULTS}
    company = _get_company()
    return render_template(
        "hrms/offer_templates_editor.html",
        templates=templates,
        template_defaults=TEMPLATE_DEFAULTS,
        template_labels=TEMPLATE_LABELS,
        template_placeholders=TEMPLATE_PLACEHOLDERS,
        company=company,
        default_logo_b64=_LOGO_WORDMARK_B64,
        default_watermark_b64=_LOGO_WATERMARK_B64,
    )


@offers_bp.route("/templates/<template_type>/save", methods=["POST"])
@login_required
def save_template(template_type):
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403
    if template_type not in TEMPLATE_DEFAULTS:
        return jsonify({"error": "Unknown template"}), 400
    content = request.form.get("content", "")
    if not content.strip():
        return jsonify({"error": "Template content can't be empty"}), 400
    from hrms.approvals.routes import create_approval_request
    
    current_content = _get_offer_template(template_type)
    payload_before = {"content": current_content} if current_content else {}
    
    if session.get("role") == "Admin":
        if not _save_offer_template(template_type, content):
            return jsonify({"error": "Failed to save template"}), 500
        create_approval_request("template_edit", "offer_templates", template_type, payload_before, {"content": content}, auto_approve=True)
        return jsonify({"success": True})
    else:
        create_approval_request("template_edit", "offer_templates", template_type, payload_before, {"content": content})
        return jsonify({"success": True, "message": "Submitted to Admin for Approval"})


@offers_bp.route("/templates/<template_type>/reset", methods=["POST"])
@login_required
def reset_template(template_type):
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403
    if template_type not in TEMPLATE_DEFAULTS:
        return jsonify({"error": "Unknown template"}), 400
    default_content = TEMPLATE_DEFAULTS[template_type]
    if not _save_offer_template(template_type, default_content):
        return jsonify({"error": "Failed to reset template"}), 500
    return jsonify({"success": True, "content": default_content})


@offers_bp.route("/templates/<template_type>/preview", methods=["GET"])
@login_required
def preview_template(template_type):
    """Renders a live PDF preview with sample data using whatever is currently
    saved (even unsaved edits, if 'content' is passed) plus the current
    appearance settings — lets HR see changes before they touch a real offer."""
    if not hr_admin_required():
        return redirect("/dashboard")
    if template_type not in TEMPLATE_DEFAULTS or not PDF_GENERATOR_AVAILABLE:
        return "Preview unavailable", 404

    override_content = request.args.get("content")

    if template_type == "nda":
        if override_content:
            content = _fill(override_content, {
                "today_date": datetime.utcnow().strftime("%d %b %Y"),
                "candidate_name": "Jordan Sample", "candidate_address": "123 Sample Street, Sample City",
                "designation": "Software Engineer", "company_name": LEGAL_ENTITY_NAME, "sig_line": "_" * 30,
            })
        else:
            content = _render_nda_content("Jordan Sample", "123 Sample Street, Sample City", "Software Engineer")
        doc_title = "NON-DISCLOSURE AGREEMENT"
    else:
        dummy = _PREVIEW_DUMMY_OFFER_DATA[template_type]
        if override_content:
            saved = _get_offer_template(template_type)
            try:
                _save_offer_template(template_type, override_content)
                content = _render_offer_content(dummy)
            finally:
                _save_offer_template(template_type, saved)
        else:
            content = _render_offer_content(dummy)
        doc_title = {
            "offer_letter_contract": "CONTRACT AGREEMENT", "offer_letter_intern": "INTERNSHIP AGREEMENT",
        }.get(template_type, "OFFER LETTER")

    company = _get_company()
    full_html = render_template(
        "hrms/offers_letterhead.html", content=content, company=company, doc_title=doc_title,
        logo_wordmark_b64=company.get("offer_logo_wordmark_b64") or _LOGO_WORDMARK_B64,
        watermark_b64=company.get("offer_watermark_b64") or _LOGO_WATERMARK_B64,
        watermark_opacity=company.get("offer_watermark_opacity") if company.get("offer_watermark_opacity") is not None else 1.0,
        watermark_width_cm=company.get("offer_watermark_width_cm") or 13.5,
        logo_width_px=company.get("offer_logo_width_px") or 95,
        font_serif_b64=_FONT_SERIF_B64, font_serif_bold_b64=_FONT_SERIF_BOLD_B64,
    )
    buf = BytesIO()
    pisa_status = pisa.CreatePDF(full_html, dest=buf)
    if pisa_status.err:
        return "Could not render preview — check your HTML for unclosed tags.", 400
    buf.seek(0)
    return Response(buf.read(), mimetype="application/pdf")


@offers_bp.route("/templates/appearance/save", methods=["POST"])
@login_required
def save_appearance():
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403
    fields = {}
    for form_key, col in [
        ("watermark_opacity", "offer_watermark_opacity"),
        ("watermark_width_cm", "offer_watermark_width_cm"),
        ("logo_width_px", "offer_logo_width_px"),
    ]:
        val = request.form.get(form_key)
        if val not in (None, ""):
            try:
                fields[col] = float(val)
            except ValueError:
                pass

    logo_file = request.files.get("logo_file")
    if logo_file and logo_file.filename:
        fields["offer_logo_wordmark_b64"] = base64.b64encode(logo_file.read()).decode()
    watermark_file = request.files.get("watermark_file")
    if watermark_file and watermark_file.filename:
        fields["offer_watermark_b64"] = base64.b64encode(watermark_file.read()).decode()

    if not fields:
        return jsonify({"error": "Nothing to update"}), 400
        
    from hrms.approvals.routes import create_approval_request
    
    current_company = _get_company()
    payload_before = dict(current_company) if current_company else {}
    
    if session.get("role") == "Admin":
        if not _update_company_settings(fields):
            return jsonify({"error": "Failed to save appearance settings"}), 500
        create_approval_request("appearance_change", "company_settings", None, payload_before, fields, auto_approve=True)
        return jsonify({"success": True})
    else:
        create_approval_request("appearance_change", "company_settings", None, payload_before, fields)
        return jsonify({"success": True, "message": "Submitted to Admin for Approval"})


@offers_bp.route("/templates/appearance/reset-images", methods=["POST"])
@login_required
def reset_appearance_images():
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403
    if not _update_company_settings({"offer_logo_wordmark_b64": None, "offer_watermark_b64": None}):
        return jsonify({"error": "Failed to reset images"}), 500
    return jsonify({"success": True})


@offers_bp.route("/", methods=["GET"])
@login_required
def pipeline():
    if not hr_admin_required():
        return redirect("/dashboard")
    conn, cur = None, None
    offers = []
    ndas_by_offer = {}
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("SELECT * FROM employee_offers ORDER BY created_at DESC")
        offers = cur.fetchall()
        cur.execute("SELECT id, offer_id, status FROM employee_ndas")
        for row in cur.fetchall():
            ndas_by_offer[str(row["offer_id"])] = row
    except Exception as e:
        print("Error fetching offers via DB, trying REST:", e)
        try:
            offers = supabase_rest.get_rows("employee_offers", {"order": "created_at.desc"}) or []
            for row in (supabase_rest.get_rows("employee_ndas", {}) or []):
                ndas_by_offer[str(row["offer_id"])] = row
        except Exception as rest_err:
            print("REST fallback for offers pipeline failed:", rest_err)
    finally:
        if conn:
            release_db(conn, cur)
    return render_template("hrms/offers_pipeline.html", offers=offers, ndas_by_offer=ndas_by_offer,
                            is_admin=admin_required())


@offers_bp.route("/new/ui", methods=["GET"])
@login_required
def new_ui():
    if not hr_admin_required():
        return redirect("/dashboard")
    
    application_id = request.args.get("application_id")
    prefill = None
    
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("SELECT id, role_name FROM hrms_roles ORDER BY role_name")
        roles = cur.fetchall()
        
        if application_id:
            cur.execute("SELECT name, email, phone, resume_url FROM applications WHERE id = %s", (application_id,))
            row = cur.fetchone()
            if row:
                prefill = {
                    "candidate_name": row["name"],
                    "candidate_email": row["email"],
                    "candidate_phone": row["phone"],
                    "resume_url": row["resume_url"],
                    "application_id": application_id
                }
    except Exception as e:
        print("Error fetching roles, trying REST:", e)
        roles = supabase_rest.list_roles()
    finally:
        if conn:
            release_db(conn, cur)
    return render_template("hrms/offer_form.html", roles=roles, offer=None, offer_types=OFFER_TYPES, prefill=prefill)


@offers_bp.route("", methods=["POST"])
@login_required
def create_offer():
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403

    data = request.form
    required = ["candidate_name", "candidate_email", "designation", "role_id"]
    for f in required:
        if not data.get(f):
            return jsonify({"error": f"{f.replace('_', ' ').title()} is required"}), 400

    offer_type = data.get("offer_type") if data.get("offer_type") in OFFER_TYPES else "Full Time"
    offer_fields = dict(
        candidate_name=data["candidate_name"],
        candidate_email=data["candidate_email"],
        candidate_address=data.get("candidate_address") or None,
        designation=data["designation"],
        department=data.get("department"),
        offer_type=offer_type,
        effective_date=data.get("effective_date") or None,
        ctc_annual=data.get("ctc_annual") or 0,
        basic_monthly=data.get("basic_monthly") or 0,
        hra_monthly=data.get("hra_monthly") or 0,
        special_allowance_monthly=data.get("special_allowance_monthly") or 0,
        pf_monthly=data.get("pf_monthly") or 0,
        bonus_monthly=data.get("bonus_monthly") or 0,
        contract_end_date=data.get("contract_end_date") or None,
        commission_min=data.get("commission_min") or 0,
        commission_max=data.get("commission_max") or 0,
        stipend_monthly=data.get("stipend_monthly") or 0,
        duration_months=data.get("duration_months") or None,
        responsibilities=data.get("responsibilities") or "",
        application_id=data.get("application_id") or None,
    )
    content_html = _render_offer_content(offer_fields)

    conn, cur = None, None
    employee_id, offer_id = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")

        cur.execute("SELECT id FROM hrms_employees WHERE email=%s AND status != 'Deleted'", (data["candidate_email"],))
        if cur.fetchone():
            release_db(conn, cur)
            return jsonify({"error": "An employee/candidate with this email already exists"}), 400

        employee_code = _next_employee_code(cur)
        cur.execute("""
            INSERT INTO hrms_employees (employee_code, full_name, email, department, designation,
                role_id, joining_date, status, employment_type)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'Offer Pending',%s) RETURNING id
        """, (employee_code, data["candidate_name"], data["candidate_email"], data.get("department"),
              data["designation"], data["role_id"], offer_fields["effective_date"] or date.today(),
              offer_type))
        employee_id = cur.fetchone()["id"]

        cur.execute("""
            INSERT INTO employee_offers (employee_id, candidate_name, candidate_email, candidate_address,
                designation, department, offer_type, effective_date, ctc_annual, basic_monthly, hra_monthly,
                special_allowance_monthly, pf_monthly, bonus_monthly, contract_end_date, commission_min,
                commission_max, stipend_monthly, duration_months, responsibilities,
                content_html, status, created_by, application_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Draft',%s,%s) RETURNING id
        """, (employee_id, offer_fields["candidate_name"], offer_fields["candidate_email"],
              offer_fields["candidate_address"], offer_fields["designation"], offer_fields["department"], offer_type,
              offer_fields["effective_date"], offer_fields["ctc_annual"], offer_fields["basic_monthly"],
              offer_fields["hra_monthly"], offer_fields["special_allowance_monthly"], offer_fields["pf_monthly"],
              offer_fields["bonus_monthly"], offer_fields["contract_end_date"], offer_fields["commission_min"],
              offer_fields["commission_max"], offer_fields["stipend_monthly"], offer_fields["duration_months"],
              offer_fields["responsibilities"], content_html, session.get("user", "HR"), offer_fields["application_id"]))
        offer_id = cur.fetchone()["id"]
        conn.commit()
        from utils.audit import log_action
        log_action(session.get("email") or "HR", "offer_created", "employee_offers", offer_id, 
                   {"candidate_name": offer_fields["candidate_name"], "candidate_email": offer_fields["candidate_email"], "designation": offer_fields["designation"]})
    except Exception as e:
        print("Error creating offer via DB, trying REST:", e)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            if supabase_rest.get_first_row("hrms_employees", {"email": f"eq.{data['candidate_email']}", "status": "not.eq.Deleted"}):
                return jsonify({"error": "An employee/candidate with this email already exists"}), 400
            last = supabase_rest.get_first_row("hrms_employees", {
                "select": "employee_code", "employee_code": "like.EMP-*", "order": "created_at.desc", "limit": 1
            })
            next_code = "EMP-0001"
            if last and last.get("employee_code"):
                try:
                    next_code = f"EMP-{(int(last['employee_code'].split('-')[1]) + 1):04d}"
                except Exception:
                    pass
            emp_row = supabase_rest.insert_row("hrms_employees", {
                "employee_code": next_code, "full_name": data["candidate_name"], "email": data["candidate_email"],
                "department": data.get("department"), "designation": data["designation"], "role_id": data["role_id"],
                "joining_date": str(offer_fields["effective_date"] or date.today()), "status": "Offer Pending",
                "employment_type": offer_type,
            })
            if not emp_row:
                return jsonify({"error": "Could not create the candidate record."}), 500
            employee_id = emp_row.get("id")
            offer_row = supabase_rest.insert_row("employee_offers", {
                **{k: (str(v) if isinstance(v, date) else v) for k, v in offer_fields.items()},
                "employee_id": employee_id, "content_html": content_html, "status": "Draft",
                "created_by": session.get("user", "HR"),
            })
            offer_id = offer_row.get("id") if offer_row else None
            from utils.audit import log_action
            log_action(session.get("email") or "HR", "offer_created", "employee_offers", offer_id, 
                       {"candidate_name": offer_fields["candidate_name"], "candidate_email": offer_fields["candidate_email"], "designation": offer_fields["designation"], "fallback": True})
        except Exception as rest_err:
            print("REST fallback for offer creation failed:", rest_err)
            return jsonify({"error": f"Failed to create offer: {rest_err}"}), 500
    finally:
        if conn and cur:
            release_db(conn, cur)

    return jsonify({"success": True, "redirect": "/hrms/offers/", "offer_id": offer_id})


def _get_offer(offer_id):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("SELECT * FROM employee_offers WHERE id=%s", (offer_id,))
        return cur.fetchone()
    except Exception as e:
        print("Error fetching offer via DB, trying REST:", e)
        try:
            return supabase_rest.get_first_row("employee_offers", {"id": f"eq.{offer_id}"})
        except Exception as rest_err:
            print("REST fallback for get offer failed:", rest_err)
            return None
    finally:
        if conn:
            release_db(conn, cur)


def _update_offer(offer_id, fields):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        set_clause = ", ".join(f"{k}=%s" for k in fields)
        cur.execute(f"UPDATE employee_offers SET {set_clause}, updated_at=now() WHERE id=%s",
                    (*fields.values(), offer_id))
        conn.commit()
        return True
    except Exception as e:
        print("Error updating offer via DB, trying REST:", e)
        try:
            supabase_rest.update_rows("employee_offers", {"id": f"eq.{offer_id}"}, fields)
            return True
        except Exception as rest_err:
            print("REST fallback for update offer failed:", rest_err)
            return False
    finally:
        if conn:
            release_db(conn, cur)


@offers_bp.route("/<offer_id>/review/ui", methods=["GET"])
@login_required
def review_ui(offer_id):
    if not hr_admin_required():
        return redirect("/dashboard")
    offer = _get_offer(offer_id)
    if not offer:
        return redirect("/hrms/offers/")
    return render_template("hrms/offer_review.html", offer=offer, is_admin=admin_required())


@offers_bp.route("/<offer_id>/submit", methods=["POST"])
@login_required
def submit_for_approval(offer_id):
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403
    offer = _get_offer(offer_id)
    if not offer or offer["status"] not in ("Draft", "Changes Requested"):
        return jsonify({"error": "This offer can't be submitted right now."}), 400

    _update_offer(offer_id, {"status": "Pending Approval", "submitted_at": datetime.utcnow().isoformat()})
    review_url = url_for("offers.review_ui", offer_id=offer_id, _external=True)
    mailer.send_offer_for_approval(_hr_notify_email(), offer["candidate_name"], offer["designation"],
                                    review_url, hr_name=session.get("user"))
    create_notification("Admin", "approval_requested", f"Offer pending your approval: {offer['candidate_name']}", review_url)
    return jsonify({"success": True})


@offers_bp.route("/<offer_id>/approve", methods=["POST"])
@login_required
def approve_offer(offer_id):
    if not admin_required():
        return jsonify({"error": "Only an Admin can approve offers"}), 403
    offer = _get_offer(offer_id)
    if not offer or offer["status"] != "Pending Approval":
        return jsonify({"error": "This offer isn't awaiting approval."}), 400

    _update_offer(offer_id, {
        "status": "Approved", "approved_by": session.get("user"), "approved_at": datetime.utcnow().isoformat(),
        "admin_comments": None,
    })
    send_url = url_for("offers.review_ui", offer_id=offer_id, _external=True)
    mailer.send_offer_approved_notice(_hr_notify_email(), offer["candidate_name"], send_url)
    create_notification("HR", "offer_approved", f"Offer approved for {offer['candidate_name']} — ready to send", send_url)
    return jsonify({"success": True})


@offers_bp.route("/<offer_id>/request-changes", methods=["POST"])
@login_required
def request_changes(offer_id):
    if not admin_required():
        return jsonify({"error": "Only an Admin can request changes"}), 403
    offer = _get_offer(offer_id)
    if not offer or offer["status"] != "Pending Approval":
        return jsonify({"error": "This offer isn't awaiting approval."}), 400
    comments = request.form.get("comments")
    if not comments:
        return jsonify({"error": "Please add a comment explaining what to change."}), 400

    _update_offer(offer_id, {"status": "Changes Requested", "admin_comments": comments})
    edit_url = url_for("offers.edit_ui", offer_id=offer_id, _external=True)
    mailer.send_offer_changes_requested(_hr_notify_email(), offer["candidate_name"], comments, edit_url)
    create_notification("HR", "offer_changes_requested", f"Admin requested changes on offer for {offer['candidate_name']}", edit_url)
    return jsonify({"success": True})


@offers_bp.route("/<offer_id>/edit/ui", methods=["GET"])
@login_required
def edit_ui(offer_id):
    if not hr_admin_required():
        return redirect("/dashboard")
    offer = _get_offer(offer_id)
    if not offer or offer["status"] not in ("Draft", "Changes Requested"):
        return redirect("/hrms/offers/")
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("SELECT id, role_name FROM hrms_roles ORDER BY role_name")
        roles = cur.fetchall()
    except Exception:
        roles = supabase_rest.list_roles()
    finally:
        if conn:
            release_db(conn, cur)
    return render_template("hrms/offer_form.html", roles=roles, offer=offer, offer_types=OFFER_TYPES)


@offers_bp.route("/<offer_id>/edit", methods=["POST"])
@login_required
def edit_offer(offer_id):
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403
    offer = _get_offer(offer_id)
    if not offer or offer["status"] not in ("Draft", "Changes Requested"):
        return jsonify({"error": "This offer can't be edited right now."}), 400

    data = request.form
    offer_type = data.get("offer_type") if data.get("offer_type") in OFFER_TYPES else offer["offer_type"]
    offer_fields = dict(
        candidate_name=data.get("candidate_name", offer["candidate_name"]),
        candidate_email=data.get("candidate_email", offer["candidate_email"]),
        candidate_address=data.get("candidate_address") or offer.get("candidate_address"),
        designation=data.get("designation", offer["designation"]),
        department=data.get("department", offer["department"]),
        offer_type=offer_type,
        effective_date=data.get("effective_date") or offer["effective_date"],
        ctc_annual=data.get("ctc_annual") or offer["ctc_annual"],
        basic_monthly=data.get("basic_monthly") or offer["basic_monthly"],
        hra_monthly=data.get("hra_monthly") or offer["hra_monthly"],
        special_allowance_monthly=data.get("special_allowance_monthly") or offer["special_allowance_monthly"],
        pf_monthly=data.get("pf_monthly") or offer.get("pf_monthly"),
        bonus_monthly=data.get("bonus_monthly") or offer["bonus_monthly"],
        contract_end_date=data.get("contract_end_date") or offer.get("contract_end_date"),
        commission_min=data.get("commission_min") or offer.get("commission_min"),
        commission_max=data.get("commission_max") or offer.get("commission_max"),
        stipend_monthly=data.get("stipend_monthly") or offer.get("stipend_monthly"),
        duration_months=data.get("duration_months") or offer.get("duration_months"),
        responsibilities=data.get("responsibilities", offer["responsibilities"]),
    )
    content_html = _render_offer_content(offer_fields)
    _update_offer(offer_id, {**offer_fields, "content_html": content_html, "status": "Draft", "admin_comments": None})
    return jsonify({"success": True, "redirect": "/hrms/offers/"})


@offers_bp.route("/<offer_id>/send", methods=["POST"])
@login_required
def send_offer(offer_id):
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403
    offer = _get_offer(offer_id)
    if not offer or offer["status"] != "Approved":
        return jsonify({"error": "Only approved offers can be sent for signature."}), 400

    token = _new_token()
    expires_at = datetime.utcnow() + timedelta(days=TOKEN_VALID_DAYS)
    _update_offer(offer_id, {
        "status": "Sent", "sign_token": token, "sign_token_expires_at": expires_at.isoformat(),
        "sent_at": datetime.utcnow().isoformat(),
    })
    from utils.audit import log_action
    log_action(session.get("email") or "HR", "offer_sent", "employee_offers", offer_id, {"candidate_name": offer["candidate_name"], "candidate_email": offer["candidate_email"]})
    sign_url = url_for("offers_public.sign_offer", token=token, _external=True)
    mailer.send_offer_for_signature(offer["candidate_email"], offer["candidate_name"], offer["designation"],
                                     sign_url, expires_at.strftime("%d %b %Y"))
    create_notification("HR", "offer_sent", f"Offer sent to {offer['candidate_name']} for signature", url_for("offers.review_ui", offer_id=offer["id"]))
    return jsonify({"success": True})


@offers_bp.route("/<offer_id>/countersign", methods=["POST"])
@login_required
def countersign_offer(offer_id):
    """HR types their name to countersign the offer once the candidate has signed it."""
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403
    offer = _get_offer(offer_id)
    if not offer or offer["status"] != "Signed":
        return jsonify({"error": "This offer isn't awaiting HR countersignature."}), 400

    hr_name = (request.form.get("hr_signed_name") or session.get("user") or "HR").strip()
    if not hr_name:
        return jsonify({"error": "Please type your name to countersign."}), 400

    hr_block = f"""\
<h3>HR Countersignature</h3>
<table>
<tr><td>Countersigned By</td><td>{hr_name}</td></tr>
<tr><td>Countersigned At</td><td>{datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}</td></tr>
</table>
"""
    final_html = offer["content_html"] + hr_block
    doc_title = {
        "Contract": "CONTRACT AGREEMENT",
        "Intern": "INTERNSHIP AGREEMENT",
    }.get(offer.get("offer_type"), "OFFER LETTER")
    pdf_url = _render_pdf_and_upload(final_html, f"offer_{offer['candidate_name'].replace(' ', '_')}", doc_title=doc_title)

    _update_offer(offer_id, {
        "status": "Countersigned", "hr_signed_name": hr_name, "hr_signed_at": datetime.utcnow().isoformat(),
        "content_html": final_html, "pdf_url": pdf_url,
    })
    from utils.audit import log_action
    log_action(session.get("email") or "HR", "offer_countersigned", "employee_offers", offer_id, {"hr_name": hr_name})

    # Auto-create + auto-send the NDA (fixed boilerplate, no separate approval cycle)
    nda_token = _new_token()
    nda_expires = datetime.utcnow() + timedelta(days=TOKEN_VALID_DAYS)
    nda_content = _render_nda_content(offer["candidate_name"], offer.get("candidate_address"), offer["designation"])

    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("""
            INSERT INTO employee_ndas (offer_id, employee_id, content_html, status, sign_token,
                sign_token_expires_at, sent_at)
            VALUES (%s,%s,%s,'Sent',%s,%s,%s)
        """, (offer["id"], offer["employee_id"], nda_content, nda_token, nda_expires, datetime.utcnow()))
        conn.commit()
    except Exception as e:
        print("Error creating NDA via DB, trying REST:", e)
        try:
            supabase_rest.insert_row("employee_ndas", {
                "offer_id": offer["id"], "employee_id": offer["employee_id"], "content_html": nda_content,
                "status": "Sent", "sign_token": nda_token, "sign_token_expires_at": nda_expires.isoformat(),
                "sent_at": datetime.utcnow().isoformat(),
            })
        except Exception as rest_err:
            print("REST fallback for NDA creation failed:", rest_err)
    finally:
        if conn:
            release_db(conn, cur)

    nda_sign_url = url_for("offers_public.sign_nda", token=nda_token, _external=True)
    mailer.send_nda_for_signature(offer["candidate_email"], offer["candidate_name"], nda_sign_url,
                                   nda_expires.strftime("%d %b %Y"))
    create_notification("HR", "nda_sent", f"NDA sent to {offer['candidate_name']} for signature", url_for("offers.review_ui", offer_id=offer["id"]))

    return jsonify({"success": True})


@offers_bp.route("/<offer_id>/delete", methods=["POST"])
@login_required
def delete_offer(offer_id):
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403
    offer = _get_offer(offer_id)
    if not offer:
        return jsonify({"error": "Offer not found"}), 404
    if offer["status"] not in ("Draft", "Changes Requested", "Pending Approval"):
        return jsonify({"error": "Signed or sent offers can't be deleted — use Onboarding's Delete instead."}), 400

    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("DELETE FROM employee_offers WHERE id=%s", (offer_id,))
        cur.execute("DELETE FROM hrms_employees WHERE id=%s AND status='Offer Pending'", (offer["employee_id"],))
        conn.commit()
        from utils.audit import log_action
        log_action(session.get("email") or "HR", "offer_deleted", "employee_offers", offer_id, {"candidate_name": offer["candidate_name"]})
    except Exception as e:
        print("Error deleting offer via DB, trying REST:", e)
        try:
            supabase_rest.delete_rows("employee_offers", {"id": f"eq.{offer_id}"})
            supabase_rest.delete_rows("hrms_employees", {"id": f"eq.{offer['employee_id']}", "status": "eq.Offer Pending"})
            from utils.audit import log_action
            log_action(session.get("email") or "HR", "offer_deleted", "employee_offers", offer_id, {"candidate_name": offer["candidate_name"], "fallback": True})
        except Exception as rest_err:
            print("REST fallback for delete offer failed:", rest_err)
            return jsonify({"error": "Failed to delete offer."}), 500
    finally:
        if conn:
            release_db(conn, cur)
            
    return jsonify({"success": True})


# =====================================================================
# PUBLIC E-SIGN — Offer Letter
# =====================================================================

def _lookup_offer_by_token(token):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("SELECT * FROM employee_offers WHERE sign_token=%s", (token,))
        return cur.fetchone()
    except Exception as e:
        print("Error looking up offer by token via DB, trying REST:", e)
        try:
            return supabase_rest.get_first_row("employee_offers", {"sign_token": f"eq.{token}"})
        except Exception as rest_err:
            print("REST fallback for offer token lookup failed:", rest_err)
            return None
    finally:
        if conn:
            release_db(conn, cur)


def _token_expired(exp):
    if not exp:
        return False
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp.replace("Z", "+00:00")).replace(tzinfo=None)
    elif exp.tzinfo:
        exp = exp.replace(tzinfo=None)
    return exp < datetime.utcnow()


@offers_public_bp.route("/offer/<token>", methods=["GET"])
def sign_offer(token):
    offer = _lookup_offer_by_token(token)
    if not offer:
        return render_template("esign_invalid.html", reason="not_found", doc="offer")
    if offer["status"] in ("Signed", "Countersigned"):
        return render_template("esign_invalid.html", reason="already_signed", doc="offer")
    if offer["status"] != "Sent":
        return render_template("esign_invalid.html", reason="not_ready", doc="offer")
    if _token_expired(offer.get("sign_token_expires_at")):
        return render_template("esign_invalid.html", reason="expired", doc="offer")
    return render_template("esign_offer.html", offer=offer, token=token)


@offers_public_bp.route("/offer/<token>", methods=["POST"])
def submit_offer_signature(token):
    offer = _lookup_offer_by_token(token)
    if not offer or offer["status"] != "Sent":
        return jsonify({"error": "This offer is no longer available for signature."}), 400

    signed_name = (request.form.get("signed_name") or "").strip()
    if not signed_name:
        return jsonify({"error": "Please type your full legal name to sign."}), 400
    if not request.form.get("agree"):
        return jsonify({"error": "Please confirm you accept the offer."}), 400

    signed_at = datetime.utcnow()
    ip = _client_ip()
    final_html = offer["content_html"] + _signature_block("Candidate Signature", signed_name, signed_at, ip)

    _update_offer(offer["id"], {
        "status": "Signed", "signed_name": signed_name, "signed_at": signed_at.isoformat(),
        "signed_ip": ip, "content_html": final_html,
    })
    from utils.audit import log_action
    log_action(signed_name, "offer_signed", "employee_offers", offer["id"], {"ip_address": ip})

    # Notify HR — the offer now needs their countersignature before the NDA goes out
    countersign_url = url_for("offers.review_ui", offer_id=offer["id"], _external=True)
    mailer.send_offer_awaiting_countersign(_hr_notify_email(), offer["candidate_name"], countersign_url)
    create_notification("HR", "offer_signed", f"Candidate {offer['candidate_name']} signed the offer — awaiting your countersignature", countersign_url)

    return jsonify({"success": True})


# =====================================================================
# PUBLIC E-SIGN — NDA (auto-sent after offer is fully countersigned)
# =====================================================================

def _lookup_nda_by_token(token):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("SELECT * FROM employee_ndas WHERE sign_token=%s", (token,))
        return cur.fetchone()
    except Exception as e:
        print("Error looking up NDA by token via DB, trying REST:", e)
        try:
            return supabase_rest.get_first_row("employee_ndas", {"sign_token": f"eq.{token}"})
        except Exception as rest_err:
            print("REST fallback for NDA token lookup failed:", rest_err)
            return None
    finally:
        if conn:
            release_db(conn, cur)


def _get_employee(employee_id):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("SELECT * FROM hrms_employees WHERE id=%s", (employee_id,))
        return cur.fetchone()
    except Exception as e:
        print("Error fetching employee via DB, trying REST:", e)
        try:
            return supabase_rest.get_first_row("hrms_employees", {"id": f"eq.{employee_id}"})
        except Exception as rest_err:
            print("REST fallback for get employee failed:", rest_err)
            return None
    finally:
        if conn:
            release_db(conn, cur)


def _update_nda(nda_id, fields):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        set_clause = ", ".join(f"{k}=%s" for k in fields)
        cur.execute(f"UPDATE employee_ndas SET {set_clause} WHERE id=%s", (*fields.values(), nda_id))
        conn.commit()
        return True
    except Exception as e:
        print("Error updating NDA via DB, trying REST:", e)
        try:
            supabase_rest.update_rows("employee_ndas", {"id": f"eq.{nda_id}"}, fields)
            return True
        except Exception as rest_err:
            print("REST fallback for update NDA failed:", rest_err)
            return False
    finally:
        if conn:
            release_db(conn, cur)


@offers_public_bp.route("/nda/<token>", methods=["GET"])
def sign_nda(token):
    nda = _lookup_nda_by_token(token)
    if not nda:
        return render_template("esign_invalid.html", reason="not_found", doc="nda")
    if nda["status"] in ("Signed", "Countersigned"):
        return render_template("esign_invalid.html", reason="already_signed", doc="nda")
    if _token_expired(nda.get("sign_token_expires_at")):
        return render_template("esign_invalid.html", reason="expired", doc="nda")
    return render_template("esign_nda.html", nda=nda, token=token)


@offers_public_bp.route("/nda/<token>", methods=["POST"])
def submit_nda_signature(token):
    nda = _lookup_nda_by_token(token)
    if not nda or nda["status"] != "Sent":
        return jsonify({"error": "This NDA is no longer available for signature."}), 400

    signed_name = (request.form.get("signed_name") or "").strip()
    if not signed_name:
        return jsonify({"error": "Please type your full legal name to sign."}), 400
    if not request.form.get("agree"):
        return jsonify({"error": "Please confirm you accept the NDA."}), 400

    signed_at = datetime.utcnow()
    ip = _client_ip()
    final_html = nda["content_html"] + _signature_block("Receiving Party Signature", signed_name, signed_at, ip)

    _update_nda(nda["id"], {
        "status": "Signed", "signed_name": signed_name, "signed_at": signed_at.isoformat(),
        "signed_ip": ip, "content_html": final_html,
    })

    employee = _get_employee(nda["employee_id"])
    countersign_url = url_for("offers.nda_review_ui", nda_id=nda["id"], _external=True)
    mailer.send_nda_awaiting_countersign(_hr_notify_email(), employee["full_name"] if employee else "Candidate",
                                          countersign_url)
    create_notification("HR", "nda_signed", f"NDA signed by {employee['full_name'] if employee else 'Candidate'} — awaiting your countersignature", countersign_url)

    return jsonify({"success": True})


def _get_nda(nda_id):
    conn, cur = None, None
    try:
        conn, cur = get_db(True)
        if not conn:
            raise Exception("no db")
        cur.execute("SELECT * FROM employee_ndas WHERE id=%s", (nda_id,))
        return cur.fetchone()
    except Exception as e:
        print("Error fetching NDA via DB, trying REST:", e)
        try:
            return supabase_rest.get_first_row("employee_ndas", {"id": f"eq.{nda_id}"})
        except Exception as rest_err:
            print("REST fallback for get NDA failed:", rest_err)
            return None
    finally:
        if conn:
            release_db(conn, cur)


@offers_bp.route("/nda/<nda_id>/review/ui", methods=["GET"])
@login_required
def nda_review_ui(nda_id):
    if not hr_admin_required():
        return redirect("/dashboard")
    nda = _get_nda(nda_id)
    if not nda:
        return redirect("/hrms/offers/")
    employee = _get_employee(nda["employee_id"])
    return render_template("hrms/nda_review.html", nda=nda, employee=employee)


@offers_bp.route("/nda/<nda_id>/countersign", methods=["POST"])
@login_required
def countersign_nda(nda_id):
    """HR types their name to countersign the NDA once the candidate has signed it —
    this is the point where the onboarding invite fires automatically."""
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403
    nda = _get_nda(nda_id)
    if not nda or nda["status"] != "Signed":
        return jsonify({"error": "This NDA isn't awaiting HR countersignature."}), 400

    hr_name = (request.form.get("hr_signed_name") or session.get("user") or "HR").strip()
    if not hr_name:
        return jsonify({"error": "Please type your name to countersign."}), 400

    hr_block = f"""\
<h3>Disclosing Party Countersignature</h3>
<table>
<tr><td>Countersigned By</td><td>{hr_name}</td></tr>
<tr><td>Countersigned At</td><td>{datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}</td></tr>
</table>
"""
    final_html = nda["content_html"] + hr_block
    employee = _get_employee(nda["employee_id"])
    pdf_url = _render_pdf_and_upload(
        final_html, f"nda_{(employee['full_name'] if employee else 'candidate').replace(' ', '_')}",
        doc_title="NON-DISCLOSURE AGREEMENT",
    )

    _update_nda(nda["id"], {
        "status": "Countersigned", "hr_signed_name": hr_name, "hr_signed_at": datetime.utcnow().isoformat(),
        "content_html": final_html, "pdf_url": pdf_url,
    })

    mailer.send_nda_signed_notice(_hr_notify_email(), employee["full_name"] if employee else "Candidate")
    create_notification("HR", "nda_countersigned", f"NDA fully signed for {employee['full_name'] if employee else 'Candidate'}", url_for("offers.nda_review_ui", nda_id=nda["id"]))

    # Auto-trigger the self-service onboarding invite — no manual "Send Invite" click.
    if employee:
        _fire_onboarding_invite(employee)

    return jsonify({"success": True})


@offers_bp.route("/bulk-csv-template", methods=["GET"])
@login_required
def bulk_csv_template():
    if not hr_admin_required():
        return redirect("/dashboard")
        
    import csv
    from io import StringIO
    from flask import make_response
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "candidate_name", "candidate_email", "candidate_phone", "candidate_address",
        "designation", "department", "offer_type", "role_name", "effective_date",
        "ctc_annual", "basic_monthly", "hra_monthly", "special_allowance_monthly",
        "pf_monthly", "bonus_monthly", "contract_end_date", "stipend_monthly",
        "duration_months", "responsibilities"
    ])
    writer.writerow([
        "John Doe", "john.doe@example.com", "9876543210", "123 Main St, Bangalore",
        "Software Engineer", "Engineering", "Full Time", "Employee", "2026-09-01",
        "1200000", "50000", "20000", "25000", "1800", "0", "", "",
        "", "Develop software applications"
    ])
    
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=bulk_onboarding_template.csv"
    response.headers["Content-Type"] = "text/csv"
    return response


@offers_bp.route("/import-bulk-csv", methods=["POST"])
@login_required
def import_bulk_csv():
    if not hr_admin_required():
        return jsonify({"error": "Unauthorized"}), 403
        
    csv_file = request.files.get("csv_file")
    if not csv_file or not csv_file.filename:
        flash("Please upload a valid CSV file.", "error")
        return redirect(url_for("offers.index"))
        
    import csv
    from io import StringIO
    
    try:
        raw_content = csv_file.read().decode("utf-8-sig")
        reader = csv.DictReader(StringIO(raw_content))
    except Exception as parse_e:
        flash(f"Failed to parse CSV file: {parse_e}", "error")
        return redirect(url_for("offers.index"))
        
    if not reader.fieldnames:
        flash("CSV file has no headers.", "error")
        return redirect(url_for("offers.index"))
        
    conn, cur = None, None
    imported = 0
    skipped = 0
    skipped_reasons = []
    
    # 1. Fetch all roles once
    role_map = {}
    default_role_id = None
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("SELECT id, role_name FROM hrms_roles")
            roles = cur.fetchall()
            role_map = {str(r["role_name"]).lower().strip(): r["id"] for r in roles}
            if roles:
                default_role_id = roles[0]["id"]
                for r in roles:
                    if "unassigned" in str(r["role_name"]).lower():
                        default_role_id = r["id"]
                        break
    except Exception as db_err:
        print("DB roles fetch failed, trying REST:", db_err)
    finally:
        if conn:
            release_db(conn, cur)
            conn, cur = None, None
            
    if not role_map:
        try:
            roles = supabase_rest.get_rows("hrms_roles") or []
            role_map = {str(r["role_name"]).lower().strip(): r["id"] for r in roles}
            if roles:
                default_role_id = roles[0]["id"]
                for r in roles:
                    if "unassigned" in str(r["role_name"]).lower():
                        default_role_id = r["id"]
                        break
        except Exception as rest_err:
            print("REST roles fetch failed:", rest_err)

    # 2. Pre-fetch existing employee emails once (eliminates 1 query per row)
    existing_emails = set()
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("SELECT email FROM hrms_employees WHERE status != 'Deleted'")
            existing_emails = {str(row["email"]).lower().strip() for row in cur.fetchall() if row.get("email")}
    except Exception as db_err:
        print("DB existing emails fetch failed, trying REST:", db_err)
    finally:
        if conn:
            release_db(conn, cur)
            conn, cur = None, None
            
    if not existing_emails:
        try:
            rows = supabase_rest.get_rows("hrms_employees", {"status": "neq.Deleted", "select": "email"}) or []
            existing_emails = {str(row["email"]).lower().strip() for row in rows if row.get("email")}
        except Exception as rest_err:
            print("REST existing emails fetch failed:", rest_err)

    # 3. Pre-fetch last employee code sequence once (eliminates 1 query per row)
    last_num = 0
    try:
        conn, cur = get_db(True)
        if conn:
            cur.execute("SELECT employee_code FROM hrms_employees WHERE employee_code LIKE 'EMP-%' ORDER BY created_at DESC LIMIT 1")
            last_emp = cur.fetchone()
            if last_emp and last_emp["employee_code"]:
                last_num = int(last_emp["employee_code"].split("-")[1])
    except Exception as db_err:
        print("DB last employee code fetch failed, trying REST:", db_err)
    finally:
        if conn:
            release_db(conn, cur)
            conn, cur = None, None
            
    if last_num == 0:
        try:
            row_last = supabase_rest.get_first_row("hrms_employees", {"employee_code": "like.EMP-%", "order": "created_at.desc"})
            if row_last and row_last.get("employee_code"):
                last_num = int(row_last["employee_code"].split("-")[1])
        except Exception as rest_err:
            print("REST last employee code fetch failed:", rest_err)

    # Main Row Processing Loop
    for row in reader:
        name = (row.get("candidate_name") or "").strip()
        email = (row.get("candidate_email") or "").strip().lower()
        designation = (row.get("designation") or "").strip()
        role_name = (row.get("role_name") or "").strip().lower()
        
        if not name or not email or not designation:
            skipped += 1
            skipped_reasons.append("Row missing name/email/designation")
            continue
            
        # O(1) Local duplicate check (no DB roundtrip)
        if email in existing_emails:
            skipped += 1
            skipped_reasons.append(f"Email '{email}' already exists")
            continue
            
        # Resolve role_id
        resolved_role_id = role_map.get(role_name) or default_role_id
        offer_type = row.get("offer_type", "Full Time").strip()
        if offer_type not in OFFER_TYPES:
            offer_type = "Full Time"
            
        # Parse numeric fields
        def to_num(val):
            try: return float(str(val).replace(",", "").strip()) or 0.0
            except: return 0.0
            
        def to_int(val):
            try: return int(str(val).strip()) or None
            except: return None
            
        offer_fields = {
            "candidate_name": name,
            "candidate_email": email,
            "candidate_address": row.get("candidate_address") or None,
            "designation": designation,
            "department": row.get("department") or None,
            "offer_type": offer_type,
            "effective_date": row.get("effective_date") or None,
            "ctc_annual": to_num(row.get("ctc_annual")),
            "basic_monthly": to_num(row.get("basic_monthly")),
            "hra_monthly": to_num(row.get("hra_monthly")),
            "special_allowance_monthly": to_num(row.get("special_allowance_monthly")),
            "pf_monthly": to_num(row.get("pf_monthly")),
            "bonus_monthly": to_num(row.get("bonus_monthly")),
            "contract_end_date": row.get("contract_end_date") or None,
            "commission_min": to_num(row.get("commission_min")),
            "commission_max": to_num(row.get("commission_max")),
            "stipend_monthly": to_num(row.get("stipend_monthly")),
            "duration_months": to_int(row.get("duration_months")),
            "responsibilities": row.get("responsibilities") or "",
            "role_id": resolved_role_id
        }
        
        content_html = _render_offer_content(offer_fields)
        
        # Local employee code sequence calculation (no DB roundtrip)
        last_num += 1
        employee_code = f"EMP-{last_num:04d}"
                
        # Database Inserts (psycopg2 direct first, fallback to REST)
        db_success = False
        conn, cur = None, None
        try:
            conn, cur = get_db(True)
            if conn:
                cur.execute("""
                    INSERT INTO hrms_employees (employee_code, full_name, email, department, designation,
                        role_id, joining_date, status, employment_type)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'Offer Pending',%s) RETURNING id
                """, (employee_code, name, email, offer_fields["department"], designation, 
                      resolved_role_id, offer_fields["effective_date"] or date.today(), offer_type))
                employee_id = cur.fetchone()["id"]
                
                cur.execute("""
                    INSERT INTO employee_offers (employee_id, candidate_name, candidate_email, candidate_address,
                        designation, department, offer_type, effective_date, ctc_annual, basic_monthly, hra_monthly,
                        special_allowance_monthly, pf_monthly, bonus_monthly, contract_end_date, commission_min,
                        commission_max, stipend_monthly, duration_months, responsibilities,
                        content_html, status, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Draft',%s)
                """, (employee_id, name, email, offer_fields["candidate_address"], designation, 
                      offer_fields["department"], offer_type, offer_fields["effective_date"], 
                      offer_fields["ctc_annual"], offer_fields["basic_monthly"], offer_fields["hra_monthly"], 
                      offer_fields["special_allowance_monthly"], offer_fields["pf_monthly"], offer_fields["bonus_monthly"], 
                      offer_fields["contract_end_date"], offer_fields["commission_min"], offer_fields["commission_max"], 
                      offer_fields["stipend_monthly"], offer_fields["duration_months"], offer_fields["responsibilities"], 
                      content_html, session.get("email") or session.get("role") or "HR"))
                conn.commit()
                db_success = True
                imported += 1
                existing_emails.add(email) # Track local uniqueness
        except Exception as db_err:
            print("DB bulk insert failed, trying REST:", db_err)
            if conn:
                conn.rollback()
        finally:
            if conn:
                release_db(conn, cur)
                conn, cur = None, None
                
        # REST Fallback Inserts
        if not db_success:
            try:
                emp_payload = {
                    "employee_code": employee_code,
                    "full_name": name,
                    "email": email,
                    "department": offer_fields["department"],
                    "designation": designation,
                    "role_id": resolved_role_id,
                    "joining_date": offer_fields["effective_date"] or date.today().isoformat(),
                    "status": "Offer Pending",
                    "employment_type": offer_type
                }
                new_emp = supabase_rest.insert_row("hrms_employees", emp_payload)
                if new_emp and new_emp.get("id"):
                    employee_id = new_emp["id"]
                    offer_payload = {
                        "employee_id": employee_id,
                        "candidate_name": name,
                        "candidate_email": email,
                        "candidate_address": offer_fields["candidate_address"],
                        "designation": designation,
                        "department": offer_fields["department"],
                        "offer_type": offer_type,
                        "effective_date": offer_fields["effective_date"],
                        "ctc_annual": offer_fields["ctc_annual"],
                        "basic_monthly": offer_fields["basic_monthly"],
                        "hra_monthly": offer_fields["hra_monthly"],
                        "special_allowance_monthly": offer_fields["special_allowance_monthly"],
                        "pf_monthly": offer_fields["pf_monthly"],
                        "bonus_monthly": offer_fields["bonus_monthly"],
                        "contract_end_date": offer_fields["contract_end_date"],
                        "commission_min": offer_fields["commission_min"],
                        "commission_max": offer_fields["commission_max"],
                        "stipend_monthly": offer_fields["stipend_monthly"],
                        "duration_months": offer_fields["duration_months"],
                        "responsibilities": offer_fields["responsibilities"],
                        "content_html": content_html,
                        "status": "Draft",
                        "created_by": session.get("email") or session.get("role") or "HR"
                    }
                    new_offer = supabase_rest.insert_row("employee_offers", offer_payload)
                    if new_offer:
                        db_success = True
                        imported += 1
                        existing_emails.add(email) # Track local uniqueness
            except Exception as rest_err:
                print("REST bulk insert failed:", rest_err)
                skipped += 1
                skipped_reasons.append("Insert failed")

    if skipped > 0:
        flash(f"Successfully imported {imported} offer(s) from CSV. Skipped {skipped} rows. Reasons: {'; '.join(skipped_reasons[:3])}", "warning")
    else:
        flash(f"Successfully imported {imported} offer(s) from CSV.", "success")
        
    return redirect(url_for("offers.index"))
