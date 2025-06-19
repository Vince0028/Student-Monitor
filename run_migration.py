import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from dotenv import load_dotenv

load_dotenv()

# Get database URL from environment
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("DATABASE_URL environment variable is not set")
    exit(1)

<<<<<<< HEAD
if len(sys.argv) < 2:
    print("Usage: python run_migration.py <migration_file.sql>")
    exit(1)

migration_file = sys.argv[1]

if not os.path.isfile(migration_file):
    print(f"Migration file '{migration_file}' does not exist.")
    exit(1)

with open(migration_file, 'r', encoding='utf-8') as f:
    migration_sql = f.read()

# Create engine
engine = create_engine(DATABASE_URL)

try:
    with engine.connect() as conn:
        conn.execute(text(migration_sql))
        conn.commit()
        print(f"Successfully applied migration from '{migration_file}'")
except Exception as e:
    print(f"Error running migration: {e}")
    exit(1) 
=======
# Add the current directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import DATABASE_URL

def run_migrations():
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        # Add subject_password column to section_subjects if it doesn't exist
        try:
            conn.execute(text("ALTER TABLE section_subjects ADD COLUMN subject_password VARCHAR(255)"))
            print("Added subject_password column to section_subjects table")
        except ProgrammingError as e:
            if "already exists" in str(e):
                print("Column 'subject_password' already exists in section_subjects table")
            else:
                raise e
        
        # Add section_subject_id column to attendance if it doesn't exist
        try:
            conn.execute(text("ALTER TABLE attendance ADD COLUMN section_subject_id UUID REFERENCES section_subjects(id)"))
            print("Added section_subject_id column to attendance table")
        except ProgrammingError as e:
            if "already exists" in str(e):
                print("Column 'section_subject_id' already exists in attendance table")
            else:
                raise e
        
        # Add password_hash column to students_info if it doesn't exist
        try:
            conn.execute(text("ALTER TABLE students_info ADD COLUMN password_hash VARCHAR(255)"))
            print("Added password_hash column to students_info table")
        except ProgrammingError as e:
            if "already exists" in str(e):
                print("Column 'password_hash' already exists in students_info table")
            else:
                raise e
        
        conn.commit()

if __name__ == "__main__":
    run_migrations() 
>>>>>>> 02540242bf81181ddc10563fb3dde9ac3a91f10e
