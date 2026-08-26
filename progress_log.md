# HRMS Project Progress Log

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
*   [ ] **Task 5:** Pre-Offer Candidate Pipeline
*   [ ] **Task 6:** Real Google Calendar Sync
*   [ ] **Tasks 7-16:** Employee Self-Service, Directory, Analytics, & Admin Roles
