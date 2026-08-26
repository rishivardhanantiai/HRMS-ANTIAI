# HRMS Project Progress Log

## Resolved Issues
*   **Fix `AttributeError: 'tuple' object has no attribute 'get'` during HR Countersignature:**
    *   **Root Cause:** The `_render_pdf_and_upload` function was opening a database connection using `get_db()` instead of `get_db(True)`. This caused the `_get_company` function to return a tuple instead of a dictionary. When the code tried to use `.get()` on the tuple to retrieve the company watermark/logo, it threw a 500 error.
    *   **Fix:** Updated the database connection inside `_render_pdf_and_upload` (in `hrms/offers/routes.py`) to explicitly request a dictionary cursor (`get_db(True)`). This ensures the company settings are always returned as a dictionary, preventing the crash when HR tries to countersign an offer.
    *   **Note:** This was not mentioned in the original Handoff Document.

*   **Fix Schema Drift (Salary data loss on candidate activation):**
    *   **Root Cause:** The `activate` route in `hrms/onboarding/routes.py` converted an onboarding candidate to an 'Active' employee but failed to transfer the compensation data from the `employee_offers` table over to the core HRMS `employee_salary` and `employee_salary_components` tables.
    *   **Fix:** Modified the `activate` route to fetch the latest executed offer for the activated candidate. If `ctc_annual` is greater than 0, it deletes any placeholder salary rows and inserts the `annual_ctc`, `monthly_salary`, and all component breakdowns (Basic, HRA, Special Allowance, etc.) into `employee_salary` and `employee_salary_components`. It handles this natively in SQL and has a complete REST API fallback for the cloud database.

## Pending Tasks (Roadmap)
*   [x] **Task 1:** Notification Inbox
*   [x] **Task 2:** Sensitive-Action Approval Queue
*   [ ] **Task 3:** Meeting / Interview Invites (.ics)
*   [ ] **Task 4:** Announcements & Bulk Composer
*   [ ] **Task 5:** Pre-Offer Candidate Pipeline
*   [ ] **Task 6:** Real Google Calendar Sync
*   [ ] **Tasks 7-16:** Employee Self-Service, Directory, Analytics, & Admin Roles
