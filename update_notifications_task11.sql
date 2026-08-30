-- SQL Migration: Task 11 Notifications Upgrade
-- Add employee_id to notifications to support individual employee notifications

ALTER TABLE public.notifications 
ADD COLUMN IF NOT EXISTS employee_id uuid REFERENCES public.hrms_employees(id) ON DELETE CASCADE;
