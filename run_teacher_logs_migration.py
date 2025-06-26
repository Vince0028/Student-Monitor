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
        print("Starting teacher_logs table migration...")
        
        # Read the migration SQL
        with open('fix_teacher_logs_schema.sql', 'r') as f:
            migration_sql = f.read()
        
        # Execute the migration
        conn.execute(text(migration_sql))
        conn.commit()
        
        print("Migration completed successfully!")
        
        # Verify the new schema
        result = conn.execute(text("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'teacher_logs' 
            ORDER BY ordinal_position;
        """))
        
        columns = result.fetchall()
        
        print("\nNew teacher_logs table schema:")
        for col in columns:
            print(f"  - {col[0]} ({col[1]}, nullable: {col[2]})")
            
        # Check if there are any records
        result = conn.execute(text("SELECT COUNT(*) FROM teacher_logs"))
        count = result.fetchone()[0]
        print(f"\nNumber of records in teacher_logs: {count}")
        
except Exception as e:
    print(f"Error during migration: {e}")
    exit(1) 