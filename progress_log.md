# HRMS Project Progress Log

## 📅 Google Calendar OAuth Integration Guide

To configure the Google Calendar integration for development or production deployment, complete the following setup:

### 1. Google Cloud Console Configuration
1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Select your project and enable the **Google Calendar API**.
3. Configure the **OAuth Consent Screen**:
   - **User Type:** Set to `External`.
   - **Publishing Status:** Keep in `Testing` mode (allows up to 100 test users without requiring Google app verification).
   - **Test Users:** Under the Test Users section, add the email address of the shared HR Gmail account that will be integrated.
4. Create Credentials:
   - Click **+ Create Credentials** -> select **OAuth client ID**.
   - **Application Type:** Select `Web application`.
   - **Authorized JavaScript origins:**
     - Local Dev: `http://localhost:5000`
     - Production: `https://<your-production-domain>.com`
   - **Authorized redirect URIs:**
     - Local Dev: `http://localhost:5000/hrms/admin/calendar/oauth2callback`
     - Production: `https://<your-production-domain>.com/hrms/admin/calendar/oauth2callback`
5. Click **Create** and download the client credentials JSON.

### 2. Project File Placement
* Rename the downloaded JSON file to `client_secrets.json`.
* Save it under the `/utils/` folder: `utils/client_secrets.json`.

---


## Resolved Issues
*   **Fix `AttributeError: 'tuple' object has no attribute 'get'` during HR Countersignature:**
    *   **Root Cause:** The `_render_pdf_and_upload` function was opening a database connection using `get_db()` instead of `get_db(True)`. This caused the `_get_company` function to return a tuple instead of a dictionary. When the code tried to use `.get()` on the tuple to retrieve the company watermark/logo, it threw a 500 error.
    *   **Fix:** Updated the database connection inside `_render_pdf_and_upload` (in `hrms/offers/routes.py`) to explicitly request a dictionary cursor (`get_db(True)`). This ensures the company settings are always returned as a dictionary, preventing the crash when HR tries to countersign an offer.
    *   **Note:** This was not mentioned in the original Handoff Document.

*   **Fix Schema Drift (Salary data loss on candidate activation):**
    *   **Root Cause:** The `activate` route in `hrms/onboarding/routes.py` converted an onboarding candidate to an 'Active' employee but failed to transfer the compensation data from the `employee_offers` table over to the core HRMS `employee_salary` and `employee_salary_components` tables.
    *   **Fix:** Modified the `activate` route to fetch the latest executed offer for the activated candidate. If `ctc_annual` is greater than 0, it deletes any placeholder salary rows and inserts the `annual_ctc`, `monthly_salary`, and all component breakdowns (Basic, HRA, Special Allowance, etc.) into `employee_salary` and `employee_salary_components`. It handles this natively in SQL and has a complete REST API fallback for the cloud database.

*   **Fix Task 4 Announcement Email Rendering (PDF/Attachment bug):**
    *   **Root Cause:** The `send_message` route and scheduler were passing raw text directly to `send_email()`. Because `send_email()` attaches a company logo (`image/png`) to the HTML body using `multipart/related`, email clients (like Outlook/Apple Mail) would get confused by the lack of an `<html>` tag referencing the image. They fell back to rendering the logo as an attachment (often mistaking it or hiding the body), which led to users reporting they received a "pdf instead of the actual body."
    *   **Fix:** Updated `hrms/announcements/routes.py` and `hrms/announcements/scheduler.py` to wrap the raw user input using the standard `_wrap_html()` template from `utils.mailer` before passing it to `send_email()`.

*   **Fix Task 4 Bulk Send UI ("Local Message" popups):**
    *   **Root Cause:** The frontend JS for announcements used `alert()` implicitly through a poorly caught state, or the user desired a more seamless UI without blocking popups.
    *   **Fix:** Removed the reliance on toasts and external alerts in `announcements.html` and replaced it with inline DOM updates directly within the "Ready to send" modal. Changed the approval text to dynamically read "Approve Send" for bulk send actions in the approval queue UI.

## Completed Tasks

*   **Task 1: Notification Inbox (HR and Admin, different content)**
    *   **Database:** Created the `notifications` table (`schema_notifications.sql`) mapping notifications to roles ('HR' or 'Admin').
    *   **Backend:** Added `notifications_bp` in `hrms/notifications/routes.py` exposing `/api/feed` and `/api/mark-read`. Wrapped all transactional emails (like `mailer.send_*()` in offers/onboarding) to also insert an in-app notification row.
    *   **Frontend:** Added a bell icon and unread badge to the top nav in `base.html`, powered by a JavaScript fetch loop to display the feed.

*   **Task 2: Sensitive-Action Approval Queue**
    *   **Database:** Created `admin_approval_queue` table (`schema_approval_queue.sql`) to store pending changes and before/after payloads (JSON).
    *   **Backend Routing:** Created `approvals_bp` (`hrms/approvals/routes.py`) with a `create_approval_request()` function. 
    *   **Feature Integration:** Modified `save_template()`, `save_appearance()`, and `delete_offer()` in `hrms/offers/routes.py`. When an HR user performs these actions, they return "submitted for approval" and insert a row into the queue. When an Admin performs them, they execute synchronously and are immediately logged as "Approved" via the `auto_approve` flag for the audit trail.
    *   **Admin UI:** Added `approvals.html` (list of pending/history) and `approval_review.html` (side-by-side JSON diffs and template previews) for Admin review/resolution.

*   **Task 3: Meeting / Interview Invites (.ics)**
    *   **Database:** Added `candidate_interviews` table (`schema_interviews.sql`) using `gen_random_uuid()`.
    *   **Mailer Integration:** Updated `utils/mailer.py` with `send_meeting_invite` utilizing the `icalendar` library to generate and attach VEVENT objects with native email calendar invites.
    *   **Backend Routing:** Created `interviews_bp` in `hrms/interviews/routes.py` with endpoints for scheduling, rescheduling, and cancelling interviews. Re-using the same `ics_uid` with incrementing sequences handles seamless calendar updates.
    *   **Frontend UI:** Added the 'Interviews' link to the sidebar, created `interviews.html` for the HR team's overview of upcoming interviews (with edit/cancel controls), and added a 'Schedule Interview' button to `offer_review.html` that triggers a modal form.

*   **Task 4: Announcements & Bulk Composer**
    *   **Dependency:** Installed `APScheduler` to run a lightweight, free background task in the main Flask process.
    *   **Database:** Created `schema_announcements.sql` with `message_templates` and `outbound_messages` tables.
    *   **Backend & Scheduler:** Added `hrms/announcements/routes.py` for UI and sending logic. Added `hrms/announcements/scheduler.py` which polls `outbound_messages` for 'Queued' items and sends up to 10 emails every 30 seconds to respect Gmail limits.
    *   **Approval Queue Integration:** In `hrms/approvals/routes.py`, handled the `bulk_send` action type so that bulk announcements routed through the approval queue are automatically queued for the scheduler upon Admin approval.
    *   **Frontend UI:** Built `templates/hrms/announcements.html` composer to pick templates, pick recipient types (Single, Department, All, Custom), and write messages. Added the "Announcements" sidebar link in `base.html`.

## Pending Tasks (Roadmap)
*   [x] **Task 1:** Notification Inbox
*   [x] **Task 2:** Sensitive-Action Approval Queue
*   [x] **Task 3:** Meeting / Interview Invites (.ics)
*   [x] **Task 4:** Announcements & Bulk Composer
*   [x] **Task 5:** Pre-Offer Candidate Pipeline
*   [x] **Task 6:** Real Google Calendar Sync
*   [x] **Task 7:** Employee Self-Service Expansion (Leave, Payslips & Documents)
*   [x] **Task 8:** Company Directory, Announcements Feed & Holiday Calendar
*   [x] **Task 9:** Employee Help Desk & Policy Acknowledgment
*   [x] **Task 10:** Offboarding Workflow Checklist & Access Revocation
*   [x] **Task 11:** HR Operational Extras (Leave Approval, Lifecycle Reminders, Bulk Onboarding, Duplicate Candidate)
*   [x] **Task 12:** Admin Control Center (User logins management, Company settings approvals, and Audit logs)
*   [x] **Task 13:** Usage/Quota & HR Analytics Dashboards (Quota gauges, pipeline funnel, and metrics)
*   [x] **Task 14:** Data Retention & Deletion Policy (Candidate PII Purge)
*   [ ] **Task 15:** Granular Role Permissions (Put on hold / Deferred)
*   [x] **Task 16:** Mobile-Friendly / PWA Pass (Manifest, service worker, and mobile sidebar)

*   **Task 5 (ATS Pipeline) - SQL Migrations for Prod:**
    *   Per Kunal's architectural decision, we are not creating a new candidates table. Instead, we are upgrading the existing applications table and linking it to offers and interviews.
    *   **Action Required for Prod DB:** Run the following SQL to safely apply the Task 5 schema changes:

    ```sql
    -- 1. Add ATS columns to existing applications table
    ALTER TABLE applications ADD COLUMN IF NOT EXISTS owner text;
    ALTER TABLE applications ADD COLUMN IF NOT EXISTS notes text;

    -- 2. Add an index for fast filtering on the Kanban board and Inbox
    CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);

    -- 3. Link Offers back to the original application (Move to Offer)
    ALTER TABLE employee_offers ADD COLUMN IF NOT EXISTS application_id uuid REFERENCES applications(id) ON DELETE SET NULL;

    -- 4. Link Interviews to the application (so pre-offer candidates can be interviewed)
    ALTER TABLE candidate_interviews ADD COLUMN IF NOT EXISTS application_id uuid REFERENCES applications(id) ON DELETE CASCADE;
    ALTER TABLE candidate_interviews ALTER COLUMN employee_id DROP NOT NULL;
    ```

*   **Task 5 (ATS Pipeline) Completed:**
    *   Isolated the Inbox in applications by defaulting to Pending.
    *   Built the Kanban ATS Pipeline at /hrms/candidates using the existing applications table.
    *   Integrated Interview Scheduling and Offer generation to support pre-offer candidates via application_id.

*   **Task 7 (Employee Self-Service Expansion) Completed:**
    *   **Document Center Upgrade:** Extended /my-documents to query and show signed employment agreements (Offer Letters, NDAs) directly from employee_offers and employee_ndas tables.
    *   **Compensation Timeline:** Modified /my-payroll to pull and render a complete table of the employee's salary progression history from the employee_salary table, showing monthly changes and CTC.

*   **Task 8 (Company Directory, Announcements Feed & Holiday Calendar) Completed:**
    *   **SQL Migration:** Created the company_holidays table in database to track official corporate holidays.
    *   **Company Directory:** Built /hrms/employees/directory displaying employee cards with manager relationships (self-joined on hrms_employees) and a client-side search filter.
    *   **Announcements Feed:** Added /hrms/announcements/feed displaying a beautiful timeline of sent announcements matching the logged-in employee's email.
    *   **Holiday Calendar:** Built /hrms/leave/holidays listing the holidays in a timeline. Added an Admin-only management side-form allowing administrators (Admin role only, not HR) to add and delete entries dynamically.
    *   **Layout Integration:** Linked the new sections in templates/base.html for easy role-based access.

*   **Task 9 (Employee Help Desk & Policy Acknowledgment) Completed:**
    *   **SQL Migration:** Created tables employee_queries, policy_documents, and employee_policy_signatures to handle tickets and compliance signatures.
    *   **Help Desk:** Built the employee query portal (/hrms/helpdesk) and HR responder interface (/hrms/helpdesk/manage), complete with state updates (Open/In Progress/Resolved) and inline responses.
    *   **Policy Acknowledgment:** Built compliance dashboard (/hrms/policies/manage) for HR to add policy templates and assign them to all active employees. Built employee dashboard (/hrms/policies) to review pending policies.
    *   **Electronic Signature:** Built the policy sign-off page (/hrms/policies/esign/<sig_id>) capturing typed legal names, agree checkboxes, IP addresses, and timestamps. Integrates with _render_pdf_and_upload to generate and upload countersigned PDFs to Supabase Storage and register them in the Document Hub.

*   **Task 10 (Offboarding Workflow) Completed:**
    *   **SQL Migration:** Created table offboarding_cases to track offboarding checklists.
    *   **Offboarding Checklist UI:** Embedded a full offboarding checklist card into the existing exit management page (/hrms/exit/manage/<emp_id>), housing exit interview status, asset returns, final settlement progress, notes, and a toggle to revoke login access.
    *   **Exit Interview:** Reused the ICS scheduling and SMTP mailer infrastructure from Task 3 to schedule exit interviews, send out email calendar attachments, and link the events to the Interviews calendar.
    *   **Access Revocation:** Integrated the access toggle to programmatically delete credentials from the hrms_users login table, instantly deactivating employee account access.

*   **Task 11 (HR Operational Extras) Completed:**
    *   **SQL Migration:** Added column `employee_id` to the `notifications` table to support targeting individual employees for in-app notification alerts.
    *   **Employee Notifications Feed:** Enabled the top-nav notification bell in `base.html` for `Employee` role users, and updated `/api/feed` and `/api/mark-read` endpoints to display and mark employee-specific notifications.
    *   **Leave-Approval Queue Notifications:** Integrated notifications into the leave workflow: notifies HR (`leave_applied` type) when an employee submits a leave request, and notifies the specific employee (`leave_resolved` type) in their in-app feed when HR approves or rejects it.
    *   **Lifecycle Reminders Job:** Implemented `run_daily_reminders` in APScheduler that scans active employees daily and alerts HR/Admin roles 7 days in advance of a 3-month probation period end or a yearly work anniversary, with duplicate insertion prevention.
    *   **Bulk Onboarding (CSV Upload):** Added CSV bulk import at `/hrms/offers/import-bulk-csv` and template download at `/hrms/offers/bulk-csv-template`. The import creates employee shell profiles and draft offers in the pipeline from CSV rows, resolving roles by name. Linked UI buttons in `offers_pipeline.html` header.
    *   **Duplicate Candidate Detection:** Created `/hrms/candidates/check-email` API endpoint and added real-time AJAX input validation in the Kanban "Add Candidate" modal that displays a warning if the email exists. Added backend duplicate warning flashes on form submission.

*   **Task 12 (Admin Control Center) Completed:**
    *   **SQL Migration:** Created the `audit_log` table with indexes for fast descending timestamp sorting. Added missing letterhead document branding columns to `company_settings` (`offer_logo_wordmark_b64`, `offer_watermark_b64`, `offer_watermark_opacity`, `offer_watermark_width_cm`, `offer_logo_width_px`).
    *   **User Login Management:** Built a complete CRUD dashboard interface at `/hrms/admin/users` allowing Administrators to add new logins, change passwords, assign roles (HR/Admin), connect profiles to employees, and delete logins.
    *   **Company Settings Management & Approvals:** Built corporate configuration screen at `/hrms/admin/settings` to edit legal entity name, office address, contact number, website, logo, and watermark templates.
        - If executed by Admin, changes write immediately (`auto_approve=True` / direct DB write).
        - If executed by HR, changes submit as a pending sensitive request (`company_settings_change` type) in the approvals queue.
    *   **System-wide Audit Logs:** Created paginated compliance view at `/hrms/admin/audit-logs` that aggregates and logs logins, candidate additions, stage transitions, deletions, offer events (created, sent, signed, countersigned, deleted), and approval resolutions.
    *   **Layout Navigation:** Linked User Logins, Company Settings, and Audit Logs sections directly in `base.html` scoped by roles.

*   **Task 13 (Usage/Quota & HR Analytics Dashboards) Completed:**
    *   **Gmail SMTP Quota Tracking:** Implemented live email utilization tracker querying outbound messages sent today against the 500-email Gmail daily cap.
    *   **Document Hub & DB Counts:** Calculated stored candidate offers, NDAs, and policy agreement PDFs in Supabase storage, alongside counting the database active tuples size.
    *   **Hiring Funnel Analytics:** Aggregated conversion statistics showing candidates count in each pipeline stage (Screening, Interviewing, Selected, Backup, Future Reference, Rejected) from the applications database.
    *   **Key Performance Indicators (KPIs):** Evaluated historical Offer Acceptance Rate percentage and calculated Average Time-to-Hire days (from candidate application to offer creation/onboarding).
    *   **Dashboard View UI:** Built a state-of-the-art dark-mode dashboard at `templates/hrms/admin_dashboards.html` with real-time progress meters, metrics cards, funnel bar charts, and latest system audit activity logs. Linked section under `base.html` for Admin.

*   **Task 14 (Data Retention & Deletion Policy) Completed:**
    *   **SQL Migration:** Added configuration column `candidate_retention_months` (INTEGER, DEFAULT 12) to the `company_settings` table to customize Candidate PII retention windows without requiring code deploys.
    *   **Corporate Settings Integration:** Added a "Candidate Data Retention (Months)" input field to the `/hrms/admin/settings` panel, allowing Admins to adjust the policy threshold between 1 and 120 months.
    *   **Auto-Purge Background Job:** Created daily background job `run_candidate_pii_purge` in `hrms/announcements/scheduler.py` that identifies candidates in the terminal `'Rejected'` stage older than the configured threshold (e.g. 12 months).
    *   **Obfuscation & Anonymization:** Clears Candidate `name` (set to `'Anonymized'`), `phone` (NULL), `notes` (NULL), and `resume_url` (NULL), and obfuscates the candidate's `email` column (set to `'anonymized-' || id || '@example.com'`) to safely satisfy the database NOT-NULL constraints. Matches pipeline historical stats tracking while completely purging PII.
    *   **Audit Trail Compliance:** Logs a `candidate_pii_purged` compliance audit record under `audit_log` listing the target candidate ID and their original email address before purging.

*   **Task 15 (Granular Role Permissions) Deferred / On Hold:**
    *   **Status Update:** Put on hold per instruction and roadmap guidance. The current HR/Admin roles are sufficient for the current team size. Granular permissions will be re-evaluated after real usage patterns are established.

*   **Task 16 (Mobile-Friendly / PWA Pass) Completed:**
    *   **Progressive Web App support:** Created PWA specification at `/static/manifest.json` setting names, colors, display standalone mode, and maskable icons.
    *   **Service Worker:** Implemented network-first cache fallback worker at `/static/sw.js` for app loading reliability and caching of main CSS/JS assets.
    *   **Integration Headers:** Injected manifest references and service worker registration code inside `templates/base.html`, `templates/esign_offer.html`, and `templates/esign_nda.html`.
    *   **Mobile Nav Toggle:** Hooked Javascript click events in `/static/js/main.js` to toggle mobile sidebar overlays on layout size adjustments.

*   **Task 6 (Real Google Calendar Sync) Completed:**
    *   **SQL Migration:** Created table `google_calendar_tokens` to store encrypted credentials and added column `google_event_id` to the `candidate_interviews` table to link scheduling objects with Google API events.
    *   **Encryption at Rest:** Implemented `utils/encryption.py` utilizing the application's `SECRET_KEY` to derive a symmetric encryption key via SHA256 and base64. Fernet encrypts and decrypts OAuth tokens.
    *   **OAuth Flow & Setup UI:** Created the calendar setup screen at `/hrms/admin/calendar/setup` with connecting and disconnecting triggers. Redirects to Google consent screen requesting `offline` access (refresh tokens).
    *   **OAuth Troubleshooting & Fixes:**
        - **Insecure Transport Fix:** Configured `OAUTHLIB_INSECURE_TRANSPORT=1` environment variable in `.env`, `app.py`, `utils/google_calendar.py`, and `hrms/admin/routes.py` to allow local HTTP testing during redirect callbacks.
        - **PKCE Grant Fix:** Resolved `invalid_grant: Missing code verifier` errors by setting `autogenerate_code_verifier=False` on Flow generation, preventing code verifier loss across separate flow initiation states.
        - **Native Calendar UI Fix:** Set CSS `color-scheme: dark` on all date/time inputs in `style.css` to fix unreadable white-on-white native calendar text popups.
    *   **Sync Logic Integration:** Restructured scheduling, rescheduling, and cancellation routes in `hrms/interviews/routes.py` to transparently connect to the Calendar API if integrated. Creates, reschedules, or cancels events on the primary calendar, automatically emailing candidates and interviewers directly from Google.
    *   **Robust Fallback:** If calendar integration is not connected, the codebase falls back cleanly to the Task 3 SMTP email format attaching custom generated `.ics` files.
