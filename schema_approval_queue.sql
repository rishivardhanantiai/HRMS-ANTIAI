CREATE TABLE IF NOT EXISTS admin_approval_queue (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type text NOT NULL,   
    target_table text,           
    target_id text,              
    payload_before jsonb,        
    payload_after jsonb,         
    requested_by text NOT NULL,  
    status text NOT NULL DEFAULT 'Pending', 
    admin_comment text,          
    resolved_by text,            
    resolved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);
