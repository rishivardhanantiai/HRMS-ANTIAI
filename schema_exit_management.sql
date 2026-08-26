-- ====================================================================
-- HRMS EXIT MANAGEMENT & OFFBOARDING COMPLETE DATABASE SCHEMA
-- Copy and paste this script directly into Supabase SQL Editor or psql
-- ====================================================================

-- 1. Add work_drive_link column to employee profile if not exists
ALTER TABLE public.hrms_employees 
ADD COLUMN IF NOT EXISTS work_drive_link TEXT;

-- 2. Drop existing foreign key constraints on exit tables to support VARCHAR employee_id (UUID compatible)
DO $$ 
DECLARE 
    r RECORD;
BEGIN
    FOR r IN (
        SELECT table_name, constraint_name 
        FROM information_schema.table_constraints 
        WHERE table_name IN ('employee_exits', 'employee_exit_documents', 'employee_fnf_records')
          AND constraint_type = 'FOREIGN KEY'
    ) LOOP
        EXECUTE 'ALTER TABLE public.' || quote_ident(r.table_name) || ' DROP CONSTRAINT IF EXISTS ' || quote_ident(r.constraint_name) || ';';
    END LOOP;
END $$;

-- 3. Create or Update employee_exits table
CREATE TABLE IF NOT EXISTS public.employee_exits (
    id SERIAL PRIMARY KEY,
    employee_id VARCHAR(100) NOT NULL,
    exit_type VARCHAR(100) DEFAULT 'Resignation',
    notice_period VARCHAR(100) DEFAULT '30 Days',
    notice_period_days INTEGER DEFAULT 0,
    last_working_date DATE,
    exit_reason TEXT,
    remarks TEXT,
    work_drive_link TEXT,
    status VARCHAR(50) DEFAULT 'Initiated',
    initiated_by VARCHAR(200),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ensure missing columns exist if table was previously created
ALTER TABLE public.employee_exits ADD COLUMN IF NOT EXISTS notice_period VARCHAR(100) DEFAULT '30 Days';
ALTER TABLE public.employee_exits ADD COLUMN IF NOT EXISTS notice_period_days INTEGER DEFAULT 0;
ALTER TABLE public.employee_exits ADD COLUMN IF NOT EXISTS work_drive_link TEXT;
ALTER TABLE public.employee_exits ALTER COLUMN employee_id TYPE VARCHAR(100) USING employee_id::text;

-- 4. Create or Update employee_exit_documents table
CREATE TABLE IF NOT EXISTS public.employee_exit_documents (
    id SERIAL PRIMARY KEY,
    employee_id VARCHAR(100) NOT NULL,
    exit_id INTEGER REFERENCES public.employee_exits(id) ON DELETE CASCADE,
    document_type VARCHAR(100) NOT NULL,
    pdf_url TEXT NOT NULL,
    generated_by VARCHAR(200),
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE public.employee_exit_documents ALTER COLUMN employee_id TYPE VARCHAR(100) USING employee_id::text;

-- 5. Create or Update employee_fnf_records table
CREATE TABLE IF NOT EXISTS public.employee_fnf_records (
    id SERIAL PRIMARY KEY,
    employee_id VARCHAR(100) NOT NULL,
    exit_id INTEGER REFERENCES public.employee_exits(id) ON DELETE CASCADE,
    pending_salary NUMERIC(10, 2) DEFAULT 0,
    leave_encashment NUMERIC(10, 2) DEFAULT 0,
    bonus NUMERIC(10, 2) DEFAULT 0,
    reimbursements NUMERIC(10, 2) DEFAULT 0,
    reimbursement NUMERIC(10, 2) DEFAULT 0,
    deductions NUMERIC(10, 2) DEFAULT 0,
    net_payable NUMERIC(10, 2) DEFAULT 0,
    net_amount NUMERIC(10, 2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE public.employee_fnf_records ADD COLUMN IF NOT EXISTS reimbursements NUMERIC(10, 2) DEFAULT 0;
ALTER TABLE public.employee_fnf_records ADD COLUMN IF NOT EXISTS reimbursement NUMERIC(10, 2) DEFAULT 0;
ALTER TABLE public.employee_fnf_records ADD COLUMN IF NOT EXISTS net_payable NUMERIC(10, 2) DEFAULT 0;
ALTER TABLE public.employee_fnf_records ADD COLUMN IF NOT EXISTS net_amount NUMERIC(10, 2) DEFAULT 0;
ALTER TABLE public.employee_fnf_records ALTER COLUMN employee_id TYPE VARCHAR(100) USING employee_id::text;

-- 6. Cleanup stale duplicate 'Resignation Applied' records (if employee has reviewed/processed exit records)
DELETE FROM public.employee_exits 
WHERE status = 'Resignation Applied' 
  AND employee_id IN (
      SELECT employee_id FROM public.employee_exits 
      WHERE status IN ('Resignation Rejected', 'Initiated', 'Notice Period', 'Exit Closed')
  );
