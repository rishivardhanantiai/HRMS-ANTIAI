CREATE TABLE IF NOT EXISTS employee_exits (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES hrms_employees(id) ON DELETE CASCADE,
    exit_type VARCHAR(100),
    notice_period VARCHAR(100),
    last_working_date DATE,
    exit_reason TEXT,
    remarks TEXT,
    status VARCHAR(50) DEFAULT 'Initiated',
    initiated_by VARCHAR(200),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employee_exit_documents (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES hrms_employees(id) ON DELETE CASCADE,
    exit_id INTEGER REFERENCES employee_exits(id) ON DELETE CASCADE,
    document_type VARCHAR(100),
    pdf_url TEXT,
    generated_by VARCHAR(200),
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employee_fnf_records (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES hrms_employees(id) ON DELETE CASCADE,
    exit_id INTEGER REFERENCES employee_exits(id) ON DELETE CASCADE,
    pending_salary NUMERIC(10, 2) DEFAULT 0,
    leave_encashment NUMERIC(10, 2) DEFAULT 0,
    bonus NUMERIC(10, 2) DEFAULT 0,
    reimbursement NUMERIC(10, 2) DEFAULT 0,
    deductions NUMERIC(10, 2) DEFAULT 0,
    net_amount NUMERIC(10, 2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS letter_templates (
    id SERIAL PRIMARY KEY,
    template_name VARCHAR(150) UNIQUE NOT NULL,
    template_content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_settings (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(200),
    company_logo_url TEXT,
    company_address TEXT,
    company_contact VARCHAR(100),
    company_email VARCHAR(100),
    company_website VARCHAR(150),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
