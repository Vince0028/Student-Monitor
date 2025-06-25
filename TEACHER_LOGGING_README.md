# Teacher Logging System

This document describes the teacher logging system implemented in the Student Monitor application.

## Overview

The teacher logging system tracks all actions performed by teachers on students and grades, providing administrators with a comprehensive audit trail of teacher activities.

## Features

### Tracked Actions

The system logs the following teacher actions:

#### Student Management
- **Add Student**: When a teacher adds a new student to a section period
- **Edit Student**: When a teacher modifies student information
- **Delete Student**: When a teacher removes a student from a section period

#### Grade Management
- **Add Grade**: When a teacher adds a new grade for a student
- **Edit Grade**: When a teacher updates an existing grade
- **Delete Grade**: When a teacher removes a grade

### Log Information

Each log entry contains:
- **Teacher ID**: The UUID of the teacher who performed the action
- **Teacher Username**: The username of the teacher
- **Action Type**: The type of action performed (add_student, edit_student, delete_student, add_grade, edit_grade, delete_grade)
- **Target Type**: Whether the action was on a 'student' or 'grade'
- **Target ID**: The UUID of the affected student or grade record
- **Target Name**: A human-readable description of what was affected
- **Details**: Additional information about the action
- **Section Period ID**: The section period where the action occurred (if applicable)
- **Subject ID**: The subject where the action occurred (if applicable)
- **Timestamp**: When the action was performed

## Implementation

### Database Schema

The system uses a `teacher_logs` table with the following structure:

```sql
CREATE TABLE teacher_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    teacher_id UUID NOT NULL REFERENCES users(id),
    teacher_username VARCHAR(255) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_id UUID,
    target_name VARCHAR(255) NOT NULL,
    details TEXT,
    section_period_id UUID REFERENCES section_periods(id),
    subject_id UUID REFERENCES section_subjects(id),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Code Integration

#### 1. TeacherLog Model (app.py)
```python
class TeacherLog(Base):
    __tablename__ = 'teacher_logs'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    teacher_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    teacher_username = Column(String(255), nullable=False)
    action_type = Column(String(50), nullable=False)
    target_type = Column(String(50), nullable=False)
    target_id = Column(PG_UUID(as_uuid=True), nullable=True)
    target_name = Column(String(255), nullable=False)
    details = Column(Text, nullable=True)
    section_period_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_periods.id'), nullable=True)
    subject_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_subjects.id'), nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
```

#### 2. Helper Function (app.py)
```python
def create_teacher_log(db_session, teacher_id, teacher_username, action_type, target_type, target_id, target_name, details=None, section_period_id=None, subject_id=None):
    """Helper function to create teacher log entries"""
    try:
        log_entry = TeacherLog(
            teacher_id=teacher_id,
            teacher_username=teacher_username,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            details=details,
            section_period_id=section_period_id,
            subject_id=subject_id
        )
        db_session.add(log_entry)
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        print(f"Error creating teacher log: {e}")
        return False
```

### Integration Points

The logging system is integrated into the following functions in `app.py`:

1. **add_student_to_section_period()**: Logs when teachers add students
2. **edit_student()**: Logs when teachers edit student information
3. **delete_student_admin()**: Logs when teachers delete students
4. **add_grades_for_student()**: Logs when teachers add or update grades
5. **update_student_score()**: Logs when teachers update individual scores

### Admin Interface

#### Teacher Logs Route (master_admin_app.py)
```python
@app.route('/admin/teacher_logs')
def teacher_logs():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    from app import TeacherLog
    logs = TeacherLog.query.order_by(TeacherLog.timestamp.desc()).all()
    return render_template('teacher_logs.html', logs=logs)
```

#### Teacher Logs Template (teacher_logs.html)
- Displays all teacher actions in a table format
- Color-coded badges for different action types
- Timestamp, teacher, action, target, and details columns
- Back button to return to user management

## Setup Instructions

### 1. Database Migration
Run the SQL script to create the teacher_logs table:
```sql
-- Execute create_teacher_logs_table.sql
```

### 2. Access Teacher Logs
1. Log in as an admin user
2. Navigate to the admin dashboard
3. Click on "Teacher Logs" card
4. View all teacher actions in chronological order

## Security Considerations

- Only admin users can view teacher logs
- Logs are read-only and cannot be modified
- All sensitive information is properly sanitized in log entries
- Database indexes are created for optimal query performance

## Future Enhancements

Potential improvements to the logging system:
- Export logs to CSV/PDF
- Filter logs by date range, teacher, or action type
- Email notifications for specific actions
- Integration with external audit systems
- Real-time log monitoring dashboard

## Troubleshooting

### Common Issues

1. **Logs not appearing**: Ensure the teacher_logs table exists and has proper permissions
2. **Import errors**: Verify that the TeacherLog model is properly imported in master_admin_app.py
3. **Performance issues**: Check that database indexes are created for optimal query performance

### Debug Mode

To enable debug logging for the teacher logging system, add the following to your application configuration:
```python
app.logger.setLevel(logging.DEBUG)
```

## Support

For issues or questions regarding the teacher logging system, please refer to the application documentation or contact the development team. 