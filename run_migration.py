import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Get database URL from environment
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("DATABASE_URL environment variable is not set")
    exit(1)

# Create engine
engine = create_engine(DATABASE_URL)

# Migration SQL
migration_sql = """
-- Add subject_password column to section_subjects table
ALTER TABLE section_subjects 
ADD COLUMN subject_password VARCHAR(255);

-- Add comment to explain the column
COMMENT ON COLUMN section_subjects.subject_password IS 'Password for accessing gradebook for this subject';
"""

# Migration for attendance table
attendance_migration_sql = """
-- Add section_subject_id column to attendance table
ALTER TABLE attendance 
ADD COLUMN section_subject_id UUID REFERENCES section_subjects(id) ON DELETE CASCADE;

-- Add unique constraint for the new column combination
ALTER TABLE attendance 
DROP CONSTRAINT IF EXISTS attendance_student_info_id_section_subject_id_attendance_date_key;

ALTER TABLE attendance 
ADD CONSTRAINT attendance_student_info_id_section_subject_id_attendance_date_key 
UNIQUE (student_info_id, section_subject_id, attendance_date);
"""

try:
    with engine.connect() as conn:
        # Check if subject_password column already exists
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'section_subjects' 
            AND column_name = 'subject_password'
        """))
        
        if result.fetchone():
            print("Column 'subject_password' already exists in section_subjects table")
        else:
            # Execute migration
            conn.execute(text(migration_sql))
            conn.commit()
            print("Successfully added 'subject_password' column to section_subjects table")
        
        # Check if section_subject_id column already exists in attendance table
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'attendance' 
            AND column_name = 'section_subject_id'
        """))
        
        if result.fetchone():
            print("Column 'section_subject_id' already exists in attendance table")
        else:
            # Execute attendance migration
            conn.execute(text(attendance_migration_sql))
            conn.commit()
            print("Successfully added 'section_subject_id' column to attendance table")
            
except Exception as e:
    print(f"Error running migration: {e}")
    exit(1) 