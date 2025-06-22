-- Migration: Fix attendance unique constraint to allow multiple subjects per student per date

-- Drop the old unique constraint (if it exists)
ALTER TABLE attendance DROP CONSTRAINT IF EXISTS attendance_student_info_id_attendance_date_key;

-- Add the new unique constraint
ALTER TABLE attendance ADD CONSTRAINT attendance_unique_per_subject_date UNIQUE (student_info_id, section_subject_id, attendance_date); 