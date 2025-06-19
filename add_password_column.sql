-- Add password_hash column to students_info table
ALTER TABLE students_info ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255); 