CREATE TABLE IF NOT EXISTS notifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_role text NOT NULL, -- 'HR' or 'Admin'
    type text NOT NULL,           
    message text NOT NULL,        
    link text,                    
    read_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);
