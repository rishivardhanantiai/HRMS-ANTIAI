-- 1. Create audit_log table
CREATE TABLE IF NOT EXISTS public.audit_log (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    actor text NOT NULL,
    action text NOT NULL,
    target_table text NULL,
    target_id uuid NULL,
    details jsonb NULL,
    created_at timestamp with time zone NULL DEFAULT now(),
    CONSTRAINT audit_log_pkey PRIMARY KEY (id)
);

-- Index for fast sorting on timeline
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON public.audit_log (created_at DESC);

-- 2. Add missing appearance columns to company_settings
ALTER TABLE public.company_settings ADD COLUMN IF NOT EXISTS offer_logo_wordmark_b64 TEXT;
ALTER TABLE public.company_settings ADD COLUMN IF NOT EXISTS offer_watermark_b64 TEXT;
ALTER TABLE public.company_settings ADD COLUMN IF NOT EXISTS offer_watermark_opacity DOUBLE PRECISION DEFAULT 0.1;
ALTER TABLE public.company_settings ADD COLUMN IF NOT EXISTS offer_watermark_width_cm DOUBLE PRECISION DEFAULT 8.0;
ALTER TABLE public.company_settings ADD COLUMN IF NOT EXISTS offer_logo_width_px DOUBLE PRECISION DEFAULT 200.0;
