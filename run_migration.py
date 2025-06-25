import os
import psycopg2
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def run_migration():
    # Get database URL from environment
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        print("Error: DATABASE_URL not found in .env file")
        return
    
    max_retries = 3
    retry_delay = 30  # seconds
    
    for attempt in range(max_retries):
        try:
            print(f"Attempt {attempt + 1} of {max_retries}...")
            
            # Connect to the database with optimized settings for Supabase
            print("Connecting to database...")
            conn = psycopg2.connect(
                database_url,
                connect_timeout=10,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5
            )
            cursor = conn.cursor()
            
            # Run the migration
            print("Running migration...")
            migration_sql = """
            ALTER TABLE users
            ADD COLUMN firstname VARCHAR(255),
            ADD COLUMN lastname VARCHAR(255),
            ADD COLUMN middlename VARCHAR(255);
            """
            
            cursor.execute(migration_sql)
            conn.commit()
            
            print("✅ Migration completed successfully!")
            print("Added columns: firstname, lastname, middlename to users table")
            return True
            
        except psycopg2.OperationalError as e:
            if "Max client connections reached" in str(e):
                print(f"❌ Connection limit reached (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    print(f"Waiting {retry_delay} seconds before retrying...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    print("❌ Max retries reached. Please try again later or use Supabase SQL Editor.")
                    print("💡 Tip: Go to https://app.supabase.com/ → SQL Editor → Run the migration manually")
            else:
                print(f"❌ Database connection error: {e}")
                break
        except psycopg2.Error as e:
            if "column" in str(e).lower() and "already exists" in str(e).lower():
                print("✅ Columns already exist! Migration not needed.")
                return True
            else:
                print(f"❌ Database error: {e}")
                break
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            break
        finally:
            try:
                if 'cursor' in locals():
                    cursor.close()
                if 'conn' in locals():
                    conn.close()
            except:
                pass
    
    return False

if __name__ == "__main__":
    print("🚀 Starting migration to add name columns to users table...")
    success = run_migration()
    
    if not success:
        print("\n📋 Manual Migration Instructions:")
        print("1. Go to https://app.supabase.com/")
        print("2. Select your project")
        print("3. Click 'SQL Editor' in the left sidebar")
        print("4. Click 'New Query'")
        print("5. Paste this SQL:")
        print("   ALTER TABLE users")
        print("   ADD COLUMN firstname VARCHAR(255),")
        print("   ADD COLUMN lastname VARCHAR(255),")
        print("   ADD COLUMN middlename VARCHAR(255);")
        print("6. Click 'Run'")
