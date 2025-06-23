-- Migration: Add parent_id column to students_info for parent assignment
ALTER TABLE students_info
ADD COLUMN parent_id UUID NULL; 