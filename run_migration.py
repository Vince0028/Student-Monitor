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

try:
    with engine.connect() as conn:
        # Check if column already exists
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
            
except Exception as e:
    print(f"Error running migration: {e}")
    exit(1) 