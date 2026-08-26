-- =====================================================================
-- Self-Service Onboarding — schema migration
-- Run this once against the same Postgres database used by the app
-- (psql "$DATABASE_URL" -f schema_onboarding.sql), or paste it into the
-- Supabase SQL editor if you're managing the schema there instead.
-- All statements are idempotent and safe to re-run.
-- =====================================================================

-- Track onboarding state directly on hrms_employees so the existing
-- employee list / profile pages keep working without changes.
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS onboarding_status TEXT;
-- One of: 'Invited', 'Submitted', 'Active'  (NULL = created via the old
-- manual wizard, i.e. not part of the self-onboarding flow)

ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS onboarding_token TEXT;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS onboarding_token_expires_at TIMESTAMPTZ;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS invited_at TIMESTAMPTZ;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS invited_by UUID;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS activated_at TIMESTAMPTZ;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS offer_accepted BOOLEAN DEFAULT FALSE;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS offer_accepted_at TIMESTAMPTZ;

-- Fast lookup when a candidate opens their invite link.
CREATE INDEX IF NOT EXISTS idx_hrms_employees_onboarding_token
    ON hrms_employees (onboarding_token);

CREATE INDEX IF NOT EXISTS idx_hrms_employees_onboarding_status
    ON hrms_employees (onboarding_status);

ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS blood_group text;

-- =====================================================================
-- The app's own hrms_employees columns / support tables were also
-- incomplete on some environments (db_upgrade.py had a uuid/integer type
-- mismatch bug that made several of its CREATE TABLE statements fail
-- silently). These are safe to (re-)run against any environment.
-- =====================================================================

ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS designation text;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS gender text;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS date_of_birth date;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS office_location text;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS employment_type text;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS profile_photo_url text;
ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS password_reset_token text;

CREATE TABLE IF NOT EXISTS employee_status_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hrms_employees(id) ON DELETE CASCADE,
    status text NOT NULL,
    changed_by uuid REFERENCES hrms_employees(id),
    changed_at timestamp with time zone DEFAULT now(),
    remarks text
);

CREATE TABLE IF NOT EXISTS employee_compliance (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hrms_employees(id) ON DELETE CASCADE UNIQUE,
    pan_number text,
    aadhaar_number text,
    uan_number text,
    pf_number text,
    esic_number text
);

CREATE TABLE IF NOT EXISTS employee_bank_details (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hrms_employees(id) ON DELETE CASCADE UNIQUE,
    bank_name text,
    account_number text,
    ifsc_code text,
    branch_name text,
    address text,
    emergency_contact text,
    emergency_contact_number text
);

CREATE TABLE IF NOT EXISTS employee_audit_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hrms_employees(id) ON DELETE CASCADE,
    action text NOT NULL,
    performed_by uuid REFERENCES hrms_employees(id),
    "timestamp" timestamp with time zone DEFAULT now(),
    details jsonb DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS employee_salary_components (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hrms_employees(id) ON DELETE CASCADE,
    component_name text NOT NULL,
    yearly_amount numeric(12,2) NOT NULL,
    monthly_amount numeric(12,2) NOT NULL,
    calculation_logic text,
    created_at timestamp with time zone DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_employee_status_history_employee_id ON employee_status_history(employee_id);
CREATE INDEX IF NOT EXISTS idx_employee_audit_logs_employee_id ON employee_audit_logs(employee_id);
CREATE INDEX IF NOT EXISTS idx_employee_salary_components_employee_id ON employee_salary_components(employee_id);
