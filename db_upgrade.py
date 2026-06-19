import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

sql_commands = [
    # 1. Update hrms_employees
    "ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS manager_id integer REFERENCES hrms_employees(id) ON DELETE SET NULL;",
    "ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS gender text;",
    "ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS date_of_birth date;",
    "ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS office_location text;",
    "ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS employment_type text;",
    "ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS profile_photo_url text;",
    "ALTER TABLE hrms_employees ADD COLUMN IF NOT EXISTS password_reset_token text;",

    # 2. employee_status_history
    """
    CREATE TABLE IF NOT EXISTS employee_status_history (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id integer NOT NULL REFERENCES hrms_employees(id) ON DELETE CASCADE,
        status text NOT NULL,
        changed_by integer REFERENCES hrms_employees(id),
        changed_at timestamp with time zone DEFAULT now(),
        remarks text
    );
    """,

    # 3. employee_salary_templates
    """
    CREATE TABLE IF NOT EXISTS employee_salary_templates (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        template_name text NOT NULL UNIQUE,
        description text,
        basic_percentage numeric(5,2),
        hra_percentage numeric(5,2),
        da_percentage numeric(5,2),
        lta_percentage numeric(5,2),
        created_at timestamp with time zone DEFAULT now()
    );
    """,

    # 4. employee_compliance
    """
    CREATE TABLE IF NOT EXISTS employee_compliance (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id integer NOT NULL REFERENCES hrms_employees(id) ON DELETE CASCADE UNIQUE,
        pan_number text,
        aadhaar_number text,
        uan_number text,
        pf_number text,
        esic_number text
    );
    """,

    # 5. employee_bank_details
    """
    CREATE TABLE IF NOT EXISTS employee_bank_details (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id integer NOT NULL REFERENCES hrms_employees(id) ON DELETE CASCADE UNIQUE,
        bank_name text,
        account_number text,
        ifsc_code text,
        branch_name text,
        address text,
        emergency_contact text,
        emergency_contact_number text
    );
    """,

    # 6. employee_audit_logs
    """
    CREATE TABLE IF NOT EXISTS employee_audit_logs (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id integer NOT NULL REFERENCES hrms_employees(id) ON DELETE CASCADE,
        action text NOT NULL,
        performed_by integer REFERENCES hrms_employees(id),
        timestamp timestamp with time zone DEFAULT now(),
        details jsonb DEFAULT '{}'::jsonb
    );
    """,

    # 7. Add annual_ctc to employee_salary (if not exists)
    "ALTER TABLE employee_salary ADD COLUMN IF NOT EXISTS annual_ctc numeric(12,2);",
    
    # 8. employee_salary_components (for custom breakdowns)
    """
    CREATE TABLE IF NOT EXISTS employee_salary_components (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id integer NOT NULL REFERENCES hrms_employees(id) ON DELETE CASCADE,
        component_name text NOT NULL,
        yearly_amount numeric(12,2) NOT NULL,
        monthly_amount numeric(12,2) NOT NULL,
        calculation_logic text,
        created_at timestamp with time zone DEFAULT now()
    );
    """
]

def upgrade_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        for cmd in sql_commands:
            print(f"Executing: {cmd[:50]}...")
            cur.execute(cmd)
        conn.commit()
        cur.close()
        conn.close()
        print("Database upgrade completed successfully.")
    except Exception as e:
        print(f"Error upgrading database: {e}")

if __name__ == "__main__":
    upgrade_db()

