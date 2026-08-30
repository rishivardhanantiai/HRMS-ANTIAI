# HRMS Project Implementation Report
**Comprehensive Handoff and Technical Handoff Document**

This document details the completed implementation of the **HR Communication Hub & System Expansion** (Tasks 1–16). It covers all database schema upgrades, architectural patterns, user navigation paths, technical approaches, and manual testing procedures.

---

## 📌 1. Architectural Decisions & Tech Stack

### Dual-Path Database Pattern
Every database-facing service in this cycle implements a dual-path pattern to guarantee maximum reliability:
1. **Direct Connection:** Try to execute query via `psycopg2` using a direct PostgreSQL connection (`utils/db.py`).
2. **REST API Fallback:** If `psycopg2` raises an exception (e.g. database connection pools are saturated or network is flaky), the application transparently falls back to the custom Supabase REST wrapper (`utils/supabase_rest.py`).

### Encryption at Rest for Sensitive Tokens (Task 6)
To secure the Google Calendar API credentials:
* **Symmetric Encryption:** We use `cryptography.fernet.Fernet`.
* **Key Derivation:** The key is derived by running the Flask app's `SECRET_KEY` through SHA256, encoded as base64.
* **Storage:** Raw tokens are never stored plaintext in PostgreSQL; they are encrypted before write and decrypted transparently on query (`utils/encryption.py`).

### Background Task Scheduler (Task 4, 11, 14)
* Powered by `APScheduler` running in the main Flask thread.
* **Announcements Sender:** Polls `outbound_messages` every 30 seconds and handles rate throttling (maximum 10 sends/batch) to protect the Gmail daily send limit.
* **Lifecycle Reminders:** Scans active employee profiles daily at midnight to notify HR of probation completions and anniversaries.
* **PII Purge Policy:** Automatically deletes rejected candidates' resumes from Supabase Storage and anonymizes candidate profiles older than the configured threshold daily.

---

## 🗄️ 2. Database Schema Migrations

The following database changes have been applied to the PostgreSQL/Supabase database.

```sql
-- Task 1: Notifications
CREATE TABLE IF NOT EXISTS notifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_role text NOT NULL,
    employee_id uuid REFERENCES hrms_employees(id) ON DELETE CASCADE,
    type text NOT NULL,
    message text NOT NULL,
    link text,
    read_at timestamptz,
    created_at timestamptz DEFAULT now()
);

-- Task 2: Admin Approval Queue
CREATE TABLE IF NOT EXISTS admin_approval_queue (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type text NOT NULL,
    target_table text,
    target_id uuid,
    payload_before jsonb,
    payload_after jsonb NOT NULL,
    requested_by text NOT NULL,
    status text NOT NULL DEFAULT 'Pending',
    admin_comment text,
    resolved_by text,
    resolved_at timestamptz,
    created_at timestamptz DEFAULT now()
);

-- Task 3 & 5: Candidate Interviews (ICS & Google Event ID)
CREATE TABLE IF NOT EXISTS candidate_interviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid REFERENCES hrms_employees(id) ON DELETE CASCADE,
    application_id uuid REFERENCES applications(id) ON DELETE CASCADE,
    scheduled_at timestamptz NOT NULL,
    duration_minutes integer NOT NULL DEFAULT 45,
    location text NOT NULL,
    ics_uid text NOT NULL,
    ics_sequence integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'Scheduled',
    scheduled_by text NOT NULL,
    google_event_id text,
    created_at timestamptz DEFAULT now()
);

-- Task 4: Bulk Mail Queue
CREATE TABLE IF NOT EXISTS message_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    subject text NOT NULL,
    body_html text NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS outbound_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject text NOT NULL,
    body_html text NOT NULL,
    recipient_email text NOT NULL,
    status text NOT NULL DEFAULT 'Queued',
    created_by text NOT NULL,
    sent_at timestamptz
);

-- Task 5: ATS Kanban Integration Columns
ALTER TABLE applications ADD COLUMN IF NOT EXISTS owner text;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS notes text;
ALTER TABLE employee_offers ADD COLUMN IF NOT EXISTS application_id uuid REFERENCES applications(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);

-- Task 6: Google OAuth Tokens
CREATE TABLE IF NOT EXISTS google_calendar_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email text UNIQUE NOT NULL,
    access_token text NOT NULL,
    refresh_token text,
    token_uri text NOT NULL,
    client_id text NOT NULL,
    client_secret text NOT NULL,
    scopes text[],
    expiry timestamptz NOT NULL,
    created_at timestamptz DEFAULT now()
);

-- Task 8: Holidays List
CREATE TABLE IF NOT EXISTS company_holidays (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    holiday_date date NOT NULL UNIQUE,
    created_at timestamptz DEFAULT now()
);

-- Task 9: Helpdesk & Compliance Policy Signatures
CREATE TABLE IF NOT EXISTS employee_queries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid REFERENCES hrms_employees(id) ON DELETE CASCADE,
    subject text NOT NULL,
    description text NOT NULL,
    status text NOT NULL DEFAULT 'Open',
    hr_response text,
    created_at timestamptz DEFAULT now(),
    resolved_at timestamptz
);

CREATE TABLE IF NOT EXISTS policy_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title text NOT NULL,
    content_html text NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS employee_policy_signatures (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid REFERENCES hrms_employees(id) ON DELETE CASCADE,
    policy_id uuid REFERENCES policy_documents(id) ON DELETE CASCADE,
    signed_name text,
    signature_ip text,
    signed_at timestamptz,
    status text NOT NULL DEFAULT 'Pending',
    pdf_url text,
    created_at timestamptz DEFAULT now()
);

-- Task 10: Offboarding Cases
CREATE TABLE IF NOT EXISTS offboarding_cases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid REFERENCES hrms_employees(id) ON DELETE CASCADE UNIQUE,
    last_working_day date NOT NULL,
    exit_interview_status text NOT NULL DEFAULT 'Not Scheduled',
    asset_return_status text NOT NULL DEFAULT 'Pending',
    final_settlement_status text NOT NULL DEFAULT 'Pending',
    access_revoked boolean DEFAULT false,
    notes text,
    created_at timestamptz DEFAULT now()
);

-- Task 12: Corporate Audit log & Settings
CREATE TABLE IF NOT EXISTS audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor text NOT NULL,
    action text NOT NULL,
    target_table text,
    target_id text,
    details jsonb,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC);

ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS offer_logo_wordmark_b64 text;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS offer_watermark_b64 text;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS offer_watermark_opacity numeric DEFAULT 0.15;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS offer_watermark_width_cm numeric DEFAULT 10.0;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS offer_logo_width_px numeric DEFAULT 150.0;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS candidate_retention_months integer DEFAULT 12;
```

---

## 🧭 3. Feature Mapping & UI Navigation

The dashboard adjusts layout automatically depending on the authenticated role.

| Task | Feature Description | Role Scopes | Sidebar / Navigation Path |
| :--- | :--- | :--- | :--- |
| **Task 1** | In-app Notification Feed | HR, Admin, Employee | Top Navbar (Bell Icon 🔔 Dropdown) |
| **Task 2** | Sensitive-Action Approval Queue | Admin | Sidebar: **Approval Requests** |
| **Task 3** | ICS Mail Calendar Invites | HR | Sidebar: **Interviews** |
| **Task 5** | Pre-Offer Candidate Pipeline (Kanban) | HR | Sidebar: **Candidate Pipeline** |
| **Task 6** | Real Google Calendar OAuth Sync | Admin | Sidebar: **Calendar Setup** |
| **Task 7** | Employee Portal (Payslips & Documents) | Employee | Sidebar: **My Documents** / **My Payroll** |
| **Task 8** | Directory & Holiday Schedule | All Users | Sidebar: **Directory** / **Holidays** |
| **Task 9** | Helpdesk & Compliance E-Signatures | Employee, HR | Sidebar: **Helpdesk** / **Company Policies** |
| **Task 10** | Offboarding Workflow Checklist | HR | Sidebar: **Exit Management** |
| **Task 11** | Bulk CSV Upload / Candidate Email Check | HR | Pipeline Headers / Kanban Add Form |
| **Task 12** | Logins CRUD / Branding Config / System Logs | Admin | Sidebar: **User Logins** / **Settings** / **Audit Logs** |
| **Task 13** | Quotas Gauges & Strategic Funnel Graphs | Admin | Sidebar: **Dashboards** |
| **Task 14** | Auto-Purge Policy Slider | Admin | Sidebar: **Settings** (Data Retention Setting) |
| **Task 16** | Service Worker Cache / Mobile Top Bar | All Users | Adaptive Top-Nav Bar on `< 992px` width |

---

## 🛠️ 4. Task Implementations & Recent Fixes

### Task 1: Notifications
* **Approach:** Intercepts `mailer.send_*()` emails. Writes in-app records for target roles ('HR' or 'Admin') or individuals (via `employee_id` for employee notifications).
* **UI:** Standard interactive navbar dropdown pulling `/hrms/notifications/api/feed` periodically.

### Task 2: Approval Queue
* **Approach:** HR updates to corporate parameters, offer deletion requests, and bulk emails are diverted into `admin_approval_queue`. Diffs are computed client-side by comparing before/after JSON blobs in the Admin Review interface.
* **Actions Supported:** `template_edit`, `appearance_change`, `delete_offer`, `delete_candidate`, `company_settings_change`, `bulk_send`.

### Task 3: Meeting / Interview Invites (.ics)
* **Approach:** Utilizes `icalendar` library. Packages calendar invitation headers with MIME `text/calendar; method=REQUEST`. Increments `ics_sequence` for rescheduling updates, and sends `METHOD:CANCEL` for cancellations to preserve calendar sync integrity.

### Task 5: ATS Candidate Pipeline
* **Approach:** Reused the core `applications` table to prevent table duplication. Linked candidates directly to `employee_offers` (`application_id`) so that dragging a candidate to "Offer Extended" opens a pre-filled offer creation form that maintains historical tracking.

### Task 6: Google Calendar OAuth Integration
* **Approach:** Integrated Google API Client. Resolved the `invalid_grant: Missing code verifier` issue by setting `autogenerate_code_verifier=False` inside Flow generation, preventing the stateless backend callback from destroying verification states. Configured `OAUTHLIB_INSECURE_TRANSPORT=1` to allow local HTTP testing.
* **Fallbacks:** Automatically reverts to the Task 3 SMTP ICS email format if OAuth state is not active.

### Task 7: Employee Self-Service
* **Approach:** Modified `/my-documents` to scan `employee_offers` and `employee_ndas` to download their signed PDFs directly. Pulled employee compensation progression history cleanly from `employee_salary`.

### Task 8: Company Directory & Holiday Calendar
* **Approach:** Directory runs a hierarchical self-join (`manager_id` references `hrms_employees.id`) to render organizational structures. Company holiday database handles additions/deletions on an interactive timeline.

### Task 9: Helpdesk & Policy E-Signatures
* **Approach:** Helpdesk is role-scoped (Open/In Progress/Resolved states). Policies allow HR to upload documents and assign them to active employees. E-signatures use a secure sign-off view that captures legal names, agree checks, IP address, and timestamps. Renders a signed PDF with countersignature boxes, uploads it to Supabase Storage, and adds it to the employee's document vault.

### Task 10: Offboarding Workflow
* **Approach:** Checklist manages last working day, exit interview scheduler (ICS-linked), asset return checkboxes, and final settlement logs. The "Revoke Access" toggle removes login credentials from the `hrms_users` credentials table.

### Task 11: HR Operational Extras
* **Lifecycle Reminders:** Scans anniversaries and probation dates daily, writing targeted notifications to HR/Admin 7 days in advance.
* **Bulk CSV Import:** Parses candidate attributes, creates draft offers, and registers placeholders in the database.
* **Duplicate Detection:** Asynchronous AJAX check at `/hrms/candidates/check-email` alerts HR if candidate exists before saving.

### Task 12: Admin Control Center
* **Audit Trail:** Custom Paginated log view tracking logins, deletions, stage updates, email logs, and admin queue results.
* **Logins CRUD:** Admin UI to assign logins, reset passwords, change roles, and link employee IDs.
* **Settings:** Gathers branding logo and watermark templates. Gated under Task 2 approval controls.

### Task 13: Usage/Quota & Analytics Dashboard
* **Bug Fix:** Fixed database crash where queries searched for the outdated column name `pdf_url` inside `employee_offers`/`employee_ndas` tables. Updated schema queries to target `final_pdf_url`.
* **Bug Fix:** Fixed database exception where queries checked for `signature_pdf_url` in `employee_policy_signatures`. Updated template logic and route query to target `pdf_url` (matching the schema definition).
* **Metrics:** Evaluates daily SMTP limits, database tuples size, conversion rate metrics, and average days time-to-hire.

### Task 14: Data Retention Policy & Storage Purge
* **Bug Fix:** Implemented physical file deletion alongside database nullification.
* **Storage Sync:** The purge job parses `resume_url`. If it contains matching Supabase bucket markers, it extracts the unique object key (e.g. `resumes/1788106857_abc.pdf`) and executes a secure HTTP `DELETE` call to the Supabase storage endpoint before updating candidate records to `Anonymized`.

### Task 16: Mobile UI & PWA Pass
* **Approach:** Built responsive header shell (`.top-nav`) on screens `< 992px` with a rotating, interactive CSS burger icon to open the navigation panel. Fixed touch scroll overflows on HTML table elements to resolve mobile overflow clipping. Integrated a manifest and custom caching service worker (`sw.js`).

---

## 🧪 5. Verification & Testing Playbook

To verify all implementations, ensure your local server is active:
```bash
python app.py
```

---

### Task 1: Notification Inbox
1. **Trigger Action:** Log in as HR (`hr@company.com`) and submit a template edit for approval under **Offer Letters** -> **Edit Templates**.
2. **Verify Admin Feed:** Log in as Admin (`admin@company.com`). Verify that the top-navbar Bell Icon displays a red unread badge. Click the bell to view the dropdown containing *"Template edit awaiting your review"*.
3. **Verify Employee Feed:** Log in as HR and approve a leave request for an employee. Log in as that Employee and verify the notification feed shows *"Your leave request has been Approved"*.

### Task 2: Sensitive-Action Approval Queue
1. **Trigger Action (HR):** Log in as HR (`hr@company.com`). Navigate to **Settings** or **Offer Letters -> Edit Templates**. Make a change and click Save.
2. **Verify Queue Status:** Observe that the UI returns a *"Submitted for approval"* message instead of saving directly.
3. **Verify Admin Review:** Log in as Admin (`admin@company.com`). Navigate to **Approval Requests** in the sidebar. Click **Review** on the pending request to inspect the JSON payload changes. Click **Approve**.
4. **Verify Live Output:** Verify that the setting/template change is now live and active.

### Task 3: Meeting / Interview Invites (.ics)
1. **Trigger Scheduling:** Log in as HR. Navigate to **Interviews** on the sidebar and click **Schedule Interview** (or click the button on a candidate's review screen). Fill in date, time, duration, and candidate email, and click submit.
2. **Verify Attachment:** Check the terminal console logs or destination inbox. Verify that an email is dispatched containing a native `.ics` file attachment with headers `Content-Type: text/calendar; method=REQUEST` and a stable `UID`.
3. **Verify Reschedule/Cancel:** Under **Interviews**, click **Edit** (reschedules and increments `ics_sequence`) or **Cancel** (dispatches cancel update). Verify the candidate's calendar updates/cancels the invitation automatically.

### Task 4: Announcements & Bulk Composer
1. **Draft and Send:** Log in as HR. Navigate to **Announcements** on the sidebar. Choose a template, customize content, select recipient type **All Active**, and click **Send**.
2. **Verify Approval Gating:** Because this is a bulk send, verify it is redirected to the Admin Approval Queue (Task 2). Log in as Admin and approve it.
3. **Verify Scheduler Throttling:** Once approved, inspect the Python terminal execution console. Verify that the `APScheduler` background job pulls the queued messages and dispatches them in batches (maximum 10 sends every 30 seconds) to stay well under the daily 500-send cap.

### Task 5: Pre-Offer Candidate Pipeline (Kanban)
1. **Create Candidate:** Log in as HR. Navigate to **Candidate Pipeline**. Click **Add Candidate** and save.
2. **Kanban Transition:** Drag and drop (or select from the dropdown) the candidate across stages: *Applied* ➡️ *Screening* ➡️ *Interview Scheduled* ➡️ *Offer Extended*.
3. **Trigger Offer:** Transition the candidate to **Offer Extended**. Click **Move to Offer** on their card. Verify that it opens the new offer creation page with candidate name, email, and designation pre-filled.

### Task 6: Google Calendar OAuth Sync
1. **Setup Connection:** Log in as Admin. Navigate to **Calendar Setup**. Click **Connect Google Calendar** and complete the OAuth authentication screen.
2. **Verify Calendar Sync:** Schedule a candidate interview. Verify that:
   * The meeting is inserted directly onto the primary Google Calendar of the connected account.
   * Google automatically dispatches calendar invites to both the candidate and interviewer.
3. **Verify Disconnection/Fallback:** Click **Disconnect** on the setup screen. Schedule another interview. Verify that the system falls back cleanly to the Task 3 SMTP mailer attaching custom `.ics` files.

### Task 7: Employee Self-Service
1. **Verify Documents:** Log in as an Employee. Navigate to **My Documents**. Verify that signed copies of your Offer Letter and NDA are listed and can be downloaded.
2. **Verify Timeline:** Navigate to **My Payroll**. Verify that your salary progression history is retrieved from the database and formatted cleanly.

### Task 8: Company Directory & Holiday Calendar
1. **Verify Directory:** Log in and navigate to **Directory**. Enter a name in the search box to check search filtering. Verify that employee cards show manager relationships correctly.
2. **Verify Holidays:** Navigate to **Holidays** to view the timeline.
3. **Manage Holidays:** Log in as Admin. Add a holiday in the side form and verify it renders instantly. Delete a holiday and verify it is removed cleanly.

### Task 9: Helpdesk & Policy E-Signatures
1. **Query Ticket:** Log in as an Employee. Go to **Helpdesk** and submit a question.
2. **HR Response:** Log in as HR. Go to **Helpdesk** (HR screen at `/hrms/helpdesk/manage`), open the query, change status to *In Progress*, type a response, and click submit. Verify the employee sees the response.
3. **Policy Sign-off:** Log in as Admin. Go to **Company Policies** and upload a PDF/HTML document. Assign it to all active employees. Log in as an Employee, navigate to **Company Policies**, click **Sign**, check *"I Agree"*, type your legal name, and submit.
4. **Verify Document Vault:** Verify that a signed copy of the policy is generated, uploaded to Supabase Storage, and added to both the Document Hub and the employee's portal.

### Task 10: Offboarding Workflow
1. **Trigger Offboarding:** Log in as HR. Go to **Exit Management** and click **Manage** next to an employee.
2. **Task Checklist:** Verify exit interview scheduling triggers. Toggle asset return and final settlement checkboxes.
3. **Access Revocation:** Toggle **Revoke Login Access** to ON. Verify that the employee's login credentials are deleted from the `hrms_users` table, preventing them from logging back in.

### Task 11: HR Operational Extras
1. **Probation/Anniversary Reminders:** Run the python command to execute the daily scheduler checks. Verify that in-app notification alerts are generated for HR/Admin 7 days before probation ends or a work anniversary arrives.
2. **Bulk CSV Import:** Navigate to **Offer Letters -> Offers Pipeline**. Download the CSV template, populate it, and upload it at **Import Bulk CSV**. Verify that shell candidate profiles and draft offers are successfully created.
3. **Duplicate Candidate Warning:** Go to **Candidate Pipeline**. Click **Add Candidate** and type an existing candidate's email. Verify that an AJAX warning badge flashes on screen indicating the candidate already exists in the database.

### Task 12: Admin Control Center
1. **User Logins:** Log in as Admin. Go to **User Logins**. Create a new login, update its password, connect it to an employee profile, change roles (HR/Admin), and delete it.
2. **System Audit Logs:** Go to **Audit Logs**. Verify that all actions (logins, deletions, template edits, stage updates, and approvals) are logged chronologically with search and pagination controls.

### Task 13: Usage/Quota & Analytics Dashboards
1. **Verify Load:** Log in as Admin. Go to **Dashboards**.
2. **Verify Metrics:** Confirm that:
   * Gmail Quota meter operates and tracks daily email delivery limits.
   * Document Hub aggregates counts for stored offers, NDAs, and signed policies.
   * Kanban recruitment metrics are parsed and grouped correctly.
   * Average days time-to-hire evaluates from actual database records.

### Task 14: Data Retention & Candidate Purge
1. **Adjust Retention Window:** Log in as Admin. Go to **Settings** and set Candidate Data Retention to `12` months.
2. **Verify Purge:** Run the verification test script:
   ```bash
   venv\Scripts\python.exe scratch/test_retention.py
   ```
3. **Confirm Obfuscation:** Verify that rejected candidates older than 12 months are anonymized (name set to `'Anonymized'`, email randomized, and phone/resume cleared to `NULL`), their PDF file is deleted from Supabase Storage, and a `candidate_pii_purged` record is logged in the Audit Trail.

### Task 15: Granular Role Permissions
* **Status:** **NOT IMPLEMENTED** (Deferred/On Hold per project roadmap, current HR/Admin roles are sufficient for current team scale).

### Task 16: Mobile UI & PWA Pass
1. **Service Worker:** Load the application, open Developer Tools -> Application -> Service Workers, and verify `sw.js` is registered.
2. **Responsive Mobile Shell:** Resize browser window to `< 992px`. Verify that:
   * A fixed header top-bar renders.
   * Clicking the animated burger icon rotates it to a close ("X") icon and slides open the sidebar menu overlay.

---

## 📊 6. Sign-off Status
* All 15 active roadmap requirements are fully coded, verified, and committed.
* System database schema drift has been completely resolved.
* Security credentials, background workers, and templates are structured following best practices.

