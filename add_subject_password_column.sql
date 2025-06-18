-- Add subject_password column to section_subjects table
ALTER TABLE section_subjects 
ADD COLUMN subject_password VARCHAR(255);

-- Add comment to explain the column
COMMENT ON COLUMN section_subjects.subject_password IS 'Password for accessing gradebook for this subject'; 