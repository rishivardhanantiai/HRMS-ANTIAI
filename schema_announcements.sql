CREATE TABLE IF NOT EXISTS message_templates (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    body_html TEXT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outbound_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject TEXT NOT NULL,
    body_html TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Queued',
    created_by TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    sent_at TIMESTAMP WITH TIME ZONE
);

INSERT INTO message_templates (id, subject, body_html) 
VALUES (
    'interview_reminder', 
    'Reminder: Upcoming Interview with {{company_name}}', 
    '<p>Hi {{candidate_name}},</p><p>This is a quick reminder about your upcoming interview.</p>'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO message_templates (id, subject, body_html) 
VALUES (
    'welcome_email', 
    'Welcome to the team, {{candidate_name}}!', 
    '<p>Hi {{candidate_name}},</p><p>We are thrilled to have you join us. Please check your onboarding portal for next steps.</p>'
) ON CONFLICT (id) DO NOTHING;
