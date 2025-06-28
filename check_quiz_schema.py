import os
from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set.")

engine = create_engine(DATABASE_URL)
inspector = inspect(engine)

print("=== Database Schema Check ===")
print(f"Database URL: {DATABASE_URL}")
print()

# Check if tables exist
tables_to_check = ['students_info', 'quizzes', 'student_quiz_results', 'student_quiz_answers']

for table_name in tables_to_check:
    if inspector.has_table(table_name):
        print(f"✅ {table_name} table exists")
        columns = inspector.get_columns(table_name)
        print(f"   Columns: {[col['name'] for col in columns]}")
        
        # Check foreign keys
        foreign_keys = inspector.get_foreign_keys(table_name)
        if foreign_keys:
            print(f"   Foreign Keys:")
            for fk in foreign_keys:
                print(f"     - {fk['constrained_columns']} -> {fk['referred_table']}.{fk['referred_columns']}")
        else:
            print(f"   No foreign keys")
        print()
    else:
        print(f"❌ {table_name} table does NOT exist")
        print()

# Check specific foreign key relationships
print("=== Foreign Key Check ===")
try:
    with engine.connect() as conn:
        # Check if student_quiz_results can reference students_info
        result = conn.execute(text("""
            SELECT 
                tc.table_name, 
                kcu.column_name, 
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name 
            FROM 
                information_schema.table_constraints AS tc 
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
                  AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY' 
                AND tc.table_name = 'student_quiz_results'
        """))
        
        fks = result.fetchall()
        if fks:
            print("Foreign keys in student_quiz_results:")
            for fk in fks:
                print(f"  {fk[1]} -> {fk[2]}.{fk[3]}")
        else:
            print("No foreign keys found in student_quiz_results")
            
except Exception as e:
    print(f"Error checking foreign keys: {e}")

print()
print("=== Table Row Counts ===")
try:
    with engine.connect() as conn:
        for table_name in tables_to_check:
            if inspector.has_table(table_name):
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = result.scalar()
                print(f"{table_name}: {count} rows")
except Exception as e:
    print(f"Error counting rows: {e}") 