-- Migration: Add parent_id column to students_info for parent assignment
ALTER TABLE students_info
ADD COLUMN parent_id UUID NULL;

-- Add created_at column to parents table
ALTER TABLE parents ADD COLUMN created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(); 