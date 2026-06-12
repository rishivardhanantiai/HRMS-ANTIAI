-- Additive migration for the new Supabase database.
-- This keeps existing jobs/applications/contacts data intact and only creates missing HRMS tables.

create table if not exists public.hrms_roles (
  id uuid not null default gen_random_uuid(),
  role_name text not null unique,
  description text null,
  created_at timestamp with time zone null default now(),
  constraint hrms_roles_pkey primary key (id)
);

create table if not exists public.hrms_employees (
  id uuid not null default gen_random_uuid(),
  employee_code text null unique,
  full_name text null,
  email text null unique,
  phone text null,
  department text null,
  role_id uuid null references public.hrms_roles(id) on delete set null,
  joining_date date null,
  status text null default 'Active',
  created_at timestamp with time zone null default now(),
  constraint hrms_employees_pkey primary key (id)
);

create table if not exists public.hrms_users (
  id uuid not null default gen_random_uuid(),
  email text not null unique,
  password text not null,
  role_id uuid null references public.hrms_roles(id) on delete set null,
  employee_id uuid null references public.hrms_employees(id) on delete set null,
  created_at timestamp with time zone null default now(),
  constraint hrms_users_pkey primary key (id)
);

create table if not exists public.hrms_attendance (
  id uuid not null default gen_random_uuid(),
  employee_id uuid not null references public.hrms_employees(id) on delete cascade,
  attendance_date date not null,
  status text null default 'Present',
  check_in_time timestamp with time zone null,
  check_out_time timestamp with time zone null,
  duration interval null,
  is_locked boolean null default false,
  created_at timestamp with time zone null default now(),
  constraint hrms_attendance_pkey primary key (id),
  constraint hrms_attendance_employee_day_key unique (employee_id, attendance_date)
);

create index if not exists hrms_attendance_employee_date_idx on public.hrms_attendance using btree (employee_id, attendance_date);

create table if not exists public.leave_types (
  id uuid not null default gen_random_uuid(),
  name text not null unique,
  description text null,
  created_at timestamp with time zone null default now(),
  constraint leave_types_pkey primary key (id)
);

create table if not exists public.leave_applications (
  id uuid not null default gen_random_uuid(),
  employee_id uuid not null references public.hrms_employees(id) on delete cascade,
  leave_type_id uuid not null references public.leave_types(id) on delete restrict,
  from_date date not null,
  to_date date not null,
  reason text null,
  status text null default 'Pending',
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint leave_applications_pkey primary key (id)
);

create index if not exists leave_applications_employee_idx on public.leave_applications using btree (employee_id);

create table if not exists public.salary_structures (
  id uuid not null default gen_random_uuid(),
  name text not null unique,
  description text null,
  created_at timestamp with time zone null default now(),
  constraint salary_structures_pkey primary key (id)
);

create table if not exists public.salary_components (
  id uuid not null default gen_random_uuid(),
  name text not null unique,
  type text not null,
  created_at timestamp with time zone null default now(),
  constraint salary_components_pkey primary key (id)
);

create table if not exists public.salary_structure_components (
  structure_id uuid not null references public.salary_structures(id) on delete cascade,
  component_id uuid not null references public.salary_components(id) on delete cascade,
  amount numeric(12, 2) not null,
  created_at timestamp with time zone null default now(),
  constraint salary_structure_components_pkey primary key (structure_id, component_id)
);

create table if not exists public.employee_salary (
  id uuid not null default gen_random_uuid(),
  employee_id uuid not null references public.hrms_employees(id) on delete cascade,
  structure_id uuid null references public.salary_structures(id) on delete set null,
  monthly_salary numeric(12, 2) null,
  effective_from date not null,
  effective_to date null,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint employee_salary_pkey primary key (id)
);

create index if not exists employee_salary_employee_effective_idx on public.employee_salary using btree (employee_id, effective_from desc);

create table if not exists public.employee_bonus (
  id uuid not null default gen_random_uuid(),
  employee_id uuid not null references public.hrms_employees(id) on delete cascade,
  amount numeric(12, 2) not null,
  month integer not null,
  year integer not null,
  created_at timestamp with time zone null default now(),
  constraint employee_bonus_pkey primary key (id)
);

create table if not exists public.employee_variable_pay (
  id uuid not null default gen_random_uuid(),
  employee_id uuid not null references public.hrms_employees(id) on delete cascade,
  bonus numeric(12, 2) null default 0,
  incentive numeric(12, 2) null default 0,
  commission numeric(12, 2) null default 0,
  esop_value numeric(12, 2) null default 0,
  month integer not null,
  year integer not null,
  created_at timestamp with time zone null default now(),
  constraint employee_variable_pay_pkey primary key (id)
);

create table if not exists public.reimbursement_requests (
  id uuid not null default gen_random_uuid(),
  employee_id uuid not null references public.hrms_employees(id) on delete cascade,
  amount numeric(12, 2) not null,
  status text not null default 'Pending',
  created_at timestamp with time zone null default now(),
  constraint reimbursement_requests_pkey primary key (id)
);

create table if not exists public.payroll_runs (
  id uuid not null default gen_random_uuid(),
  employee_id uuid not null references public.hrms_employees(id) on delete cascade,
  month integer not null,
  year integer not null,
  gross_salary numeric(12, 2) not null,
  attendance_deduction numeric(12, 2) null default 0,
  pf numeric(12, 2) null default 0,
  variable_pay numeric(12, 2) null default 0,
  bonus numeric(12, 2) null default 0,
  reimbursements numeric(12, 2) null default 0,
  net_salary numeric(12, 2) not null,
  status text null default 'DRAFT',
  generated_at timestamp with time zone null default now(),
  generated_by uuid null,
  financial_year text null,
  approved_at timestamp with time zone null,
  locked_at timestamp with time zone null,
  constraint payroll_runs_pkey primary key (id),
  constraint payroll_runs_employee_month_year_key unique (employee_id, month, year)
);
