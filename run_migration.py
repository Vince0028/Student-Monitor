import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Get database URL from environment
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("DATABASE_URL environment variable is not set")
    exit(1)

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