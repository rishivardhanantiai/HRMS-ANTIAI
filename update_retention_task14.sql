-- Add candidate_retention_months column to company_settings
ALTER TABLE public.company_settings ADD COLUMN IF NOT EXISTS candidate_retention_months INTEGER DEFAULT 12;

-- Set default value to 12 for existing settings row if it's currently null
UPDATE public.company_settings SET candidate_retention_months = 12 WHERE candidate_retention_months IS NULL;
