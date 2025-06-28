-- Migration: Drop and re-add the correct foreign key constraint for student_info_id in student_quiz_results
DO $$
DECLARE
    constraint_name text;
BEGIN
    -- Find the existing constraint name, if any
    SELECT tc.constraint_name INTO constraint_name
    FROM information_schema.table_constraints AS tc
    JOIN information_schema.key_column_usage AS kcu
      ON tc.constraint_name = kcu.constraint_name
      AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_name = 'student_quiz_results'
      AND kcu.column_name = 'student_info_id';

    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE student_quiz_results DROP CONSTRAINT %I', constraint_name);
    END IF;
END $$;

ALTER TABLE student_quiz_results 
ADD CONSTRAINT fk_student_quiz_results_student_info 
FOREIGN KEY (student_info_id) REFERENCES students_info(id) ON DELETE CASCADE; 