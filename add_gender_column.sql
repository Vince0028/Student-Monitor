DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='students_info' AND column_name='gender'
    ) THEN
        ALTER TABLE students_info ADD COLUMN gender VARCHAR(10);
    END IF;
END $$; 