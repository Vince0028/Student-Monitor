-- Create comprehensive logging tables for admin, teacher, and student actions
-- This replaces the old admin_logs table and enhances the teacher_logs table

-- Drop old admin_logs table if it exists (backup first)
CREATE TABLE IF NOT EXISTS admin_logs_backup AS 
SELECT * FROM admin_logs;

-- Drop the old admin_logs table
DROP TABLE IF EXISTS admin_logs;

-- Create new comprehensive admin_logs table
CREATE TABLE admin_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id UUID NOT NULL REFERENCES users(id),
    admin_username VARCHAR(255) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_id UUID,
    target_name VARCHAR(255) NOT NULL,
    details TEXT,
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create comprehensive teacher_logs table (enhance existing)
-- Drop old teacher_logs table if it exists (backup first)
CREATE TABLE IF NOT EXISTS teacher_logs_backup AS 
SELECT * FROM teacher_logs;

-- Drop the old teacher_logs table
DROP TABLE IF EXISTS teacher_logs;

-- Create new comprehensive teacher_logs table
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
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create new student_logs table
CREATE TABLE student_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students_info(id),
    student_username VARCHAR(255) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_id UUID,
    target_name VARCHAR(255) NOT NULL,
    details TEXT,
    section_period_id UUID REFERENCES section_periods(id),
    subject_id UUID REFERENCES section_subjects(id),
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for better query performance
-- Admin logs indexes
CREATE INDEX idx_admin_logs_admin_id ON admin_logs(admin_id);
CREATE INDEX idx_admin_logs_timestamp ON admin_logs(timestamp);
CREATE INDEX idx_admin_logs_action_type ON admin_logs(action_type);
CREATE INDEX idx_admin_logs_target_type ON admin_logs(target_type);

-- Teacher logs indexes
CREATE INDEX idx_teacher_logs_teacher_id ON teacher_logs(teacher_id);
CREATE INDEX idx_teacher_logs_timestamp ON teacher_logs(timestamp);
CREATE INDEX idx_teacher_logs_action_type ON teacher_logs(action_type);
CREATE INDEX idx_teacher_logs_target_type ON teacher_logs(target_type);
CREATE INDEX idx_teacher_logs_section_period_id ON teacher_logs(section_period_id);
CREATE INDEX idx_teacher_logs_subject_id ON teacher_logs(subject_id);

-- Student logs indexes
CREATE INDEX idx_student_logs_student_id ON student_logs(student_id);
CREATE INDEX idx_student_logs_timestamp ON student_logs(timestamp);
CREATE INDEX idx_student_logs_action_type ON student_logs(action_type);
CREATE INDEX idx_student_logs_target_type ON student_logs(target_type);
CREATE INDEX idx_student_logs_section_period_id ON student_logs(section_period_id);
CREATE INDEX idx_student_logs_subject_id ON student_logs(subject_id);

-- Create composite indexes for common queries
CREATE INDEX idx_admin_logs_admin_timestamp ON admin_logs(admin_id, timestamp DESC);
CREATE INDEX idx_teacher_logs_teacher_timestamp ON teacher_logs(teacher_id, timestamp DESC);
CREATE INDEX idx_student_logs_student_timestamp ON student_logs(student_id, timestamp DESC);

-- Create indexes for IP address tracking (security)
CREATE INDEX idx_admin_logs_ip_address ON admin_logs(ip_address);
CREATE INDEX idx_teacher_logs_ip_address ON teacher_logs(ip_address);
CREATE INDEX idx_student_logs_ip_address ON student_logs(ip_address);

-- Note: Backup tables are preserved in case manual data migration is needed
-- You can drop them later after confirming the new system works correctly 