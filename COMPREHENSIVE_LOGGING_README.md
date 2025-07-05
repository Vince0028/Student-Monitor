# Comprehensive Logging System

This document describes the comprehensive logging system implemented in the Student Monitor application that tracks all activities across admin, teacher, and student dashboards.

## Overview

The enhanced logging system provides complete audit trails for all user actions across the entire system, including:

- **Admin Actions**: All administrative operations on users, grade levels, strands, sections, etc.
- **Teacher Actions**: All teaching activities including grading, attendance, quiz management, etc.
- **Student Actions**: All student activities including logins, quiz submissions, profile changes, etc.

## Database Schema

### Admin Logs Table
```sql
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
```

### Teacher Logs Table (Enhanced)
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
    subject_id UUID REFERENCES section_subjects.id),
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Student Logs Table (New)
```sql
CREATE TABLE student_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students_info(id),
    student_username VARCHAR(255) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_id UUID,
    target_name VARCHAR(255) NOT NULL,
    details TEXT,
    section_period_id UUID REFERENCES section_periods(id),
    subject_id UUID REFERENCES section_subjects.id),
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

## Tracked Actions

### Admin Actions
- **User Management**: `add_user`, `edit_user`, `delete_user`
- **Grade Level Management**: `add_grade_level`, `edit_grade_level`, `delete_grade_level`
- **Strand Management**: `add_strand`, `edit_strand`, `delete_strand`
- **Section Management**: `add_section`, `edit_section`, `delete_section`
- **Section Period Management**: `add_section_period`, `edit_section_period`, `delete_section_period`
- **Subject Management**: `add_subject`, `edit_subject`, `delete_subject`
- **Student Management**: `assign_parent`, `unassign_parent`, `sync_students`
- **System Actions**: `login`, `logout`, `export_data`, `view_logs`, `system_config`

### Teacher Actions
- **Student Management**: `add_student`, `edit_student`, `delete_student`
- **Grade Management**: `add_grade`, `edit_grade`, `delete_grade`, `sync_grades`, `export_grades`
- **Attendance Management**: `record_attendance`, `view_attendance`
- **Quiz Management**: `create_quiz`, `edit_quiz`, `delete_quiz`, `score_essay`
- **System Actions**: `login`, `logout`

### Student Actions
- **Quiz Activities**: `quiz_submit`, `quiz_view`, `quiz_score_view`
- **Profile Management**: `profile_update`, `password_change`
- **Grade Viewing**: `grade_view`
- **Attendance Viewing**: `attendance_view`
- **System Actions**: `login`, `logout`

## Implementation

### Logging Functions

#### Admin Logging
```python
def create_admin_log(db_session, admin_id, admin_username, action_type, target_type, target_id, target_name, details=None, request=None):
    """Helper function to create admin log entries"""
    try:
        ip_address, user_agent = get_client_info(request) if request else (None, None)
        log_entry = AdminLog(
            admin_id=admin_id,
            admin_username=admin_username,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db_session.add(log_entry)
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        print(f"Error creating admin log: {e}")
        return False
```

#### Teacher Logging
```python
def create_teacher_log(db_session, teacher_id, teacher_username, action_type, target_type, target_id, target_name, details=None, section_period_id=None, subject_id=None, request=None):
    """Helper function to create teacher log entries"""
    try:
        ip_address, user_agent = get_client_info(request) if request else (None, None)
        log_entry = TeacherLog(
            teacher_id=teacher_id,
            teacher_username=teacher_username,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            details=details,
            section_period_id=section_period_id,
            subject_id=subject_id,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db_session.add(log_entry)
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        print(f"Error creating teacher log: {e}")
        return False
```

#### Student Logging
```python
def create_student_log(db_session, student_id, student_username, action_type, target_type, target_id, target_name, details=None, section_period_id=None, subject_id=None, request=None):
    """Helper function to create student log entries"""
    try:
        ip_address, user_agent = get_client_info(request) if request else (None, None)
        log_entry = StudentLog(
            student_id=student_id,
            student_username=student_username,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            details=details,
            section_period_id=section_period_id,
            subject_id=subject_id,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db_session.add(log_entry)
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        print(f"Error creating student log: {e}")
        return False
```

### Client Information Tracking
```python
def get_client_info(request):
    """Helper function to get client IP and user agent"""
    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip_address and ',' in ip_address:
        ip_address = ip_address.split(',')[0].strip()
    user_agent = request.headers.get('User-Agent', 'Unknown')
    return ip_address, user_agent
```

## Integration Examples

### Admin Login Logging
```python
# In admin login route
if user and check_password_hash(user.password_hash, password):
    session['admin_logged_in'] = True
    session['admin_username'] = user.username
    
    # Log successful login
    create_admin_log(
        db_session=db_session,
        admin_id=user.id,
        admin_username=user.username,
        action_type='login',
        target_type='system',
        target_id=None,
        target_name='Admin Login',
        details=f'Admin {user.username} logged in successfully',
        request=request
    )
```

### Teacher Grade Export Logging
```python
# In grade export route
create_teacher_log(
    db_session=g.session,
    teacher_id=uuid.UUID(session['user_id']),
    teacher_username=session['username'],
    action_type='export_grades',
    target_type='grade',
    target_id=subject_id,
    target_name=f'Grade Export for {subject.subject_name}',
    details=f'Exported grades for {subject.subject_name} in {export_format.upper()} format',
    section_period_id=subject.section_period_id,
    subject_id=subject_id,
    request=request
)
```

### Student Quiz Submission Logging
```python
# In quiz submission route
create_student_log(
    db_session=g.session,
    student_id=student_id,
    student_username=student.student_id_number,
    action_type='quiz_submit',
    target_type='quiz',
    target_id=quiz_id,
    target_name=quiz.title,
    details=f'Submitted quiz "{quiz.title}" with score {total_score}/{total_points}',
    section_period_id=student.section_period_id,
    subject_id=quiz.subject_id,
    request=request
)
```

## Database Indexes

For optimal query performance, the following indexes are created:

```sql
-- Admin logs indexes
CREATE INDEX idx_admin_logs_admin_id ON admin_logs(admin_id);
CREATE INDEX idx_admin_logs_timestamp ON admin_logs(timestamp);
CREATE INDEX idx_admin_logs_action_type ON admin_logs(action_type);
CREATE INDEX idx_admin_logs_target_type ON admin_logs(target_type);
CREATE INDEX idx_admin_logs_admin_timestamp ON admin_logs(admin_id, timestamp DESC);
CREATE INDEX idx_admin_logs_ip_address ON admin_logs(ip_address);

-- Teacher logs indexes
CREATE INDEX idx_teacher_logs_teacher_id ON teacher_logs(teacher_id);
CREATE INDEX idx_teacher_logs_timestamp ON teacher_logs(timestamp);
CREATE INDEX idx_teacher_logs_action_type ON teacher_logs(action_type);
CREATE INDEX idx_teacher_logs_target_type ON teacher_logs(target_type);
CREATE INDEX idx_teacher_logs_section_period_id ON teacher_logs(section_period_id);
CREATE INDEX idx_teacher_logs_subject_id ON teacher_logs(subject_id);
CREATE INDEX idx_teacher_logs_teacher_timestamp ON teacher_logs(teacher_id, timestamp DESC);
CREATE INDEX idx_teacher_logs_ip_address ON teacher_logs(ip_address);

-- Student logs indexes
CREATE INDEX idx_student_logs_student_id ON student_logs(student_id);
CREATE INDEX idx_student_logs_timestamp ON student_logs(timestamp);
CREATE INDEX idx_student_logs_action_type ON student_logs(action_type);
CREATE INDEX idx_student_logs_target_type ON student_logs(target_type);
CREATE INDEX idx_student_logs_section_period_id ON student_logs(section_period_id);
CREATE INDEX idx_student_logs_subject_id ON student_logs(subject_id);
CREATE INDEX idx_student_logs_student_timestamp ON student_logs(student_id, timestamp DESC);
CREATE INDEX idx_student_logs_ip_address ON student_logs(ip_address);
```

## Admin Interface

### Viewing Logs
- **Admin Logs**: `/admin/admin_logs` - View all admin actions
- **Teacher Logs**: `/admin/teacher_logs` - View all teacher actions
- **Student Logs**: `/admin/student_logs` - View all student actions (new)

### Log Display Features
- Color-coded badges for different action types
- Timestamp, user, action, target, and details columns
- IP address and user agent information for security tracking
- Filtering and sorting capabilities
- Export functionality (CSV/PDF)

## Security Features

### IP Address Tracking
- Records client IP addresses for all actions
- Handles proxy/load balancer scenarios with X-Forwarded-For header
- Enables tracking of suspicious login patterns

### User Agent Tracking
- Records browser and device information
- Helps identify unauthorized access attempts
- Provides context for user behavior analysis

### Comprehensive Coverage
- All CRUD operations are logged
- System access (login/logout) is tracked
- Export and data access activities are recorded
- Quiz submissions and grading activities are logged

## Performance Considerations

### Database Optimization
- Proper indexing for common query patterns
- Efficient composite indexes for user-specific queries
- Partitioning strategy for large log tables (future enhancement)

### Log Retention
- Implement log rotation and archival policies
- Consider data retention requirements
- Plan for log table maintenance

## Future Enhancements

### Advanced Features
- Real-time log monitoring dashboard
- Email notifications for critical actions
- Integration with external SIEM systems
- Machine learning for anomaly detection
- Automated log analysis and reporting

### Export and Reporting
- Scheduled log reports
- Custom log filtering and search
- Integration with business intelligence tools
- Compliance reporting for educational institutions

## Setup Instructions

### 1. Database Migration
Run the comprehensive logging migration:
```sql
-- Execute create_comprehensive_logs_tables.sql
```

### 2. Code Integration
- Import the new logging models in all application files
- Add logging calls to all relevant routes and functions
- Update existing logging calls to use the new enhanced functions

### 3. Testing
- Verify all actions are being logged correctly
- Test log viewing interfaces
- Validate IP address and user agent capture
- Check performance impact of logging

## Troubleshooting

### Common Issues
1. **Logs not appearing**: Check database permissions and model imports
2. **Performance issues**: Verify indexes are created and queries are optimized
3. **Missing IP addresses**: Check proxy configuration and X-Forwarded-For headers
4. **Import errors**: Ensure all models are properly imported in application files

### Debug Mode
Enable debug logging for troubleshooting:
```python
app.logger.setLevel(logging.DEBUG)
```

## Support

For issues or questions regarding the comprehensive logging system, please refer to the application documentation or contact the development team.

## Compliance and Audit

This logging system provides comprehensive audit trails suitable for:
- Educational institution compliance requirements
- Data protection regulations (GDPR, FERPA, etc.)
- Internal security audits
- Student performance tracking and analysis
- Teacher activity monitoring and evaluation 