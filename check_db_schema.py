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

try:
    with engine.connect() as conn:
        # Check if teacher_logs table exists
        result = conn.execute(text("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'teacher_logs' 
            ORDER BY ordinal_position;
        """))
        
        columns = result.fetchall()
        
        if columns:
            print("teacher_logs table exists with the following columns:")
            for col in columns:
                print(f"  - {col[0]} ({col[1]}, nullable: {col[2]})")
        else:
            print("teacher_logs table does not exist")
            
        # Check if there are any existing records
        result = conn.execute(text("SELECT COUNT(*) FROM teacher_logs"))
        count = result.fetchone()[0]
        print(f"\nNumber of records in teacher_logs: {count}")
        
except Exception as e:
    print(f"Error checking database schema: {e}")
    exit(1) 