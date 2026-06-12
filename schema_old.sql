create table public.departments (
  id uuid not null default gen_random_uuid (),
  name character varying(150) not null,
  description text null,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint departments_pkey primary key (id),
  constraint departments_name_key unique (name)
) TABLESPACE pg_default;

create trigger departments_set_updated_at BEFORE
update on departments for EACH row
execute FUNCTION set_updated_at ();

create table public.roles (
  id uuid not null default gen_random_uuid (),
  name character varying(120) not null,
  permissions jsonb null default '[]'::jsonb,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint roles_pkey primary key (id),
  constraint roles_name_key unique (name)
) TABLESPACE pg_default;

create trigger roles_set_updated_at BEFORE
update on roles for EACH row
execute FUNCTION set_updated_at ();

create table public.attendance (
  id uuid not null default gen_random_uuid (),
  employee_id uuid not null,
  day date not null,
  check_in timestamp with time zone null,
  check_out timestamp with time zone null,
  duration interval null,
  status character varying(20) null default 'present'::character varying,
  notes text null,
  created_at timestamp with time zone null default now(),
  constraint attendance_pkey primary key (id),
  constraint attendance_employee_id_fkey foreign KEY (employee_id) references employees (id) on delete CASCADE
) TABLESPACE pg_default;

create unique INDEX IF not exists attendance_employee_day_idx on public.attendance using btree (employee_id, day) TABLESPACE pg_default;

create table public.salaries (
  id uuid not null default gen_random_uuid (),
  employee_id uuid not null,
  base_amount numeric(12, 2) not null,
  currency character varying(8) null default 'INR'::character varying,
  effective_from date not null,
  effective_to date null,
  components jsonb null default '{}'::jsonb,
  notes text null,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint salaries_pkey primary key (id),
  constraint salaries_employee_id_fkey foreign KEY (employee_id) references employees (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists salaries_employee_id_idx on public.salaries using btree (employee_id) TABLESPACE pg_default;

create trigger salaries_set_updated_at BEFORE
update on salaries for EACH row
execute FUNCTION set_updated_at ();

create table public.payrolls (
  id uuid not null default gen_random_uuid (),
  employee_id uuid not null,
  period_start date not null,
  period_end date not null,
  gross_pay numeric(12, 2) not null,
  net_pay numeric(12, 2) not null,
  tax_amount numeric(12, 2) null default 0,
  deductions jsonb null default '{}'::jsonb,
  additions jsonb null default '{}'::jsonb,
  status character varying(30) null default 'draft'::character varying,
  created_at timestamp with time zone null default now(),
  constraint payrolls_pkey primary key (id),
  constraint payrolls_employee_id_fkey foreign KEY (employee_id) references employees (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists payrolls_employee_id_idx on public.payrolls using btree (employee_id) TABLESPACE pg_default;

create table public.employees (
  id uuid not null default gen_random_uuid (),
  employee_number character varying(32) null,
  first_name character varying(120) not null,
  last_name character varying(120) null,
  email character varying(255) null,
  phone character varying(32) null,
  hire_date date null,
  date_of_birth date null,
  department_id uuid null,
  role_id uuid null,
  manager_id uuid null,
  status character varying(20) not null default 'active'::character varying,
  resume_url text null,
  metadata jsonb null default '{}'::jsonb,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint employees_pkey primary key (id),
  constraint employees_email_key unique (email),
  constraint employees_employee_number_key unique (employee_number),
  constraint employees_manager_id_fkey foreign KEY (manager_id) references employees (id) on delete set null
) TABLESPACE pg_default;

create index IF not exists employees_employee_number_idx on public.employees using btree (employee_number) TABLESPACE pg_default;

create index IF not exists employees_email_idx on public.employees using btree (email) TABLESPACE pg_default;

create trigger employees_set_updated_at BEFORE
update on employees for EACH row
execute FUNCTION set_updated_at ();

create table public.leaves (
  id uuid not null default gen_random_uuid (),
  employee_id uuid not null,
  leave_type character varying(50) not null,
  start_date date not null,
  end_date date not null,
  days numeric(5, 2) not null,
  reason text null,
  approver_id uuid null,
  status character varying(20) null default 'pending'::character varying,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint leaves_pkey primary key (id),
  constraint leaves_approver_id_fkey foreign KEY (approver_id) references employees (id),
  constraint leaves_employee_id_fkey foreign KEY (employee_id) references employees (id) on delete CASCADE
) TABLESPACE pg_default;

create trigger leaves_set_updated_at BEFORE
update on leaves for EACH row
execute FUNCTION set_updated_at ();

create table public.reimbursements (
  id uuid not null default gen_random_uuid (),
  employee_id uuid not null,
  amount numeric(12, 2) not null,
  currency character varying(8) null default 'INR'::character varying,
  description text null,
  receipt_url text null,
  status character varying(20) null default 'pending'::character varying,
  created_at timestamp with time zone null default now(),
  processed_at timestamp with time zone null,
  constraint reimbursements_pkey primary key (id),
  constraint reimbursements_employee_id_fkey foreign KEY (employee_id) references employees (id) on delete CASCADE
) TABLESPACE pg_default;

create table public.hrms_employees (
  id uuid not null default gen_random_uuid (),
  employee_code text null,
  full_name text null,
  email text null,
  phone text null,
  department text null,
  role_id uuid null,
  joining_date date null,
  status text null,
  created_at timestamp with time zone null default now(),
  constraint hrms_employees_pkey primary key (id),
  constraint hrms_employees_email_key unique (email)
) TABLESPACE pg_default;

create table public.audits (
  id uuid not null default gen_random_uuid (),
  actor_id uuid null,
  action character varying(120) not null,
  resource_type character varying(80) null,
  resource_id uuid null,
  payload jsonb null default '{}'::jsonb,
  created_at timestamp with time zone null default now(),
  constraint audits_pkey primary key (id)
) TABLESPACE pg_default;

create table public.hrms_roles (
  id uuid not null default gen_random_uuid (),
  role_name text null,
  description text null,
  created_at timestamp with time zone null default now(),
  constraint hrms_roles_pkey primary key (id),
  constraint hrms_roles_role_name_key unique (role_name)
) TABLESPACE pg_default;

create table public.users (
  id uuid not null default gen_random_uuid (),
  email text not null,
  password text not null,
  system_role_id uuid null,
  employee_id uuid null,
  created_at timestamp with time zone null default now(),
  constraint users_pkey primary key (id),
  constraint users_email_key unique (email),
  constraint users_employee_id_fkey foreign KEY (employee_id) references hrms_employees (id),
  constraint users_system_role_id_fkey foreign KEY (system_role_id) references system_roles (id)
) TABLESPACE pg_default;

create table public.system_roles (
  id uuid not null default gen_random_uuid (),
  role_name text null,
  description text null,
  created_at timestamp with time zone null default now(),
  constraint system_roles_pkey primary key (id),
  constraint system_roles_role_name_key unique (role_name)
) TABLESPACE pg_default;