-- Migration to ensure pdf_url is used on employee_offers and employee_ndas to match production schema

DO $$ 
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'employee_offers' AND column_name = 'final_pdf_url'
    ) THEN
        ALTER TABLE employee_offers RENAME COLUMN final_pdf_url TO pdf_url;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'employee_ndas' AND column_name = 'final_pdf_url'
    ) THEN
        ALTER TABLE employee_ndas RENAME COLUMN final_pdf_url TO pdf_url;
    END IF;
END $$;
