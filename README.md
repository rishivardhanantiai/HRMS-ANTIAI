# HRMS - Human Resource Management System

## Overview

HRMS is a Flask-based Human Resource Management System for managing day-to-day HR workflows such as job postings, candidate applications, employee records, attendance, leave, payroll, salary structures, and role administration.

The application is built to work with a local PostgreSQL database and also includes Supabase fallback logic for several operations, so core workflows can continue even when the primary database connection is unavailable.

## Main Features

- Login and session-based user roles
- Dashboard with role-aware views
- Job creation, editing, and deletion
- Public job application submission with resume upload
- HR/Admin applications management
- CSV import for applications
- Downloadable CSV template for applicant import
- Excel export for applications and salary records
- Employee management
- Role management
- Leave management
- Attendance tracking
- Payroll and salary management
- Resume upload and serving support

## Access Control

- General authentication is handled through `login_required`
- HR/Admin-only areas should use `role_required(["HR", "Admin"])`
- The Applications area is restricted server-side to HR/Admin users, not just hidden in the sidebar

## Project Structure

- `app.py` contains the main Flask app, shared routes, dashboard, jobs, applications, uploads, exports, and settings
- `hrms/attendance/`, `hrms/leave/`, `hrms/payroll/`, `hrms/salary/`, `hrms/employees/`, and `hrms/roles/` contain feature blueprints
- `utils/auth.py` contains login and role checks
- `utils/db.py` manages PostgreSQL connections
- `utils/supabase_rest.py` contains Supabase fallback helpers

## Data and Storage Behavior

- Primary database access goes through PostgreSQL
- If the SQL connection fails, the app falls back to Supabase REST in several routes
- Resume uploads go to Supabase Storage
- Excel downloads are generated in memory, which avoids filesystem issues on read-only deployments

## Environment Variables

- `SECRET_KEY`
- `DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SERVICE_KEY`
- `SUPABASE_RESUME_BUCKET`
- `VERCEL`

## Developer Notes

- Several routes are written to work with either PostgreSQL or Supabase fallback logic
- When adding new features, check whether the route belongs in `app.py` or an existing blueprint first
- The applications page supports manual CSV imports, template downloads, and Excel export, but access is limited to HR/Admin users

## Setup Summary

1. Install dependencies from `requirements.txt`
2. Configure the environment variables listed above
3. Run the Flask app from the main entry point in `app.py`

## Short Description

HRMS is a modular HR operations app that combines job posting, applicant tracking, employee management, leave, attendance, payroll, and role-based access control in a single Flask project.
