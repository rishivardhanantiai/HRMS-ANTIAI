CREATE TABLE IF NOT EXISTS generated_letters (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES hrms_employees(id) ON DELETE CASCADE,
    document_type VARCHAR(100),
    pdf_url TEXT,
    generated_by VARCHAR(200),
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS letter_templates_history (
    id SERIAL PRIMARY KEY,
    template_name VARCHAR(150),
    template_content TEXT,
    updated_by VARCHAR(200),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ensure updated_by is added to letter_templates
ALTER TABLE letter_templates ADD COLUMN IF NOT EXISTS updated_by VARCHAR(200);
