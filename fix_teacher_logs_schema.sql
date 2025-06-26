-- Fix teacher_logs table schema to match SQLAlchemy model
-- Drop the old table and recreate it with the correct schema

-- First, backup existing data if any
CREATE TABLE IF NOT EXISTS teacher_logs_backup AS 
SELECT * FROM teacher_logs;

-- Drop the old table
DROP TABLE IF EXISTS teacher_logs;

-- Create the new table with correct schema
CREATE TABLE teacher_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    teacher_id UUID NOT NULL REFERENCES users(id),
    teacher_username VARCHAR(255) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_id UUID,
    target_name VARCHAR(255) NOT NULL,
    details TEXT,
    section_period_id UUID REFERENCES section_periods(id),
    subject_id UUID REFERENCES section_subjects(id),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for better query performance
CREATE INDEX idx_teacher_logs_teacher_id ON teacher_logs(teacher_id);
CREATE INDEX idx_teacher_logs_timestamp ON teacher_logs(timestamp);
CREATE INDEX idx_teacher_logs_action_type ON teacher_logs(action_type);

-- Note: If you need to restore data from the backup, you would need to map the old columns to new ones
-- For now, we'll leave the backup table in case manual data migration is needed 