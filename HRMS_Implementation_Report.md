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

Ensure local server is active:
```bash
python app.py
```

### 1. Test Admin Dashboard Loading (Task 13)
1. Login as `admin@company.com`.
2. Navigate to **Dashboards** on the left menu.
3. Verify that the page loads completely without any error banners.
4. Verify that:
   * Gmail Quota gauge renders live statistics.
   * Document Hub count correctly displays offers, NDAs, and signed policy counts.
   * The Hiring Funnel chart groups applicant counts accurately.
   * Time-to-hire metrics and recent logs are displayed.

### 2. Test Data Retention Auto-Purge & Storage Deletion (Task 14)
1. Navigate to **Settings** as `admin@company.com`.
2. Set **Candidate Data Retention** to `12` months and save.
3. Run the verification script:
   ```bash
   venv\Scripts\python.exe scratch/test_retention.py
   ```
4. Verify from output that:
   * Rejected candidates older than 12 months are identified.
   * Storage delete requests are fired to clean up the Supabase PDF files.
   * Profiles have name set to `'Anonymized'`, phone/notes set to `NULL`, and email randomized.
   * `candidate_pii_purged` record is inserted under the system audit logs.

### 3. Test Sensitive-Action Approval Gating (Task 2)
1. Login as HR user (`hr@company.com`).
2. Go to **Offer Letters** -> **Edit Templates**.
3. Edit the Full Time Offer template and click **Save Changes**.
4. Log back in as `admin@company.com`.
5. Navigate to **Approval Requests** on the sidebar.
6. Verify that the template edit request is pending. Click **Review**, examine the JSON side-by-side differences, and approve.
7. Verify that the changes are now live and logged in **Audit Logs**.

---

## 📊 6. Sign-off Status
* All 15 active roadmap requirements are fully coded, verified, and committed.
* System database schema drift has been completely resolved.
* Security credentials, background workers, and templates are structured following best practices.
