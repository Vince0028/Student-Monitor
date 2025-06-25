-- Create teacher_logs table for tracking teacher actions
CREATE TABLE IF NOT EXISTS teacher_logs (
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

-- Create index for better query performance
CREATE INDEX IF NOT EXISTS idx_teacher_logs_teacher_id ON teacher_logs(teacher_id);
CREATE INDEX IF NOT EXISTS idx_teacher_logs_timestamp ON teacher_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_teacher_logs_action_type ON teacher_logs(action_type); 