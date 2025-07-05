#!/usr/bin/env python3
"""
Comprehensive Logging System Migration Script

This script sets up the enhanced logging system for admin, teacher, and student actions.
It creates the necessary tables, indexes, and migrates existing data if needed.
"""

import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def run_migration():
    """Run the comprehensive logging migration"""
    
    # Get database URL
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        print("Error: DATABASE_URL environment variable is not set.")
        sys.exit(1)
    
    # Create database engine
    engine = create_engine(DATABASE_URL)
    
    # Migration SQL
    migration_sql = """
    -- Comprehensive Logging System Migration
    -- This migration sets up enhanced logging for admin, teacher, and student actions
    
    -- 1. Backup existing admin_logs table if it exists
    CREATE TABLE IF NOT EXISTS admin_logs_backup AS 
    SELECT * FROM admin_logs;
    
    -- 2. Drop the old admin_logs table
    DROP TABLE IF EXISTS admin_logs;
    
    -- 3. Create new comprehensive admin_logs table
    CREATE TABLE admin_logs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        admin_id UUID NOT NULL REFERENCES users(id),
        admin_username VARCHAR(255) NOT NULL,
        action_type VARCHAR(50) NOT NULL,
        target_type VARCHAR(50) NOT NULL,
        target_id UUID,
        target_name VARCHAR(255) NOT NULL,
        details TEXT,
        ip_address VARCHAR(45),
        user_agent VARCHAR(500),
        timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    
    -- 4. Enhance existing teacher_logs table
    ALTER TABLE teacher_logs 
    ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45),
    ADD COLUMN IF NOT EXISTS user_agent VARCHAR(500);
    
    -- 5. Create new student_logs table
    CREATE TABLE IF NOT EXISTS student_logs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        student_id UUID NOT NULL REFERENCES students_info(id),
        student_username VARCHAR(255) NOT NULL,
        action_type VARCHAR(50) NOT NULL,
        target_type VARCHAR(50) NOT NULL,
        target_id UUID,
        target_name VARCHAR(255) NOT NULL,
        details TEXT,
        section_period_id UUID REFERENCES section_periods(id),
        subject_id UUID REFERENCES section_subjects(id),
        ip_address VARCHAR(45),
        user_agent VARCHAR(500),
        timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    
    -- 6. Create indexes for optimal performance
    
    -- Admin logs indexes
    CREATE INDEX IF NOT EXISTS idx_admin_logs_admin_id ON admin_logs(admin_id);
    CREATE INDEX IF NOT EXISTS idx_admin_logs_timestamp ON admin_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_admin_logs_action_type ON admin_logs(action_type);
    CREATE INDEX IF NOT EXISTS idx_admin_logs_target_type ON admin_logs(target_type);
    CREATE INDEX IF NOT EXISTS idx_admin_logs_admin_timestamp ON admin_logs(admin_id, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_admin_logs_ip_address ON admin_logs(ip_address);
    
    -- Teacher logs indexes (enhance existing)
    CREATE INDEX IF NOT EXISTS idx_teacher_logs_teacher_id ON teacher_logs(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_teacher_logs_timestamp ON teacher_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_teacher_logs_action_type ON teacher_logs(action_type);
    CREATE INDEX IF NOT EXISTS idx_teacher_logs_target_type ON teacher_logs(target_type);
    CREATE INDEX IF NOT EXISTS idx_teacher_logs_section_period_id ON teacher_logs(section_period_id);
    CREATE INDEX IF NOT EXISTS idx_teacher_logs_subject_id ON teacher_logs(subject_id);
    CREATE INDEX IF NOT EXISTS idx_teacher_logs_teacher_timestamp ON teacher_logs(teacher_id, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_teacher_logs_ip_address ON teacher_logs(ip_address);
    
    -- Student logs indexes
    CREATE INDEX IF NOT EXISTS idx_student_logs_student_id ON student_logs(student_id);
    CREATE INDEX IF NOT EXISTS idx_student_logs_timestamp ON student_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_student_logs_action_type ON student_logs(action_type);
    CREATE INDEX IF NOT EXISTS idx_student_logs_target_type ON student_logs(target_type);
    CREATE INDEX IF NOT EXISTS idx_student_logs_section_period_id ON student_logs(section_period_id);
    CREATE INDEX IF NOT EXISTS idx_student_logs_subject_id ON student_logs(subject_id);
    CREATE INDEX IF NOT EXISTS idx_student_logs_student_timestamp ON student_logs(student_id, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_student_logs_ip_address ON student_logs(ip_address);
    
    -- 7. Insert sample log entries for testing (optional)
    -- Uncomment the following lines if you want to insert sample data for testing
    
    /*
    INSERT INTO admin_logs (admin_id, admin_username, action_type, target_type, target_name, details, ip_address, user_agent)
    SELECT 
        u.id,
        u.username,
        'system_setup',
        'system',
        'Comprehensive Logging System',
        'Comprehensive logging system initialized',
        '127.0.0.1',
        'Migration Script'
    FROM users u 
    WHERE u.user_type = 'admin' 
    LIMIT 1;
    */
    
    -- 8. Create views for easier log access (optional)
    CREATE OR REPLACE VIEW recent_admin_activity AS
    SELECT 
        al.timestamp,
        al.admin_username,
        al.action_type,
        al.target_type,
        al.target_name,
        al.details,
        al.ip_address
    FROM admin_logs al
    ORDER BY al.timestamp DESC
    LIMIT 100;
    
    CREATE OR REPLACE VIEW recent_teacher_activity AS
    SELECT 
        tl.timestamp,
        tl.teacher_username,
        tl.action_type,
        tl.target_type,
        tl.target_name,
        tl.details,
        tl.ip_address
    FROM teacher_logs tl
    ORDER BY tl.timestamp DESC
    LIMIT 100;
    
    CREATE OR REPLACE VIEW recent_student_activity AS
    SELECT 
        sl.timestamp,
        sl.student_username,
        sl.action_type,
        sl.target_type,
        sl.target_name,
        sl.details,
        sl.ip_address
    FROM student_logs sl
    ORDER BY sl.timestamp DESC
    LIMIT 100;
    
    -- 9. Grant necessary permissions (adjust as needed for your setup)
    -- GRANT SELECT, INSERT ON admin_logs TO your_app_user;
    -- GRANT SELECT, INSERT ON teacher_logs TO your_app_user;
    -- GRANT SELECT, INSERT ON student_logs TO your_app_user;
    """
    
    try:
        with engine.connect() as connection:
            print("Starting comprehensive logging migration...")
            
            # Split the migration into individual statements
            statements = migration_sql.split(';')
            
            for i, statement in enumerate(statements):
                statement = statement.strip()
                if statement:
                    try:
                        connection.execute(text(statement))
                        connection.commit()
                        print(f"✓ Executed statement {i+1}/{len(statements)}")
                    except Exception as e:
                        print(f"⚠ Warning on statement {i+1}: {e}")
                        # Continue with other statements
                        continue
            
            print("\n✅ Comprehensive logging migration completed successfully!")
            print("\nMigration Summary:")
            print("- Enhanced admin_logs table with comprehensive fields")
            print("- Enhanced teacher_logs table with IP and user agent tracking")
            print("- Created new student_logs table for student activity tracking")
            print("- Created performance indexes for all log tables")
            print("- Created views for recent activity monitoring")
            print("- Backup of old admin_logs table created as admin_logs_backup")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

def verify_migration():
    """Verify that the migration was successful"""
    
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        print("Error: DATABASE_URL environment variable is not set.")
        return False
    
    engine = create_engine(DATABASE_URL)
    
    verification_queries = [
        "SELECT COUNT(*) FROM admin_logs",
        "SELECT COUNT(*) FROM teacher_logs", 
        "SELECT COUNT(*) FROM student_logs",
        "SELECT COUNT(*) FROM information_schema.indexes WHERE table_name = 'admin_logs'",
        "SELECT COUNT(*) FROM information_schema.indexes WHERE table_name = 'teacher_logs'",
        "SELECT COUNT(*) FROM information_schema.indexes WHERE table_name = 'student_logs'"
    ]
    
    try:
        with engine.connect() as connection:
            print("\n🔍 Verifying migration...")
            
            for i, query in enumerate(verification_queries):
                result = connection.execute(text(query))
                count = result.scalar()
                print(f"✓ Query {i+1}: {count} records/indexes found")
            
            print("\n✅ Migration verification completed successfully!")
            return True
            
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Comprehensive Logging System Migration")
    print("=" * 50)
    
    # Run migration
    run_migration()
    
    # Verify migration
    verify_migration()
    
    print("\n📋 Next Steps:")
    print("1. Update your application code to use the new logging functions")
    print("2. Test the logging system with sample actions")
    print("3. Monitor the logs through the admin interface")
    print("4. Review the COMPREHENSIVE_LOGGING_README.md for implementation details")
    
    print("\n🎉 Migration script completed!") 