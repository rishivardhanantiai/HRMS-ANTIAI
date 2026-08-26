create table public.contacts (
  id uuid not null default gen_random_uuid (),
  first_name text not null,
  last_name text null,
  email text not null,
  phone text null,
  message text not null,
  created_at timestamp with time zone null default now(),
  constraint contacts_pkey primary key (id)
) TABLESPACE pg_default;

create table public.applications (
  id uuid not null default gen_random_uuid (),
  job_id uuid null,
  name text not null,
  email text not null,
  phone text null,
  resume_url text null,
  cover_letter text null,
  created_at timestamp with time zone null default now(),
  constraint applications_pkey primary key (id),
  constraint applications_job_id_fkey foreign KEY (job_id) references jobs (id) on delete CASCADE
) TABLESPACE pg_default;

create table public.jobs (
  id uuid not null default gen_random_uuid (),
  title text not null,
  location text null,
  department text null,
  description text null,
  is_active boolean null default true,
  created_at timestamp with time zone null default now(),
  constraint jobs_pkey primary key (id)
) TABLESPACE pg_default;

create table public.contact_us (
  id uuid not null default gen_random_uuid (),
  full_name text not null,
  company text null,
  message text not null,
  email text not null,
  phone text null,
  created_at timestamp with time zone null default now(),
  constraint contact_us_pkey primary key (id)
) TABLESPACE pg_default;