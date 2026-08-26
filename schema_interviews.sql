CREATE TABLE IF NOT EXISTS candidate_interviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id UUID REFERENCES hrms_employees(id) ON DELETE CASCADE,
    scheduled_at TIMESTAMP WITH TIME ZONE NOT NULL,
    duration_minutes INTEGER DEFAULT 30,
    location TEXT,
    ics_uid TEXT NOT NULL,
    ics_sequence INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Scheduled',
    scheduled_by TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
