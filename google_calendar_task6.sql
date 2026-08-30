-- Migration for Task 6 Google Calendar Integration

-- Table for storing encrypted tokens
CREATE TABLE IF NOT EXISTS google_calendar_tokens (
    id SERIAL PRIMARY KEY,
    user_email text UNIQUE NOT NULL,
    token_data text NOT NULL, -- Encrypted JSON string
    updated_at timestamp with time zone DEFAULT now()
);

-- Column on candidate_interviews table to link Google Calendar Event
ALTER TABLE candidate_interviews ADD COLUMN IF NOT EXISTS google_event_id text;
