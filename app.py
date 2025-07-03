import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import uuid
from datetime import date, timedelta, datetime, timezone
import re # For school year validation
import decimal
import bcrypt
import json

# Import SQLAlchemy components
from sqlalchemy import create_engine, Column, Integer, String, Date, Numeric, ForeignKey, DateTime, UniqueConstraint, and_, or_, case, func, text, Text
from sqlalchemy.orm import sessionmaker, relationship, declarative_base, aliased, joinedload
from sqlalchemy.sql import func
from sqlalchemy.exc import NoResultFound, MultipleResultsFound

# Import the PostgreSQL specific UUID type
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from dotenv import load_dotenv

load_dotenv()

# Import the Quiz model from models.py
from models import Quiz
from models import (
    Base, 
    User, 
    GradeLevel,
    Strand, 
    Section, 
    SectionPeriod, 
    SectionSubject, 
    Attendance, 
    Grade, 
    GradingSystem, 
    GradingComponent, 
    GradableItem, 
    StudentScore, 
    TeacherLog, 
    StudentInfo, 
    Parent, 
    ParentPortalStudent,
    Session
)

# --- Flask App Configuration ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'supersecretkey_for_development_only')
app.permanent_session_lifetime = timedelta(days=30)
app.config['SESSION_COOKIE_NAME'] = 'sos_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True if using HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

@app.before_request
def make_session_permanent():
    session.permanent = True

# Database connection details   
DATABASE_URL = os.environ.get('DATABASE_URL')

print(f"DEBUG: DATABASE_URL being used: {DATABASE_URL}")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set. Please set it in your .env file or as a system environment variable before running the app.")

# --- SQLAlchemy Setup ---
# For Supabase free tier on Render: pool_size=2, max_overflow=1 (safe for free tier, avoids connection exhaustion)
engine = create_engine(
    DATABASE_URL,  # Use the pooled connection string from Supabase
    pool_size=20,   # Increased pool size for Supabase pooler
    max_overflow=10, # Allow 10 extra connections for short spikes
    pool_timeout=30,
)

# Define SQLAlchemy Models (including Parent for relationship)
# --- Teacher Log Model for Tracking Teacher Actions ---
def create_teacher_log(db_session, teacher_id, teacher_username, action_type, target_type, target_id, target_name, details=None, section_period_id=None, subject_id=None):
    """
    Helper function to create teacher log entries
    """
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

TEACHER_SPECIALIZATIONS_SHS = ['ICT', 'STEM', 'ABM', 'HUMSS', 'GAS', 'HE'] # Strands as specializations for SHS

GRADE_LEVELS_JHS = ['Grade 7', 'Grade 8', 'Grade 9', 'Grade 10']
GRADE_LEVELS_SHS = ['Grade 11', 'Grade 12']
ALL_GRADE_LEVELS = GRADE_LEVELS_JHS + GRADE_LEVELS_SHS

PERIOD_TYPES = {
    'JHS': ['Quarter 1', 'Quarter 2', 'Quarter 3', 'Quarter 4'],
    'SHS': ['1st Semester', '2nd Semester']
}
ATTENDANCE_STATUSES = ['present', 'absent', 'late', 'excused']

# --- Database Session Management per request ---
def open_db_session():
    g.session = Session()

def close_db_session(exception):
    db_session = g.pop('session', None)
    if db_session is not None:
        if exception:
            db_session.rollback()
        db_session.close()

# These need to be registered with the app directly
app.before_request(open_db_session)
app.teardown_appcontext(close_db_session)

# Helper function to get current school year options
def get_school_year_options():
    current_year = date.today().year
    # Include current, previous, and next academic years
    school_years = [f"{current_year}-{current_year+1}", f"{current_year-1}-{current_year}", f"{current_year+1}-{current_year+2}"]
    return sorted(list(set(school_years)), reverse=True) # Sort descending


# --- Authentication Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def user_type_required(*required_types):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_type' not in session:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login'))
            
            if session['user_type'] not in required_types:
                flash(f'You do not have permission to access this page. Requires {", ".join(required_types)} role.', 'danger')
                # Redirect to an appropriate dashboard based on user type
                if session['user_type'] == 'teacher':
                    return redirect(url_for('teacher_dashboard'))
                elif session['user_type'] == 'admin':
                    return redirect(url_for('admin_dashboard'))
                else:
                    return redirect(url_for('login'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Helper function to verify password
def verify_current_user_password(user_id, password):
    db_session = g.session
    user = db_session.query(User).filter_by(id=user_id).first()
    if user and check_password_hash(user.password_hash, password):
        return True
    return False

# Helper function to sync total grade to database
def sync_total_grade_to_database(db_session, student_id, subject_id, teacher_id, section_period):
    """
    Sync the calculated total grade from the grading system to the grades table.
    """
    try:
        # Get the grading system for this subject
        grading_system = db_session.query(GradingSystem).filter_by(section_subject_id=subject_id).first()
        if not grading_system:
            return False
        
        # Get all scores for this student in this subject
        all_student_scores_query = db_session.query(StudentScore).join(GradableItem).join(GradingComponent).filter(
            GradingComponent.system_id == grading_system.id,
            StudentScore.student_info_id == student_id
        ).all()
        student_scores_map = {s.item_id: s.score for s in all_student_scores_query}

        # Calculate total grade
        student_total_grade = decimal.Decimal('0.0')
        total_weight = 0
        
        for component in grading_system.components:
            component_items = component.items
            if not component_items:
                continue
            
            component_student_sum = sum((decimal.Decimal(student_scores_map.get(i.id, 0)) for i in component_items), decimal.Decimal(0))
            component_max_sum = sum((i.max_score for i in component_items), decimal.Decimal(0))

            if component_max_sum > 0:
                average = component_student_sum / component_max_sum
                weight = decimal.Decimal(component.weight) / decimal.Decimal('100.0')
                student_total_grade += average * weight
                total_weight += component.weight

        # Only save if we have a valid total weight
        if total_weight > 0:
            final_grade = student_total_grade * 100  # Convert to percentage
            
            # Check if grade already exists for this student/subject/period
            existing_grade = db_session.query(Grade).filter(
                Grade.student_info_id == student_id,
                Grade.section_subject_id == subject_id,
                Grade.semester == section_period.period_name,
                Grade.school_year == section_period.school_year
            ).first()

            if existing_grade:
                existing_grade.grade_value = final_grade
                existing_grade.teacher_id = teacher_id
            else:
                new_grade = Grade(
                    student_info_id=student_id,
                    section_subject_id=subject_id,
                    teacher_id=teacher_id,
                    grade_value=final_grade,
                    semester=section_period.period_name,
                    school_year=section_period.school_year
                )
                db_session.add(new_grade)
            
            return True
        return False
    except Exception as e:
        app.logger.error(f"Error syncing total grade: {e}")
        return False

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    """Redirect users to their appropriate dashboard based on account type"""
    user_type = session.get('user_type')
    if user_type == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif user_type == 'teacher':
        return redirect(url_for('teacher_dashboard'))
    else:
        # Fallback for unknown user types
        flash('Unknown user type. Please contact an administrator.', 'error')
        return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_type = request.form['user_type']
        grade_level_assigned = request.form.get('grade_level_assigned') # New field
        specialization = request.form.get('specialization') # This will be present for SHS, empty/None for JHS

        if not username or not password or not user_type:
            flash('All required fields are necessary.', 'error')
            return render_template('register.html', 
                                   all_grade_levels=ALL_GRADE_LEVELS,
                                   teacher_specializations_shs=TEACHER_SPECIALIZATIONS_SHS)
        
        if user_type == 'teacher':
            if not grade_level_assigned:
                flash('Assigned Grade Level is required for teachers.', 'error')
                return render_template('register.html', 
                                       all_grade_levels=ALL_GRADE_LEVELS,
                                       teacher_specializations_shs=TEACHER_SPECIALIZATIONS_SHS)
            
            # Server-side logic for specialization based on grade level
            if grade_level_assigned in GRADE_LEVELS_JHS:
                specialization = None # JHS teachers do not have a specific specialization (null in DB)
            elif grade_level_assigned in GRADE_LEVELS_SHS:
                if not specialization: # For SHS, specialization is still required
                    flash('Teacher specialization (strand) is required for Senior High School grade levels.', 'error')
                    return render_template('register.html', 
                                           all_grade_levels=ALL_GRADE_LEVELS,
                                           teacher_specializations_shs=TEACHER_SPECIALIZATIONS_SHS)
                # Ensure the chosen specialization is a valid SHS specialization
                if specialization not in TEACHER_SPECIALIZATIONS_SHS:
                    flash('Invalid specialization selected for Senior High School grade level.', 'error')
                    return render_template('register.html', 
                                           all_grade_levels=ALL_GRADE_LEVELS,
                                           teacher_specializations_shs=TEACHER_SPECIALIZATIONS_SHS)
            else: # Fallback for unexpected grade levels
                flash('Invalid Assigned Grade Level selected.', 'error')
                return render_template('register.html', 
                                       all_grade_levels=ALL_GRADE_LEVELS,
                                       teacher_specializations_shs=TEACHER_SPECIALIZATIONS_SHS)

        hashed_password = generate_password_hash(password)
        db_session = g.session
        try:
            existing_user = db_session.query(User).filter_by(username=username).first()
            if existing_user:
                flash('Username already exists. Please choose a different one.', 'error')
                return render_template('register.html', 
                                       all_grade_levels=ALL_GRADE_LEVELS,
                                       teacher_specializations_shs=TEACHER_SPECIALIZATIONS_SHS)

            new_user = User(
                username=username,
                password_hash=hashed_password,
                user_type=user_type,
                specialization=specialization if user_type == 'teacher' else None, # Store specialization (None for JHS)
                grade_level_assigned=grade_level_assigned if user_type == 'teacher' else None # Store grade level for teachers
            )
            db_session.add(new_user)
            db_session.commit()
            flash(f'Registration successful! You can now log in as a {user_type.capitalize()}.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error during registration: {e}")
            flash('An error occurred during registration. Please try again.', 'error')

    return render_template('register.html', 
                           all_grade_levels=ALL_GRADE_LEVELS,
                           teacher_specializations_shs=TEACHER_SPECIALIZATIONS_SHS)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if not username or not password:
            flash('Username and password are required.', 'error')
            return render_template('login.html')

        db_session = g.session
        user = db_session.query(User).filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            session.permanent = True
            session['user_id'] = str(user.id)
            session['username'] = user.username
            session['user_type'] = user.user_type
            session['specialization'] = user.specialization # Teacher specialization (will be None for JHS)
            session['grade_level_assigned'] = user.grade_level_assigned # Teacher assigned grade level

            flash('Welcome, you are logged in.', 'success')
            if session['user_type'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif session['user_type'] == 'teacher':
                return redirect(url_for('teacher_dashboard'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/teacher/section_period/<uuid:section_period_id>/attendance/history/<uuid:subject_id>')
@login_required
@user_type_required('teacher', 'admin')
def teacher_section_attendance_history(section_period_id, subject_id):
    db_session = g.session
    teacher_id = uuid.UUID(session['user_id'])

    # Get section period and subject details
    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand)
    ).filter(SectionPeriod.id == section_period_id).first()

    subject = db_session.query(SectionSubject).filter(
        SectionSubject.id == subject_id,
        SectionSubject.section_period_id == section_period_id
    ).first()

    if not section_period or not subject:
        flash('Section period or subject not found.', 'error')
        return redirect(url_for('teacher_dashboard'))

    # Check if teacher is assigned to this section period
    if str(section_period.assigned_teacher_id) != str(teacher_id):
        flash('You are not authorized to view this section\'s attendance.', 'error')
        return redirect(url_for('teacher_dashboard'))

    # Get all students in the section
    students = db_session.query(StudentInfo).filter(
        StudentInfo.section_period_id == section_period_id
    ).order_by(StudentInfo.name).all()

    # Calculate summary statistics for each student
    summary = []
    for student in students:
        attendance_records = db_session.query(Attendance).filter(
            Attendance.student_info_id == student.id,
            Attendance.section_subject_id == subject_id
        ).all()

        # Set gender to 'Unknown' if missing or empty
        gender = student.gender if student.gender else 'Unknown'

        stats = {
            'name': student.name,
            'gender': gender,  # Always set for template grouping
            'present_count': sum(1 for a in attendance_records if a.status == 'present'),
            'absent_count': sum(1 for a in attendance_records if a.status == 'absent'),
            'late_count': sum(1 for a in attendance_records if a.status == 'late'),
            'excused_count': sum(1 for a in attendance_records if a.status == 'excused')
        }
        summary.append(stats)

    # Get date-wise attendance summary
    dates_query = db_session.query(
        Attendance.attendance_date.label('date'),
        func.count(case((Attendance.status == 'present', 1))).label('present_count'),
        func.count(case((Attendance.status == 'absent', 1))).label('absent_count'),
        func.count(case((Attendance.status == 'late', 1))).label('late_count'),
        func.count(case((Attendance.status == 'excused', 1))).label('excused_count')
    ).filter(
        Attendance.section_subject_id == subject_id
    ).group_by(Attendance.attendance_date).order_by(Attendance.attendance_date.desc()).all()
    attendance_days_count = len(dates_query)

    return render_template('attendance_history.html',
                         section_period=section_period,
                         subject=subject,
                         summary=summary,
                         dates=dates_query,
                         attendance_days_count=attendance_days_count)

@app.route('/teacher/section_period/<uuid:section_period_id>/attendance/date/<uuid:subject_id>/<date>', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher', 'admin')
def teacher_section_attendance_date(section_period_id, subject_id, date):
    db_session = g.session
    teacher_id = uuid.UUID(session['user_id'])

    try:
        attendance_date = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format.', 'error')
        return redirect(url_for('teacher_section_attendance_history', section_period_id=section_period_id, subject_id=subject_id))

    # Get all students in the section period
    students = db_session.query(StudentInfo).filter(
        StudentInfo.section_period_id == section_period_id
    ).order_by(StudentInfo.name).all()

    # Build a map of student_id to attendance record for this date/subject
    attendance_map = {}
    attendance_records = db_session.query(Attendance).filter(
        Attendance.attendance_date == attendance_date,
        Attendance.section_subject_id == subject_id
    ).all()
    for record in attendance_records:
        attendance_map[str(record.student_info_id)] = record

    # If POST, update attendance records
    if request.method == 'POST':
        try:
            for student in students:
                status = request.form.get(f'status_{student.id}')
                notes = request.form.get(f'notes_{student.id}')
                if status:
                    record = attendance_map.get(str(student.id))
                    if record:
                        record.status = status
                        record.recorded_by = teacher_id
                        record.notes = notes if status in ['absent','late','excused'] else None
                    else:
                        new_attendance = Attendance(
                            student_info_id=student.id,
                            section_subject_id=subject_id,
                            attendance_date=attendance_date,
                            status=status,
                            recorded_by=teacher_id,
                            notes=notes if status in ['absent','late','excused'] else None
                        )
                        db_session.add(new_attendance)
            db_session.commit()
            flash('Attendance updated successfully!', 'success')
            return redirect(url_for('teacher_section_attendance_date', section_period_id=section_period_id, subject_id=subject_id, date=date))
        except Exception as e:
            db_session.rollback()
            flash(f'An error occurred while updating attendance: {e}', 'error')

    # Prepare attendance_records for template (list of (student, attendance))
    attendance_records = []
    total_present = total_absent = total_late = total_excused = 0
    total_boys = total_girls = 0
    for student in students:
        attendance = attendance_map.get(str(student.id))
        attendance_records.append((student, attendance))
        if attendance and attendance.status == 'present':
            if student.gender == 'Male':
                total_boys += 1
            elif student.gender == 'Female':
                total_girls += 1
        if attendance:
            if attendance.status == 'present':
                total_present += 1
            elif attendance.status == 'absent':
                total_absent += 1
            elif attendance.status == 'late':
                total_late += 1
            elif attendance.status == 'excused':
                total_excused += 1

    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand)
    ).filter(SectionPeriod.id == section_period_id).first()

    subject = db_session.query(SectionSubject).filter(
        SectionSubject.id == subject_id,
        SectionSubject.section_period_id == section_period_id
    ).first()

    if not section_period or not subject:
        flash('Section period or subject not found.', 'error')
        return redirect(url_for('teacher_dashboard'))

    # Show edit form if ?edit=1 in query or after POST
    show_edit = request.method == 'POST' or request.args.get('edit') == '1'
    ATTENDANCE_STATUSES = ['present', 'absent', 'late', 'excused']
    return render_template('date_attendance_details.html',
                         section_period=section_period,
                         subject=subject,
                         attendance_records=attendance_records,
                         date=attendance_date,
                         total_present=total_present,
                         total_absent=total_absent,
                         total_late=total_late,
                         total_excused=total_excused,
                         total_boys=total_boys,
                         total_girls=total_girls,
                         show_edit=show_edit,
                         attendance_statuses=ATTENDANCE_STATUSES)

# --- User Profile Management ---
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if session.get('user_type') == 'teacher' and not session.get('profile_unlocked'):
        flash('You must enter the admin password to access your profile.', 'warning')
        return redirect(url_for('teacher_dashboard'))

    db_session = g.session
    user = db_session.query(User).filter_by(id=session['user_id']).one()

    if request.method == 'POST':
        current_password = request.form.get('current_password')
        admin_password = request.form.get('admin_password')
        new_username = request.form.get('new_username', '').strip()
        new_password = request.form.get('new_password')
        confirm_new_password = request.form.get('confirm_new_password')

        # Verify current password
        if not verify_current_user_password(user.id, current_password):
            flash('Incorrect current password. No changes were saved.', 'error')
            return redirect(url_for('profile'))

        # Verify admin password (must match any admin account)
        if not admin_password:
            flash('Admin password is required to save changes.', 'error')
            return redirect(url_for('profile'))
        admin_user = db_session.query(User).filter_by(user_type='admin').first()
        admin_password_valid = False
        if admin_user:
            # Check all admin accounts
            admin_users = db_session.query(User).filter_by(user_type='admin').all()
            for admin in admin_users:
                if check_password_hash(admin.password_hash, admin_password):
                    admin_password_valid = True
                    break
        if not admin_password_valid:
            flash('Incorrect admin password. No changes were saved.', 'error')
            return redirect(url_for('profile'))

        # Track if any changes other than password were made to provide a specific message
        changes_made = False

        # Update username if a new one is provided and is different
        if new_username and new_username != user.username:
            # Check if new username is already taken
            if db_session.query(User).filter(User.username == new_username, User.id != user.id).first():
                flash('That username is already taken. Please choose another.', 'error')
                return redirect(url_for('profile'))
            user.username = new_username
            session['username'] = new_username # Update session
            flash('Username updated successfully!', 'success')
            changes_made = True

        # Update user type and teacher specific fields
        new_user_type = request.form.get('user_type')
        new_grade_level_assigned = request.form.get('grade_level_assigned')
        new_specialization = request.form.get('specialization')

        # Check if user type is being changed
        user_type_changed = (new_user_type != user.user_type)
        grade_level_changed = (new_grade_level_assigned != user.grade_level_assigned)
        specialization_changed = (new_specialization != user.specialization)

        if user_type_changed or grade_level_changed or specialization_changed:
            # Validate new user type and teacher fields
            if new_user_type not in ['admin', 'teacher']:
                flash('Invalid user type selected.', 'error')
                return redirect(url_for('profile'))

            if new_user_type == 'teacher':
                if not new_grade_level_assigned:
                    flash('Assigned Grade Level is required for teachers.', 'error')
                    return redirect(url_for('profile'))
                
                if new_grade_level_assigned in GRADE_LEVELS_JHS:
                    new_specialization = None # JHS teachers do not have specialization
                elif new_grade_level_assigned in GRADE_LEVELS_SHS:
                    if not new_specialization:
                        flash('Teacher specialization (strand) is required for Senior High School grade levels.', 'error')
                        return redirect(url_for('profile'))
                    if new_specialization not in TEACHER_SPECIALIZATIONS_SHS:
                        flash('Invalid specialization selected for Senior High School grade level.', 'error')
                        return redirect(url_for('profile'))
                else:
                    flash('Invalid Assigned Grade Level selected.', 'error')
                    return redirect(url_for('profile'))

                user.user_type = new_user_type
                user.grade_level_assigned = new_grade_level_assigned
                user.specialization = new_specialization
                session['user_type'] = new_user_type
                session['grade_level_assigned'] = new_grade_level_assigned
                session['specialization'] = new_specialization
                flash('Account type updated to Teacher successfully!', 'success')
                changes_made = True
            elif new_user_type == 'admin':
                user.user_type = new_user_type
                user.grade_level_assigned = None # Admins do not have these fields
                user.specialization = None
                session['user_type'] = new_user_type
                session['grade_level_assigned'] = None
                session['specialization'] = None
                flash('Account type updated to Admin successfully!', 'success')
                changes_made = True

        # Update password if a new one is provided
        if new_password:
            if len(new_password) < 6:
                flash('New password must be at least 6 characters long.', 'error')
                return redirect(url_for('profile'))
            if new_password != confirm_new_password:
                flash('New passwords do not match.', 'error')
                return redirect(url_for('profile'))
            
            user.password_hash = generate_password_hash(new_password)
            flash('Password updated successfully!', 'success')
            changes_made = True

        db_session.commit()

        if not changes_made:
            flash('No changes were provided.', 'info')

        return redirect(url_for('profile'))

    # Reset the lock after the profile is loaded.
    if 'profile_unlocked' in session:
        session.pop('profile_unlocked', None)

    return render_template('profile.html', 
                           user=user,
                           all_grade_levels=ALL_GRADE_LEVELS,
                           teacher_specializations_shs=TEACHER_SPECIALIZATIONS_SHS)

@app.route('/verify_password_for_profile', methods=['POST'])
@login_required
def verify_password_for_profile():
    db_session = g.session
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'User not found.'}), 404

    user = db_session.query(User).filter_by(id=user_id).one_or_none()

    if not user:
        return jsonify({'success': False, 'message': 'User not found.'})

    if not request.json:
        return jsonify({'success': False, 'message': 'Invalid request.'}), 400

    password = request.json.get('password')
    
    # Check all admin accounts for a matching password
    admins = db_session.query(User).filter_by(user_type='admin').all()
    for admin in admins:
        if check_password_hash(admin.password_hash, password):
            session['profile_unlocked'] = True
            return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Incorrect password.'})

# --- Admin Dashboard Routes ---
@app.route('/admin_dashboard')
@login_required
@user_type_required('admin')
def admin_dashboard():
    db_session = g.session
    admin_id = uuid.UUID(session['user_id'])

    # Eager load sections and section_periods for grade levels
    grade_levels = db_session.query(GradeLevel).options(
        joinedload(GradeLevel.sections).joinedload(Section.section_periods)
    ).filter_by(created_by=admin_id).all()

    # Get counts for summary
    section_count = db_session.query(Section).join(GradeLevel).filter(GradeLevel.created_by == admin_id).count()
    student_count = db_session.query(StudentInfo).join(SectionPeriod).join(Section).join(GradeLevel).filter(GradeLevel.created_by == admin_id).count()

    # Paginate students (first 20)
    students = db_session.query(StudentInfo).join(SectionPeriod).join(Section).join(GradeLevel).filter(GradeLevel.created_by == admin_id).limit(20).all()

    return render_template('admin_dashboard.html',
                         grade_levels=grade_levels,
                         section_count=section_count,
                         student_count=student_count,
                         students=students)

@app.route('/add_grade_level', methods=['GET', 'POST'])
@login_required
@user_type_required('admin')
def add_grade_level():
    if request.method == 'POST':
        grade_level_name = request.form.get('grade_level_name')
        level_type = request.form.get('level_type')

        if not grade_level_name or not level_type:
            flash('Grade level name and type are required.', 'error')
            return redirect(url_for('admin_dashboard'))

        if level_type not in ['JHS', 'SHS']:
            flash('Invalid level type.', 'error')
            return redirect(url_for('admin_dashboard'))

        # Check if grade level already exists
        existing_level = g.session.query(GradeLevel).filter_by(name=grade_level_name).first()
        if existing_level:
            flash(f'Grade level "{grade_level_name}" already exists.', 'error')
            return redirect(url_for('admin_dashboard'))

        # Create new grade level
        new_grade_level = GradeLevel(
            name=grade_level_name,
            level_type=level_type,
            created_by=uuid.UUID(session['user_id'])
        )

        try:
            g.session.add(new_grade_level)
            g.session.commit()
            flash(f'Grade level "{grade_level_name}" created successfully!', 'success')
        except Exception as e:
            g.session.rollback()
            flash(f'An error occurred: {e}', 'error')

        return redirect(url_for('admin_dashboard'))

    # For GET request, render the form
    return render_template('add_grade_level.html')

@app.route('/grade_level/<uuid:grade_level_id>/delete', methods=['POST'])
@login_required
@user_type_required('admin')
def delete_grade_level(grade_level_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    password = request.form.get('password')

    if not password or not verify_current_user_password(user_id, password):
        return jsonify({'success': False, 'message': 'Incorrect password.'})

    grade_level_to_delete = db_session.query(GradeLevel).filter_by(id=grade_level_id, created_by=user_id).first()

    if not grade_level_to_delete:
        return jsonify({'success': False, 'message': 'Grade Level not found or you do not have permission to delete it.'})

    try:
        db_session.delete(grade_level_to_delete)
        db_session.commit()
        return jsonify({
            'success': True, 
            'message': f'Grade Level "{grade_level_to_delete.name}" and all its associated data (strands, sections, periods, students, subjects, attendance, and grades) have been deleted.',
            'redirect_url': url_for('admin_dashboard')
        })
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting grade level: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred while deleting the grade level.'})

@app.route('/grade_level/<uuid:grade_level_id>/edit', methods=['POST'])
@login_required
@user_type_required('admin')
def edit_grade_level(grade_level_id):
    try:
        grade_level = g.session.query(GradeLevel).filter(
            GradeLevel.id == grade_level_id,
            GradeLevel.created_by == uuid.UUID(session['user_id'])
        ).one()
        
        new_name = request.form.get('grade_level_name')
        new_type = request.form.get('level_type')

        if not new_name or not new_type:
            flash('Grade level name and type are required.', 'error')
            return redirect(url_for('admin_dashboard'))

        if new_type not in ['JHS', 'SHS']:
            flash('Invalid level type.', 'error')
            return redirect(url_for('admin_dashboard'))

        # Check if the new name already exists
        existing_level = g.session.query(GradeLevel).filter(
            GradeLevel.name == new_name,
            GradeLevel.id != grade_level_id
        ).first()

        if existing_level:
            flash(f'Grade level "{new_name}" already exists.', 'error')
            return redirect(url_for('admin_dashboard'))

        grade_level.name = new_name
        grade_level.level_type = new_type
        g.session.commit()
        flash('Grade level updated successfully!', 'success')

    except NoResultFound:
        flash('Grade level not found or you do not have permission to edit it.', 'error')
    except Exception as e:
        g.session.rollback()
        flash(f'An error occurred: {e}', 'error')

    return redirect(url_for('admin_dashboard'))

@app.route('/grade_level/<uuid:grade_level_id>')
@login_required
@user_type_required('admin')
def grade_level_details(grade_level_id):
    db_session = g.session
    admin_id = uuid.UUID(session['user_id'])
    
    grade_level = db_session.query(GradeLevel).filter_by(id=grade_level_id, created_by=admin_id).first()
    if not grade_level:
        flash('Grade Level not found or you do not have permission to view it.', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    sections = db_session.query(Section).options(joinedload(Section.strand)).filter_by(grade_level_id=grade_level_id).order_by(Section.name).all()
    
    for section in sections:
        # --- Add available_accounts calculation ---
        teacher_query = db_session.query(User).filter(User.user_type == 'teacher')
        teacher_query = teacher_query.filter(User.grade_level_assigned == grade_level.name)

        if grade_level.level_type == 'JHS':
            teacher_query = teacher_query.filter(User.specialization.is_(None))
        elif grade_level.level_type == 'SHS' and section.strand:
            teacher_query = teacher_query.filter(User.specialization == section.strand.name)
        
        section.available_accounts = teacher_query.order_by(User.username).all()

        # --- Add average_grade calculation for admin ---
        section.section_period_averages = []
        section_periods = db_session.query(SectionPeriod).filter_by(section_id=section.id).all()
        for period in section_periods:
            student_ids = db_session.query(StudentInfo.id).filter(StudentInfo.section_period_id == period.id).all()
            student_ids = [s.id for s in student_ids]
            total_grades_sum = 0
            total_grades_count = 0
            if student_ids:
                all_grades_summary = db_session.query(func.sum(Grade.grade_value), func.count(Grade.grade_value)).\
                    filter(Grade.student_info_id.in_(student_ids),
                           Grade.semester == period.period_name,
                           Grade.school_year == period.school_year).one_or_none()
                if all_grades_summary and all_grades_summary[0] is not None and all_grades_summary[1] > 0:
                    total_grades_sum = float(all_grades_summary[0])
                    total_grades_count = all_grades_summary[1]
            avg = round(total_grades_sum / total_grades_count, 2) if total_grades_count > 0 else None
            section.section_period_averages.append({
                'period_name': period.period_name,
                'school_year': period.school_year,
                'average': avg
            })
        # For backward compatibility, set section.average_grade to the most recent period's average (if any)
        if section.section_period_averages:
            section.average_grade = section.section_period_averages[0]['average']
        else:
            section.average_grade = None

    strands = []
    if grade_level.level_type == 'SHS':
        strands = db_session.query(Strand).filter_by(grade_level_id=grade_level_id).order_by(Strand.name).all()

    return render_template('grade_level_details.html', 
                           grade_level=grade_level, 
                           sections=sections, 
                           strands=strands)

@app.route('/grade_level/<uuid:grade_level_id>/add_strand', methods=['GET', 'POST'])
@login_required
@user_type_required('admin')
def add_strand(grade_level_id):
    db_session = g.session
    admin_id = uuid.UUID(session['user_id'])

    grade_level = db_session.query(GradeLevel).filter_by(id=grade_level_id, created_by=admin_id).first()
    if not grade_level or grade_level.level_type != 'SHS':
        flash('Strands can only be added to Senior High School grade levels (Grade 11 or Grade 12), or grade level not found/permission denied.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        strand_name = request.form['name'].strip()
        if not strand_name:
            flash('Strand name cannot be empty.', 'error')
            return render_template('add_strand.html', grade_level=grade_level)

        try:
            existing_strand = db_session.query(Strand).filter(
                func.lower(Strand.name) == func.lower(strand_name),
                Strand.grade_level_id == grade_level_id
            ).first()
            if existing_strand:
                flash(f'Strand "{strand_name}" already exists for {grade_level.name}.', 'error')
                return render_template('add_strand.html', grade_level=grade_level)

            new_strand = Strand(name=strand_name, grade_level_id=grade_level_id, created_by=admin_id)
            db_session.add(new_strand)
            db_session.commit()
            flash(f'Strand "{strand_name}" added to {grade_level.name} successfully!', 'success')
            return redirect(url_for('grade_level_details', grade_level_id=grade_level_id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error adding strand: {e}")
            flash('An error occurred while adding the strand. Please try again.', 'error')

    return render_template('add_strand.html', grade_level=grade_level)


@app.route('/strand/<uuid:strand_id>/edit', methods=['GET', 'POST'])
@login_required
@user_type_required('admin')
def edit_strand(strand_id):
    db_session = g.session
    admin_id = uuid.UUID(session['user_id'])

    strand = db_session.query(Strand).options(joinedload(Strand.grade_level)).filter_by(id=strand_id, created_by=admin_id).first()
    if not strand:
        flash('Strand not found or you do not have permission to edit it.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        new_strand_name = request.form['name'].strip()
        if not new_strand_name:
            flash('Strand name cannot be empty.', 'error')
            return render_template('edit_strand.html', strand=strand)

        try:
            existing_strand = db_session.query(Strand).filter(
                func.lower(Strand.name) == func.lower(new_strand_name),
                Strand.grade_level_id == strand.grade_level.id, # Check uniqueness within the same grade level
                Strand.id != strand_id
            ).first()
            if existing_strand:
                flash(f'Strand "{new_strand_name}" already exists for {strand.grade_level.name}.', 'error')
                return render_template('edit_strand.html', strand=strand)
            
            strand.name = new_strand_name
            db_session.commit()
            flash(f'Strand "{strand.name}" updated successfully!', 'success')
            return redirect(url_for('grade_level_details', grade_level_id=strand.grade_level.id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error editing strand: {e}")
            flash('An error occurred while updating the strand. Please try again.', 'error')

    return render_template('edit_strand.html', strand=strand)


@app.route('/strand/<uuid:strand_id>/delete', methods=['POST'])
@login_required
@user_type_required('admin')
def delete_strand(strand_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    password = request.form.get('password')

    if not password or not verify_current_user_password(user_id, password):
        return jsonify({'success': False, 'message': 'Incorrect password.'})

    strand_to_delete = db_session.query(Strand).options(joinedload(Strand.grade_level)).filter_by(id=strand_id, created_by=user_id).first()

    if not strand_to_delete:
        return jsonify({'success': False, 'message': 'Strand not found or you do not have permission to delete it.'})

    redirect_grade_level_id = strand_to_delete.grade_level.id if strand_to_delete.grade_level else None

    try:
        db_session.delete(strand_to_delete)
        db_session.commit()
        return jsonify({'success': True, 'message': f'Strand "{strand_to_delete.name}" and all its associated data have been deleted.'})
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting strand: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred while deleting the strand.'})

# NEW ROUTE: For viewing a specific strand's details (sections within it)
@app.route('/strand_details/<uuid:strand_id>')
@login_required
@user_type_required('admin')
def strand_details(strand_id):
    db_session = g.session
    admin_id = uuid.UUID(session['user_id'])

    strand = db_session.query(Strand).options(joinedload(Strand.grade_level)).filter_by(id=strand_id, created_by=admin_id).first()
    if not strand:
        flash('Strand not found or you do not have permission to view it.', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    sections = db_session.query(Section).filter_by(strand_id=strand_id, grade_level_id=strand.grade_level.id).order_by(Section.name).all()

    # Attach available_accounts, assigned_user_id, and average_grade to each section (SHS)
    for section in sections:
        teacher_query = db_session.query(User).filter(User.user_type == 'teacher')
        teacher_query = teacher_query.filter(User.grade_level_assigned == strand.grade_level.name)
        teacher_query = teacher_query.filter(User.specialization == strand.name)
        section.available_accounts = teacher_query.order_by(User.username).all()
        section.assigned_user_id = section.assigned_user_id

        # --- Add average_grade calculation for admin ---
        section.section_period_averages = []
        section_periods = db_session.query(SectionPeriod).filter_by(section_id=section.id).all()
        for period in section_periods:
            student_ids = db_session.query(StudentInfo.id).filter(StudentInfo.section_period_id == period.id).all()
            student_ids = [s.id for s in student_ids]
            total_grades_sum = 0
            total_grades_count = 0
            if student_ids:
                all_grades_summary = db_session.query(func.sum(Grade.grade_value), func.count(Grade.grade_value)).\
                    filter(Grade.student_info_id.in_(student_ids),
                           Grade.semester == period.period_name,
                           Grade.school_year == period.school_year).one_or_none()
                if all_grades_summary and all_grades_summary[0] is not None and all_grades_summary[1] > 0:
                    total_grades_sum = float(all_grades_summary[0])
                    total_grades_count = all_grades_summary[1]
            avg = round(total_grades_sum / total_grades_count, 2) if total_grades_count > 0 else None
            section.section_period_averages.append({
                'period_name': period.period_name,
                'school_year': period.school_year,
                'average': avg
            })
        # For backward compatibility, set section.average_grade to the most recent period's average (if any)
        if section.section_period_averages:
            section.average_grade = section.section_period_averages[0]['average']
        else:
            section.average_grade = None

    return render_template('strand_details.html',
                           strand=strand,
                           sections=sections)


# MODIFIED: add_section now explicitly tied to a strand_id for SHS, or grade_level_id for JHS
@app.route('/add_section/<uuid:parent_id>/<string:parent_type>', methods=['GET', 'POST'])
@login_required
@user_type_required('admin')
def add_section(parent_id, parent_type):
    db_session = g.session
    admin_id = uuid.UUID(session['user_id'])
    
    grade_level = None
    strand = None

    if parent_type == 'grade_level': # For JHS sections
        grade_level = db_session.query(GradeLevel).filter_by(id=parent_id, created_by=admin_id).first()
        if not grade_level:
            flash('Grade Level not found or you do not have permission.', 'danger')
            return redirect(url_for('admin_dashboard'))
        if grade_level.level_type == 'SHS':
            flash('Sections for Senior High School must be added under a specific Strand. Please select a Strand first.', 'danger')
            return redirect(url_for('grade_level_details', grade_level_id=grade_level.id))
    elif parent_type == 'strand': # For SHS sections
        strand = db_session.query(Strand).options(joinedload(Strand.grade_level)).filter_by(id=parent_id, created_by=admin_id).first()
        if not strand:
            flash('Strand not found or you do not have permission.', 'danger')
            return redirect(url_for('admin_dashboard'))
        grade_level = strand.grade_level
    else:
        flash('Invalid parent type for adding a section.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        section_name = request.form['name'].strip()
        if not section_name:
            flash('Section name cannot be empty.', 'error')
            return render_template('add_section.html', grade_level=grade_level, strand=strand)

        strand_id_to_save = strand.id if strand else None # If it's SHS, get strand_id, else None

        try:
            existing_section_query = db_session.query(Section).filter(
                func.lower(Section.name) == func.lower(section_name),
                Section.grade_level_id == grade_level.id,
                Section.strand_id == strand_id_to_save # Crucial for uniqueness and correct linking
            )
            existing_section = existing_section_query.first()

            if existing_section:
                flash(f'Section "{section_name}" already exists for this grade level and strand (if applicable).', 'error')
                return render_template('add_section.html', grade_level=grade_level, strand=strand)

            new_section = Section(
                name=section_name, 
                grade_level_id=grade_level.id, 
                strand_id=strand_id_to_save, 
                created_by=admin_id
            )
            db_session.add(new_section)
            db_session.commit()
            
            flash_message = f'Section "{section_name}" added to {grade_level.name} successfully!'
            if strand:
                flash_message = f'Section "{section_name}" added to {strand.name} Strand ({grade_level.name}) successfully!'
            
            flash(flash_message, 'success')

            if strand:
                return redirect(url_for('strand_details', strand_id=strand.id))
            else:
                return redirect(url_for('grade_level_details', grade_level_id=grade_level.id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error adding section: {e}")
            flash('An error occurred while adding the section. Please try again.', 'error')

    return render_template('add_section.html', grade_level=grade_level, strand=strand)


# MODIFIED: delete_section_admin now redirects based on where the section was added from (grade_level_details or strand_details)
@app.route('/section/<uuid:section_id>/delete_admin', methods=['POST'])
@login_required
@user_type_required('admin')
def delete_section_admin(section_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    password = request.form.get('password')

    if not password or not verify_current_user_password(user_id, password):
        return jsonify({'success': False, 'message': 'Incorrect password.'})
    
    section_to_delete = db_session.query(Section).options(
        joinedload(Section.grade_level),
        joinedload(Section.strand)
    ).filter_by(id=section_id, created_by=user_id).first()

    if not section_to_delete:
        return jsonify({'success': False, 'message': 'Section not found or you do not have permission to delete it.'})
    
    redirect_url_after_delete = url_for('admin_dashboard') # Default fallback

    if section_to_delete.strand_id: # If section belonged to a strand (SHS)
        redirect_url_after_delete = url_for('strand_details', strand_id=section_to_delete.strand_id)
    elif section_to_delete.grade_level_id: # If section belonged directly to a grade level (JHS)
        redirect_url_after_delete = url_for('grade_level_details', grade_level_id=section_to_delete.grade_level_id)


    try:
        db_session.delete(section_to_delete)
        db_session.commit()
        return jsonify({'success': True, 'message': f'Section "{section_to_delete.name}" and all its associated data have been deleted.', 'redirect_url': redirect_url_after_delete})
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting section: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred while deleting the section.'})


@app.route('/section/<uuid:section_id>')
@login_required
@user_type_required('admin', 'teacher')
def section_details(section_id):
    try:
        # Eagerly load related data to prevent extra queries in the template
        section = g.session.query(Section).options(
        joinedload(Section.grade_level),
            joinedload(Section.strand),
            joinedload(Section.section_periods).joinedload(SectionPeriod.assigned_teacher)
        ).filter(Section.id == section_id).one()

        school_year_options = get_school_year_options()
        period_type = section.grade_level.level_type
        period_options = PERIOD_TYPES.get(period_type, [])

        # Logic to get available teachers for the dropdown
        available_teachers = []
        if period_type: # Only fetch teachers if there's a valid period type
            specialization_filter = section.strand.name if period_type == 'SHS' and section.strand else None
            grade_level_filter = section.grade_level.name
            
            teacher_query = g.session.query(User).filter(User.user_type == 'teacher')
            
            if specialization_filter:
                teacher_query = teacher_query.filter(User.specialization == specialization_filter)
            if grade_level_filter:
                # JHS teachers can be assigned to any JHS grade, so check if assigned is in the JHS list
                if section.grade_level.level_type == 'JHS':
                    teacher_query = teacher_query.filter(User.grade_level_assigned.in_(GRADE_LEVELS_JHS))
                else:
                     teacher_query = teacher_query.filter(User.grade_level_assigned == grade_level_filter)
            
            available_teachers = teacher_query.order_by(User.username).all()

        return render_template('section_details.html',
                                   section=section,
                                   section_periods=section.section_periods,
                           period_type=period_type,
                                   period_options=period_options,
                                   school_year_options=school_year_options,
                                   available_teachers=available_teachers)
    except NoResultFound:
        flash('Section not found.', 'error')
        return redirect(url_for('admin_dashboard'))


@app.route('/section/<uuid:section_id>/add_period', methods=['GET', 'POST'])
@login_required
@user_type_required('admin')
def add_section_period(section_id): # Renamed from add_section_semester
    section = g.session.query(Section).options(joinedload(Section.grade_level), joinedload(Section.section_periods)).filter(Section.id == section_id).one_or_none()

    if not section:
        flash('Section not found.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    # --- RESTRICTION LOGIC ---
    period_type = section.grade_level.level_type
    existing_periods_count = len(section.section_periods)

    if period_type == 'SHS' and existing_periods_count >= 2:
        flash('Cannot add more than 2 semesters for a Senior High School section.', 'warning')
        return redirect(url_for('section_details', section_id=section_id))
    
    if period_type == 'JHS' and existing_periods_count >= 4:
        flash('Cannot add more than 4 quarters for a Junior High School section.', 'warning')
        return redirect(url_for('section_details', section_id=section_id))
    # --- END RESTRICTION LOGIC ---

    if request.method == 'POST':
        period_name = request.form.get('period_name')
        school_year = request.form.get('school_year')
        assigned_teacher_id_str = request.form.get('assigned_teacher_id')

        assigned_teacher_id = uuid.UUID(assigned_teacher_id_str) if assigned_teacher_id_str else None

        period_options = PERIOD_TYPES.get(section.grade_level.level_type, [])
        if not period_name or not school_year or period_name not in period_options:
            flash('Invalid form submission. Please check the period name and school year.', 'error')
            school_year_options = get_school_year_options()
            teacher_query = g.session.query(User).filter(User.user_type == 'teacher')
            available_teachers = teacher_query.order_by(User.username).all()
            return render_template('add_section_period.html', section=section, school_year_options=school_year_options, period_options=period_options, available_teachers=available_teachers), 400

        existing_period = g.session.query(SectionPeriod).filter_by(
            section_id=section_id,
            period_name=period_name,
            school_year=school_year
            ).first()

        if existing_period:
            flash(f'The period "{period_name}" for school year {school_year} already exists for this section.', 'error')
            # Re-render form with context
            school_year_options = get_school_year_options()
            period_options = PERIOD_TYPES.get(section.grade_level.level_type, [])
            teacher_query = g.session.query(User).filter(User.user_type == 'teacher')
            available_teachers = teacher_query.order_by(User.username).all()
            return render_template('add_section_period.html', section=section, school_year_options=school_year_options, period_options=period_options, available_teachers=available_teachers), 400

        new_period = SectionPeriod(
                section_id=section_id,
            period_type='Semester' if section.grade_level.level_type == 'SHS' else 'Quarter',
                period_name=period_name,
                school_year=school_year,
            assigned_teacher_id=assigned_teacher_id,
            created_by_admin=uuid.UUID(session['user_id'])
            )
        
        g.session.add(new_period)
        g.session.commit()
            
        flash(f'{new_period.period_name} for school year {new_period.school_year} created successfully!', 'success')
        return redirect(url_for('section_details', section_id=section_id))

    # Determine period options for the form
    level_type = section.grade_level.level_type
    period_options = PERIOD_TYPES.get(level_type, [])
    school_year_options = get_school_year_options()
    
    # Logic to get available teachers for the dropdown
    specialization_filter = section.strand.name if level_type == 'SHS' and section.strand else None
    grade_level_filter = section.grade_level.name
    
    teacher_query = g.session.query(User).filter(User.user_type == 'teacher')
    
    if specialization_filter:
        teacher_query = teacher_query.filter(User.specialization == specialization_filter)
    
    if level_type == 'JHS':
         teacher_query = teacher_query.filter(User.grade_level_assigned.in_(GRADE_LEVELS_JHS))
    else: #SHS
         teacher_query = teacher_query.filter(User.grade_level_assigned == grade_level_filter)
    
    available_teachers = teacher_query.order_by(User.username).all()

    return render_template('add_section_period.html', 
                           section=section, 
                           school_year_options=school_year_options,
                           available_teachers=available_teachers,
                           period_options=period_options)


@app.route('/section_period/<uuid:section_period_id>/delete', methods=['POST'])
@login_required
@user_type_required('admin')
def delete_section_period(section_period_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    password = request.form.get('password')

    if not password or not verify_current_user_password(user_id, password):
        return jsonify({'success': False, 'message': 'Incorrect password.'})

    section_period_to_delete = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand) # Load strand via section
    ).filter_by(id=section_period_id, created_by_admin=user_id).first()

    if not section_period_to_delete:
        return jsonify({'success': False, 'message': 'Period not found or you do not have permission to delete it.'})
    
    redirect_url_after_delete = url_for('admin_dashboard') # Default fallback

    if section_period_to_delete.section and section_period_to_delete.section.strand_id: # If section belonged to a strand (SHS)
        redirect_url_after_delete = url_for('strand_details', strand_id=section_period_to_delete.section.strand_id)
    elif section_period_to_delete.section and section_period_to_delete.section.grade_level_id: # If section belonged directly to a grade level (JHS)
        redirect_url_after_delete = url_for('section_details', section_id=section_period_to_delete.section.id) # Corrected: go to section details
    

    try:
        db_session.delete(section_period_to_delete)
        db_session.commit()
        period_info = f"{section_period_to_delete.period_name} {section_period_to_delete.school_year}"
        if section_period_to_delete.section and section_period_to_delete.section.strand: # Check strand via section
            period_info += f" ({section_period_to_delete.section.strand.name})"
        return jsonify({'success': True, 'message': f'Period "{period_info}" and all its associated students, subjects, attendance, and grades have been deleted.', 'redirect_url': redirect_url_after_delete})
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting section period: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred while deleting the period.'})


@app.route('/section_period/<uuid:section_period_id>')
@login_required
@user_type_required('admin', 'teacher') # Allow both admins and teachers
def section_period_details(section_period_id):
    try:
        db_session = g.session
        user_type = session['user_type']
        user_id = uuid.UUID(session['user_id'])

        section_period = db_session.query(SectionPeriod).options(
            joinedload(SectionPeriod.section).joinedload(Section.grade_level),
            joinedload(SectionPeriod.section).joinedload(Section.strand),
            joinedload(SectionPeriod.assigned_teacher)
        ).filter(SectionPeriod.id == section_period_id).one()

        # --- Data Sync Logic ---
        # For SHS/semesters, only show students for the current period
        students = db_session.query(StudentInfo).options(joinedload(StudentInfo.parent)).filter(StudentInfo.section_period_id == section_period_id).order_by(StudentInfo.name).all()
        for student in students:
            # Only average grades for the current period (semester and school year)
            grades = db_session.query(Grade.grade_value).filter(
                Grade.student_info_id == student.id,
                Grade.semester == section_period.period_name,
                Grade.school_year == section_period.school_year
            ).all()
            if grades:
                student.average_grade = sum(g[0] for g in grades) / len(grades)
            else:
                student.average_grade = None

        # --- FIX: Fetch parents for the "Assign Parent" modal ---
        parents = db_session.query(Parent).order_by(Parent.first_name, Parent.last_name).all()
        parents_dict = {p.id: p for p in parents}

        # --- FIX: Fetch all manageable section periods for the "Edit Student" modal dropdown ---
        section_periods_for_dropdown = []
        if user_type == 'admin':
            admin_id = uuid.UUID(session['user_id'])
            section_periods_for_dropdown = db_session.query(SectionPeriod).options(
                joinedload(SectionPeriod.section).joinedload(Section.grade_level),
                joinedload(SectionPeriod.section).joinedload(Section.strand)
            ).filter_by(created_by_admin=admin_id).join(Section).outerjoin(Strand).order_by(
                SectionPeriod.school_year.desc(),
                SectionPeriod.period_name,
                Section.name.asc(),
                Strand.name.asc().nulls_first()
            ).all()
        else:  # teacher
            section_periods_for_dropdown = db_session.query(SectionPeriod).options(
                joinedload(SectionPeriod.section).joinedload(Section.grade_level),
                joinedload(SectionPeriod.section).joinedload(Section.strand)
            ).filter_by(assigned_teacher_id=user_id).join(Section).outerjoin(Strand).order_by(
                SectionPeriod.school_year.desc(),
                SectionPeriod.period_name,
                Section.name.asc(),
                Strand.name.asc().nulls_first()
            ).all()

        # Fetch subjects - show all subjects if teacher is assigned to this section period
        user_id = uuid.UUID(session['user_id'])
        user_type = session['user_type']
        
        # Check if teacher is assigned to this section period
        is_assigned_teacher = str(section_period.assigned_teacher_id) == str(user_id)
        
        if is_assigned_teacher or user_type == 'admin':
            # If teacher is assigned to this period or user is admin, show all subjects
            section_subjects = g.session.query(SectionSubject).filter(
                SectionSubject.section_period_id == section_period_id
            ).order_by(SectionSubject.subject_name).all()
        else:
            # If not assigned, only show subjects created by this teacher
            section_subjects = g.session.query(SectionSubject).filter(
                SectionSubject.section_period_id == section_period_id,
                SectionSubject.created_by_teacher_id == user_id
            ).order_by(SectionSubject.subject_name).all()
    
        # Use different templates based on user type
        template = 'section_period_details.html' if user_type == 'admin' else 'teacher_section_period_details.html'
        return render_template(template,
                               section_period=section_period,
                               students=students,
                               section_subjects=section_subjects,
                               parents=parents,
                               parents_dict=parents_dict,
                               section_periods_for_dropdown=section_periods_for_dropdown)
    except NoResultFound:
        flash('Section period not found.', 'error')
        return redirect(url_for('teacher_dashboard') if session.get('user_type') == 'teacher' else url_for('admin_dashboard'))


@app.route('/assign_parent', methods=['POST'])
@login_required
@user_type_required('admin')
def assign_parent():
    db_session = g.session
    data = request.get_json()
    student_id = data.get('student_id')
    parent_id = data.get('parent_id')

    if not student_id or not parent_id:
        return jsonify({'success': False, 'message': 'Missing student or parent ID.'})

    student = db_session.query(StudentInfo).filter_by(id=student_id).first()
    parent = db_session.query(Parent).filter_by(id=parent_id).first()

    if not student or not parent:
        return jsonify({'success': False, 'message': 'Student or Parent not found.'})

    try:
        student.parent_id = uuid.UUID(parent_id)
        db_session.commit()

        # --- Improved Parent Portal Sync Logic ---
        success, message = sync_student_to_parent_portal(student, uuid.UUID(parent_id), app.logger)
        if not success:
            app.logger.error(f"Parent portal sync failed: {message}")
            # Optionally, you can flash a message or return an error to the admin here
            # flash(f'Parent portal sync failed: {message}', 'error')

        return jsonify({'success': True, 'message': 'Parent assigned successfully!'})
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error assigning parent: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while assigning the parent.'})

@app.route('/unassign_parent', methods=['POST'])
@login_required
@user_type_required('admin')
def unassign_parent():
    db_session = g.session
    data = request.get_json()
    student_id = data.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': 'Missing student ID.'})
    student = db_session.query(StudentInfo).filter_by(id=student_id).first()
    if not student:
        return jsonify({'success': False, 'message': 'Student not found.'})
    try:
        student.parent_id = None
        db_session.commit()
        return jsonify({'success': True, 'message': 'Parent unassigned successfully!'})
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error unassigning parent: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while unassigning the parent.'})

@app.route('/section_period/<uuid:section_period_id>/add_student', methods=['GET', 'POST'])
@login_required
@user_type_required('admin', 'teacher')
def add_student_to_section_period(section_period_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    user_type = session['user_type']

    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section)
    ).filter(SectionPeriod.id==section_period_id).first()

    if not section_period:
        flash('Period not found.', 'danger')
        return redirect(url_for('teacher_dashboard') if user_type == 'teacher' else url_for('admin_dashboard'))

    # Permission check
    is_admin_creator = (user_type == 'admin' and section_period.created_by_admin == user_id)
    is_assigned_teacher = (user_type == 'teacher' and str(section_period.assigned_teacher_id) == str(user_id))
    if not (is_admin_creator or is_assigned_teacher):
        flash('You do not have permission to add students to this period.', 'danger')
        return redirect(url_for('teacher_dashboard') if user_type == 'teacher' else url_for('admin_dashboard'))
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        student_id_number = request.form.get('student_id_number', '').strip()
        gender = request.form.get('gender')
        if not all([name, student_id_number, gender]):
            flash('Student name, ID number, and gender are all required.', 'error')
            return render_template('add_student_to_section_period.html', section_period=section_period)

        # --- Sync Logic: Always add to the master period ---
        master_period = db_session.query(SectionPeriod).filter(
            SectionPeriod.section_id == section_period.section_id,
            SectionPeriod.school_year == section_period.school_year
        ).order_by(SectionPeriod.period_name).first()
        target_period_id = master_period.id if master_period else section_period_id
        # --- End Sync Logic ---
        
        # Check if student ID already exists in the system
        existing_student = db_session.query(StudentInfo).filter_by(student_id_number=student_id_number).first()
        if existing_student:
            flash(f'A student with ID number {student_id_number} already exists in the system.', 'error')
            return render_template('add_student_to_section_period.html', section_period=section_period)

        try:
            new_student = StudentInfo(
                name=name,
                student_id_number=student_id_number,
                gender=gender,
                section_period_id=target_period_id  # Save to the master period
            )
            db_session.add(new_student)
            db_session.commit()
            
            # Log the action for teachers only
            if user_type == 'teacher':
                teacher_username = session.get('username', 'unknown')
                create_teacher_log(
                    db_session=db_session,
                    teacher_id=user_id,
                    teacher_username=teacher_username,
                    action_type='add_student',
                    target_type='student',
                    target_id=new_student.id,
                    target_name=name,
                    details=f"Added student {name} (ID: {student_id_number}) to section period",
                    section_period_id=target_period_id
                )
            
            flash('Student added successfully!', 'success')
            return redirect(url_for('section_period_details', section_period_id=section_period_id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error adding student: {e}")
            flash('An error occurred while adding the student. Please try again.', 'error')
            
    return render_template('add_student_to_section_period.html', section_period=section_period)
    
@app.route('/student/<uuid:student_id>/delete', methods=['POST'])
@login_required
@user_type_required('admin', 'teacher') # Allow teachers to delete students
def delete_student_admin(student_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    password = request.form.get('password')

    student_to_delete = db_session.query(StudentInfo).options(
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.strand) # Load strand via section
    ).filter_by(id=student_id).first()

    if not student_to_delete:
        return jsonify({'success': False, 'message': 'Student not found.'})

    if not password or not verify_current_user_password(user_id, password):
        return jsonify({'success': False, 'message': 'Incorrect password.'})

    # Permission check REMOVED

    redirect_url_after_delete = url_for('admin_dashboard') # Default fallback
    if student_to_delete.section_period:
        redirect_url_after_delete = url_for('section_period_details', section_period_id=student_to_delete.section_period.id)

    # Log the action for teachers only
    user_type = session.get('user_type')
    if user_type == 'teacher':
        teacher_username = session.get('username', 'unknown')
        create_teacher_log(
            db_session=db_session,
            teacher_id=user_id,
            teacher_username=teacher_username,
            action_type='delete_student',
            target_type='student',
            target_id=student_to_delete.id,
            target_name=student_to_delete.name,
            details=f"Deleted student {student_to_delete.name} (ID: {student_to_delete.student_id_number})",
            section_period_id=student_to_delete.section_period_id
        )

    try:
        db_session.delete(student_to_delete)
        db_session.commit()
        return jsonify({'success': True, 'message': f'Student "{student_to_delete.name}" and all their associated attendance and grades have been deleted.', 'redirect_url': redirect_url_after_delete})
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting student: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred while deleting the student.'})


@app.route('/edit_student/<uuid:student_id>', methods=['GET', 'POST'])
@login_required
@user_type_required('admin', 'teacher') # Allow teachers to edit students
def edit_student(student_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    user_type = session['user_type']
    
    student_to_edit = db_session.query(StudentInfo).options(
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.strand)
    ).filter_by(id=student_id).first()

    if not student_to_edit:
        flash('Student not found.', 'danger')
        return redirect(url_for('admin_dashboard')) 

    # Fetch all section periods manageable by this admin or teacher for the dropdown
    if user_type == 'admin':
        admin_id = uuid.UUID(session['user_id'])
        section_periods_for_dropdown = db_session.query(SectionPeriod).options(
            joinedload(SectionPeriod.section).joinedload(Section.grade_level),
            joinedload(SectionPeriod.section).joinedload(Section.strand)
        ).filter_by(created_by_admin=admin_id).order_by(
            SectionPeriod.school_year.desc(),
            SectionPeriod.period_name,
            Section.name.asc(),
            Strand.name.asc().nulls_first()
        ).join(Section).outerjoin(Strand).all()
    else:  # teacher
        section_periods_for_dropdown = db_session.query(SectionPeriod).options(
            joinedload(SectionPeriod.section).joinedload(Section.grade_level),
            joinedload(SectionPeriod.section).joinedload(Section.strand)
        ).filter_by(assigned_teacher_id=user_id).order_by(
            SectionPeriod.school_year.desc(),
            SectionPeriod.period_name,
            Section.name.asc(),
            Strand.name.asc().nulls_first()
        ).join(Section).outerjoin(Strand).all()

    current_period_manageable = any(str(s.id) == str(student_to_edit.section_period_id) for s in section_periods_for_dropdown)
    if not current_period_manageable:
         flash('You do not have permission to edit this student.', 'danger')
         if student_to_edit and student_to_edit.section_period_id:
             return redirect(url_for('section_period_details', section_period_id=student_to_edit.section_period.id))
         return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        student_name = request.form['name'].strip()
        student_id_number = request.form['student_id_number'].strip()
        gender = request.form.get('gender')
        new_section_period_id_str = request.form.get('section_period_id')
        password = request.form.get('password', '').strip()

        if not student_name or not student_id_number or not new_section_period_id_str or not gender:
            flash('All student fields are required.', 'error')
            return render_template('edit_student.html', student=student_to_edit, section_periods=section_periods_for_dropdown)
        
        new_section_period_id = uuid.UUID(new_section_period_id_str)

        try:
            if student_id_number != student_to_edit.student_id_number:
                existing_student_by_id = db_session.query(StudentInfo).filter(
                    StudentInfo.student_id_number == student_id_number,
                    StudentInfo.id != student_id
                ).first()
                if existing_student_by_id:
                    flash(f'Student ID Number "{student_id_number}" already exists for another student.', 'error')
                    return render_template('edit_student.html', student=student_to_edit, section_periods=section_periods_for_dropdown)
            
            new_section_period_obj_valid = any(str(s.id) == str(new_section_period_id) for s in section_periods_for_dropdown)
            if not new_section_period_obj_valid:
                flash('Selected new section/period is invalid or you do not have permission for it.', 'error')
                return render_template('edit_student.html', student=student_to_edit, section_periods=section_periods_for_dropdown)
            
            student_to_edit.name = student_name
            student_to_edit.student_id_number = student_id_number
            student_to_edit.section_period_id = new_section_period_id
            student_to_edit.gender = gender
            
            # Update password if provided (store raw password for admin visibility)
            if password and password.strip():
                student_to_edit.password_hash = password  # Store raw password for admin
                flash(f'Student "{student_name}" updated successfully with new password!', 'success')
            else:
                flash(f'Student "{student_name}" updated successfully! (Password unchanged)', 'success')

            db_session.commit()
            
            # Log the action for teachers only
            if user_type == 'teacher':
                teacher_username = session.get('username', 'unknown')
                create_teacher_log(
                    db_session=db_session,
                    teacher_id=user_id,
                    teacher_username=teacher_username,
                    action_type='edit_student',
                    target_type='student',
                    target_id=student_to_edit.id,
                    target_name=student_name,
                    details=f"Updated student {student_name} (ID: {student_id_number})",
                    section_period_id=new_section_period_id
                )
            
            return redirect(url_for('section_period_details', section_period_id=student_to_edit.section_period.id, edit_student_id=student_to_edit.id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error editing student: {e}")
            flash('An error occurred while updating the student. Please try again.', 'error')

    return render_template('edit_student.html', student=student_to_edit, section_periods=section_periods_for_dropdown)



# --- Teacher Dashboard Routes ---
@app.route('/teacher_dashboard')
@login_required
@user_type_required('teacher')
def teacher_dashboard():
    db_session = g.session
    teacher_id = uuid.UUID(session['user_id'])

    sections = db_session.query(Section).options(
        joinedload(Section.grade_level),
        joinedload(Section.strand)
    ).outerjoin(Section.section_periods).filter(
        or_(
            Section.assigned_user_id == teacher_id,
            SectionPeriod.assigned_teacher_id == teacher_id
        )
    ).distinct().order_by(Section.name).limit(20).all()  # Paginate if needed

    return render_template('teacher_dashboard.html', sections=sections, uuid=uuid)


@app.route('/teacher/section_period/<uuid:section_period_id>')
@login_required
@user_type_required('teacher', 'admin')
def teacher_section_period_view(section_period_id):
    # This route is now a simple redirect to the main, corrected details view.
    # This ensures that both admins and teachers use the exact same logic.
    return redirect(url_for('section_period_details', section_period_id=section_period_id))

@app.route('/teacher/section_period/<uuid:section_period_id>/add_subject', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher', 'admin')
def add_subject_to_section_period(section_period_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    user_type = session['user_type']

    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section)
    ).filter_by(id=section_period_id).one_or_none()

    if not section_period:
        flash('Period not found.', 'danger')
        return redirect(url_for('teacher_dashboard') if user_type == 'teacher' else url_for('admin_dashboard'))
    
    # Permission check
    is_admin_creator = (user_type == 'admin' and section_period.created_by_admin == user_id)
    is_assigned_teacher = (user_type == 'teacher' and str(section_period.assigned_teacher_id) == str(user_id))
    if not (is_admin_creator or is_assigned_teacher):
         flash('You do not have permission to add subjects to this period.', 'danger')
         return redirect(url_for('teacher_dashboard') if user_type == 'teacher' else url_for('admin_dashboard'))

    if request.method == 'POST':
        subject_name = request.form.get('subject_name', '').strip()
        assigned_teacher_name = request.form.get('assigned_teacher_name', '').strip()
        subject_password = request.form.get('subject_password')

        if not all([subject_name, assigned_teacher_name]):
            flash('Subject name and assigned teacher name are required.', 'error')
            return render_template('add_section_subject.html', section_period=section_period)
        
        # --- Enhanced Sync Logic ---
        if section_period.period_type == 'Quarter':
            # JHS: Sync to master period only (existing logic)
            target_period_id = section_period_id
            master_period = db_session.query(SectionPeriod).filter(
                SectionPeriod.section_id == section_period.section_id,
                SectionPeriod.school_year == section_period.school_year
            ).order_by(SectionPeriod.period_name).first()
            if master_period:
                target_period_id = master_period.id
            # Check for existing subject in the target period
            existing_subject = db_session.query(SectionSubject).filter_by(
                section_period_id=target_period_id,
                subject_name=subject_name
            ).first()
            if existing_subject:
                flash(f'Subject "{subject_name}" already exists for this period.', 'error')
                return render_template('add_section_subject.html', section_period=section_period)
            try:
                new_subject = SectionSubject(
                    section_period_id=target_period_id, # Add to correct period (master for JHS)
                    subject_name=subject_name,
                    created_by_teacher_id=user_id, 
                    assigned_teacher_name=assigned_teacher_name,
                    subject_password=generate_password_hash(subject_password) if subject_password else None
                )
                db_session.add(new_subject)
                db_session.commit()
                flash(f'Subject "{subject_name}" added successfully!', 'success')
                return redirect(url_for('section_period_details', section_period_id=section_period_id))
            except Exception as e:
                db_session.rollback()
                app.logger.error(f"Error adding subject: {e}")
                flash('An error occurred while adding the subject. Please try again.', 'error')
        elif section_period.period_type == 'Semester':
            # SHS: Sync to all section periods in the same grade, strand, period, and school year
            # Get the current section's grade_level_id and strand_id
            section = db_session.query(Section).filter_by(id=section_period.section_id).first()
            if not section:
                flash('Section not found.', 'error')
                return render_template('add_section_subject.html', section_period=section_period)
            matching_section_periods = db_session.query(SectionPeriod).join(Section).filter(
                Section.grade_level_id == section.grade_level_id,
                Section.strand_id == section.strand_id,
                SectionPeriod.period_name == section_period.period_name,
                SectionPeriod.school_year == section_period.school_year
            ).all()
            added_count = 0
            for sp in matching_section_periods:
                # Check if subject already exists for this period
                existing_subject = db_session.query(SectionSubject).filter_by(
                    section_period_id=sp.id,
                    subject_name=subject_name
                ).first()
                if not existing_subject:
                    if sp.id == section_period.id:
                        # For the original section_period, use the provided teacher and password
                        new_subject = SectionSubject(
                            section_period_id=sp.id,
                            subject_name=subject_name,
                            created_by_teacher_id=user_id,
                            assigned_teacher_name=assigned_teacher_name,
                            subject_password=generate_password_hash(subject_password) if subject_password else None
                        )
                    else:
                        # For other section_periods, only copy the subject name, leave teacher and password blank
                        new_subject = SectionSubject(
                            section_period_id=sp.id,
                            subject_name=subject_name,
                            created_by_teacher_id=user_id,
                            assigned_teacher_name='',
                            subject_password=None
                        )
                    db_session.add(new_subject)
                    added_count += 1
            try:
                db_session.commit()
                if added_count > 0:
                    flash(f'Subject "{subject_name}" added to all {section.strand.name if section.strand else ""} sections for {section_period.period_name} {section_period.school_year}!', 'success')
                else:
                    flash(f'Subject "{subject_name}" already exists in all matching sections.', 'info')
                return redirect(url_for('section_period_details', section_period_id=section_period_id))
            except Exception as e:
                db_session.rollback()
                app.logger.error(f"Error adding subject: {e}")
                flash('An error occurred while adding the subject. Please try again.', 'error')
        else:
            flash('Unknown period type. Cannot sync subject.', 'error')
            return render_template('add_section_subject.html', section_period=section_period)

    return render_template('add_section_subject.html', section_period=section_period)

@app.route('/teacher/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/edit', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher', 'admin')
def edit_section_subject(section_period_id, subject_id):
    try:
        subject = g.session.query(SectionSubject).filter_by(id=subject_id, section_period_id=section_period_id).one()
        user_id = uuid.UUID(session['user_id'])
        user_type = session.get('user_type')
        if request.method == 'POST':
            new_subject_name = request.form.get('subject_name')
            new_teacher_name = request.form.get('assigned_teacher_name')
            password = request.form.get('password')
            subject_password = request.form.get('subject_password')
            # Only require password for teachers
            if user_type == 'teacher':
                if not password or not verify_current_user_password(user_id, password):
                    flash('Incorrect password. Subject was not updated.', 'error')
                    redirect_url = url_for('section_period_details', section_period_id=section_period_id) if user_type == 'admin' else url_for('teacher_section_period_view', section_period_id=section_period_id)
                    return redirect(redirect_url)
            if not new_subject_name or not new_teacher_name:
                flash('Subject Name and Assigned Teacher Name cannot be empty.', 'error')
            else:
                subject.subject_name = new_subject_name
                subject.assigned_teacher_name = new_teacher_name
                # Only admin can update subject password
                if user_type == 'admin' and subject_password:
                    subject.subject_password = subject_password
                g.session.commit()
                flash('Subject updated successfully!', 'success')
            # Correct redirect logic
            redirect_url = url_for('section_period_details', section_period_id=section_period_id) if session['user_type'] == 'admin' else url_for('teacher_section_period_view', section_period_id=section_period_id)
            return redirect(redirect_url)
        # GET request: render the edit form
        return render_template('edit_section_subject.html', subject=subject, section_period_id=section_period_id)
    except NoResultFound:
        flash('Subject not found.', 'error')
    except Exception as e:
        g.session.rollback()
        flash(f'An error occurred: {e}', 'error')
    redirect_url = url_for('section_period_details', section_period_id=section_period_id) if session['user_type'] == 'admin' else url_for('teacher_section_period_view', section_period_id=section_period_id)
    return redirect(redirect_url)

@app.route('/teacher/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/delete', methods=['POST'])
@login_required
@user_type_required('teacher', 'admin')
def delete_section_subject(section_period_id, subject_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    user_type = session['user_type']
    password = request.form.get('password')

    # Fetch the subject and its section period
    subject_to_delete = db_session.query(SectionSubject).options(
        joinedload(SectionSubject.section_period).joinedload(SectionPeriod.section)
    ).filter(
        SectionSubject.id == subject_id,
        SectionSubject.section_period_id == section_period_id
    ).first()

    if not subject_to_delete:
        return jsonify({'success': False, 'message': 'Subject not found.'})

    # Permission checks based on user type
    if user_type == 'teacher':
        # For teachers: check if they are the assigned teacher for this period
        if str(subject_to_delete.section_period.assigned_teacher_id) != str(user_id):
            return jsonify({'success': False, 'message': 'You do not have permission to delete subjects from this period.'})
        # Adviser password check
        section = subject_to_delete.section_period.section
        if not password or password != (section.adviser_password or ''):
            return jsonify({'success': False, 'message': 'Incorrect adviser password.'})
    else:  # admin
        if not password or not verify_current_user_password(user_id, password):
            return jsonify({'success': False, 'message': 'Incorrect password.'})

    try:
        # Delete associated records first
        app.logger.info(f"Attempting to delete subject {subject_id} and its associated records...")
        
        # Delete grades
        grades = db_session.query(Grade).filter_by(section_subject_id=subject_id).all()
        for grade in grades:
            db_session.delete(grade)
        
        # Delete attendance records
        attendance_records = db_session.query(Attendance).filter_by(section_subject_id=subject_id).all()
        for record in attendance_records:
            db_session.delete(record)
        
        # Delete grading system and its components
        grading_system = db_session.query(GradingSystem).filter_by(section_subject_id=subject_id).first()
        if grading_system:
            components = db_session.query(GradingComponent).filter_by(system_id=grading_system.id).all()
            for component in components:
                # Delete gradable items and scores
                items = db_session.query(GradableItem).filter_by(component_id=component.id).all()
                for item in items:
                    scores = db_session.query(StudentScore).filter_by(item_id=item.id).all()
                    for score in scores:
                        db_session.delete(score)
                    db_session.delete(item)
                db_session.delete(component)
            db_session.delete(grading_system)

        # Finally delete the subject
        db_session.delete(subject_to_delete)
        db_session.commit()
        app.logger.info(f"Successfully deleted subject {subject_id} and all associated records")
        
        # Return appropriate redirect URL based on user type
        if user_type == 'admin':
            redirect_url = url_for('section_period_details', section_period_id=section_period_id)
        else:
            redirect_url = url_for('teacher_section_period_view', section_period_id=section_period_id)
            
        return jsonify({
            'success': True, 
            'message': f'Subject "{subject_to_delete.subject_name}" has been deleted.',
            'redirect_url': redirect_url
        })
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting subject: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': f'An error occurred while deleting the subject: {str(e)}'})


@app.route('/teacher/section/<uuid:section_id>/delete', methods=['POST'])
@login_required
@user_type_required('teacher')
def delete_teacher_section(section_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    password = request.form.get('password')
    
    section_to_delete = db_session.query(Section).options(joinedload(Section.grade_level), joinedload(Section.strand)).filter_by(id=section_id).first()
    if not section_to_delete:
        return jsonify({'success': False, 'message': 'Section not found.'})
    
    # Check adviser password instead of account password
    if not password or password != (section_to_delete.adviser_password or ''):
        return jsonify({'success': False, 'message': 'Incorrect adviser password.'})

    teacher_specialization = session.get('specialization')
    teacher_grade_level = session.get('grade_level_assigned')

    all_periods_in_section = db_session.query(SectionPeriod).filter_by(section_id=section_id).all() # No need to load strand here, it's on the section
    
    # 2, 3 & 4. Check assignment for all periods and strand match for SHS / NULL strand for JHS
    if all_periods_in_section:
        for period in all_periods_in_section:
            if str(period.assigned_teacher_id) != str(user_id):
                return jsonify({'success': False, 'message': 'You can only delete sections where you are assigned to all its periods. Otherwise, only the student admin can delete it.'})
            
            # Additional check based on section's strand, not period's strand (since period no longer has one)
            if section_to_delete.grade_level.level_type == 'SHS':
                if not section_to_delete.strand or section_to_delete.strand.name != teacher_specialization:
                    return jsonify({'success': False, 'message': 'You can only delete sections where the section\'s strand matches your specialization.'})
            elif section_to_delete.grade_level.level_type == 'JHS':
                if section_to_delete.strand_id is not None:
                    return jsonify({'success': False, 'message': 'You can only delete JHS sections where the section has no assigned strand.'})

    try:
        db_session.delete(section_to_delete)
        db_session.commit()
        return jsonify({'success': True, 'message': f'Section "{section_to_delete.name}" has been deleted (all associated periods, students, subjects, attendance, and grades also deleted).'})
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting section: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred while deleting the section.'})


@app.route('/teacher/student/<uuid:student_id>/delete', methods=['POST'])
@login_required
@user_type_required('teacher')
def delete_student_from_section(student_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])

    student_to_delete = db_session.query(StudentInfo).options(
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.strand) # Load strand via section
    ).filter_by(id=student_id).first()

    if not student_to_delete:
        return jsonify({'success': False, 'message': 'Student not found.'})

    # No adviser password check for teachers
    try:
        # Log the action before deleting
        teacher_username = session.get('username', 'unknown')
        create_teacher_log(
            db_session=db_session,
            teacher_id=user_id,
            teacher_username=teacher_username,
            action_type='delete_student',
            target_type='student',
            target_id=student_to_delete.id,
            target_name=student_to_delete.name,
            details=f"Deleted student {student_to_delete.name} (ID: {student_to_delete.student_id_number}) from section {student_to_delete.section_period.section.name}",
            section_period_id=student_to_delete.section_period_id
        )
        
        db_session.delete(student_to_delete)
        db_session.commit()
        return jsonify({'success': True, 'message': f'Student "{student_to_delete.name}" has been deleted from section "{student_to_delete.section_period.section.name}".'})
    except Exception as e:
        db_session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred while deleting the student.'})


@app.route('/teacher/section_period/<uuid:section_period_id>/add_grades/<uuid:student_id>', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher', 'admin')
def add_grades_for_student(section_period_id, student_id):
    db_session = g.session
    teacher_id = uuid.UUID(session['user_id'])
    teacher_specialization = session.get('specialization')
    teacher_grade_level = session.get('grade_level_assigned')

    student = db_session.query(StudentInfo).options(
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.strand)
    ).filter_by(id=student_id).first()

    if not student or str(student.section_period.id) != str(section_period_id):
        flash('Student not found in this period.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    # Permission check (same as teacher_section_period_view)
    if student.section_period.section.grade_level.name != teacher_grade_level or \
       (student.section_period.assigned_teacher_id and str(student.section_period.assigned_teacher_id) != str(teacher_id)) :
        flash('You do not have permission to grade this student.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    if student.section_period.section.grade_level.level_type == 'SHS':
        if not student.section_period.section.strand or student.section_period.section.strand.name != teacher_specialization:
            flash('You do not have permission to grade this student (incorrect strand).', 'danger')
            return redirect(url_for('teacher_dashboard'))
    elif student.section_period.section.grade_level.level_type == 'JHS':
        if student.section_period.section.strand_id is not None:
             flash('You do not have permission to grade this student (JHS student incorrectly assigned to a strand).', 'danger')
             return redirect(url_for('teacher_dashboard'))


    # Fetch all subjects within this period
    # No longer filtering by SectionSubject.assigned_teacher_for_subject_id here
    section_subjects = db_session.query(SectionSubject).filter(
        SectionSubject.section_period_id == student.section_period.id
    ).order_by(SectionSubject.subject_name).all()
    
    section_subjects_data = [{
        'id': str(s.id),
        'subject_name': s.subject_name,
        'assigned_teacher_name': s.assigned_teacher_name # Include the assigned teacher name
    } for s in section_subjects]

    existing_grades_data = db_session.query(Grade, SectionSubject).join(SectionSubject).filter(
        Grade.student_info_id == student_id,
        SectionSubject.section_period_id == student.section_period.id,
        Grade.teacher_id == teacher_id # Only load grades entered by this teacher account
    ).all()

    grades_dict = {}
    for grade_obj, section_subject_obj in existing_grades_data:
        key = f"{section_subject_obj.subject_name}|{grade_obj.semester}|{grade_obj.school_year}" # Using legacy semester/year from Grade for dict key
        grades_dict[key] = {
            'grade_value': float(grade_obj.grade_value),
            'id': str(grade_obj.id),
            'section_subject_id': str(section_subject_obj.id)
        }

    school_years_options = get_school_year_options()
    period_names_options = PERIOD_TYPES[student.section_period.section.grade_level.level_type]

    default_period_name = student.section_period.period_name
    default_school_year = student.section_period.school_year

    initial_average_grade = None
    grades_for_default_period = []
    if default_period_name and default_school_year:
        for ss in section_subjects_data:
            key = f"{ss['subject_name']}|{default_period_name}|{default_school_year}"
            if key in grades_dict:
                grades_for_default_period.append(grades_dict[key]['grade_value'])
        
        if grades_for_default_period:
            initial_average_grade = round(sum(grades_for_default_period) / len(grades_for_default_period), 2)


    if request.method == 'POST':
        period_name = request.form['period_name'] # Get from form
        school_year = request.form['school_year']

        if not period_name or not school_year:
            flash(f'{student.section_period.period_type} and School Year are required.', 'error')
            return render_template('add_grades_for_student.html', 
                                   student=student, 
                                   section_subjects=section_subjects_data, 
                                   grades_dict=grades_dict, 
                                   period_names=period_names_options, 
                                   school_years=school_years_options, 
                                   initial_average_grade=initial_average_grade)

        if not re.fullmatch(r'\d{4}-\d{4}', school_year):
            flash('Invalid School Year format. Please use XXXX-YYYY (e.g., 2025-2026).', 'error')
            return render_template('add_grades_for_student.html', 
                                   student=student, 
                                   section_subjects=section_subjects_data, 
                                   grades_dict=grades_dict, 
                                   period_names=period_names_options, 
                                   school_years=school_years_options, 
                                   initial_average_grade=initial_average_grade)


        grades_to_process = []
        for section_subject in section_subjects: # Iterate over ALL subjects in this period
            grade_input_name = f"grade__{section_subject.id}"
            grade_value_str = request.form.get(grade_input_name)

            if grade_value_str:
                try:
                    grade_value = float(grade_value_str)
                    if not (0 <= grade_value <= 100):
                        flash(f'Grade for {section_subject.subject_name} must be between 0 and 100.', 'error')
                        return render_template('add_grades_for_student.html', 
                                               student=student, 
                                               section_subjects=section_subjects_data, 
                                               grades_dict=grades_dict, 
                                               period_names=period_names_options, 
                                               school_years=school_years_options, 
                                               initial_average_grade=initial_average_grade)
                    grades_to_process.append({
                        'section_subject_id': section_subject.id,
                        'grade_value': grade_value
                    })
                except ValueError:
                    flash(f'Invalid grade for {section_subject.subject_name}. Please enter a number.', 'error')
                    return render_template('add_grades_for_student.html', 
                                           student=student, 
                                           section_subjects=section_subjects_data, 
                                           grades_dict=grades_dict, 
                                           period_names=period_names_options, 
                                           school_years=school_years_options, 
                                           initial_average_grade=initial_average_grade)
        
        if not grades_to_process:
            flash('No grades provided to save.', 'warning')
            return render_template('add_grades_for_student.html', 
                                   student=student, 
                                   section_subjects=section_subjects_data, 
                                   grades_dict=grades_dict, 
                                   period_names=period_names_options, 
                                   school_years=school_years_options, 
                                   initial_average_grade=initial_average_grade)

        try:
            for grade_data in grades_to_process:
                # Use period_name and school_year from the form, which map to the current SectionPeriod
                existing_grade_record = db_session.query(Grade).filter(
                    Grade.student_info_id == student_id,
                    Grade.section_subject_id == grade_data['section_subject_id'],
                    Grade.semester == period_name, # Map period_name to 'semester' field in Grade table
                    Grade.school_year == school_year
                ).first()

                if existing_grade_record:
                    existing_grade_record.grade_value = grade_data['grade_value']
                    existing_grade_record.teacher_id = teacher_id
                    # Log grade update for teachers only
                    if session.get('user_type') == 'teacher':
                        teacher_username = session.get('username', 'unknown')
                        subject_name = db_session.query(SectionSubject).filter_by(id=grade_data['section_subject_id']).first().subject_name
                        create_teacher_log(
                            db_session=db_session,
                            teacher_id=teacher_id,
                            teacher_username=teacher_username,
                            action_type='edit_grade',
                            target_type='grade',
                            target_id=existing_grade_record.id,
                            target_name=f"{student.name} - {subject_name}",
                            details=f"Updated grade for {student.name} in {subject_name}: {grade_data['grade_value']} ({period_name} {school_year})",
                            section_period_id=section_period_id,
                            subject_id=grade_data['section_subject_id']
                        )
                else:
                    new_grade = Grade(
                        student_info_id=student_id,
                        section_subject_id=grade_data['section_subject_id'],
                        teacher_id=teacher_id,
                        grade_value=grade_data['grade_value'],
                        semester=period_name, # Map period_name to 'semester' field in Grade table
                        school_year=school_year
                    )
                    db_session.add(new_grade)
                    # Log grade addition for teachers only
                    if session.get('user_type') == 'teacher':
                        teacher_username = session.get('username', 'unknown')
                        subject_name = db_session.query(SectionSubject).filter_by(id=grade_data['section_subject_id']).first().subject_name
                        create_teacher_log(
                            db_session=db_session,
                            teacher_id=teacher_id,
                            teacher_username=teacher_username,
                            action_type='add_grade',
                            target_type='grade',
                            target_id=new_grade.id,
                            target_name=f"{student.name} - {subject_name}",
                            details=f"Added grade for {student.name} in {subject_name}: {grade_data['grade_value']} ({period_name} {school_year})",
                            section_period_id=section_period_id,
                            subject_id=grade_data['section_subject_id']
                        )
            db_session.commit()
            flash(f'Grades for {student.name} ({period_name} {school_year}) saved successfully!', 'success')
            return redirect(url_for('teacher_section_period_view', section_period_id=section_period_id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error saving grades: {e}")
            flash('An error occurred while saving grades. Please try again.', 'error')
    
    return render_template('add_grades_for_student.html', 
                           student=student, 
                           section_subjects=section_subjects_data, 
                           grades_dict=grades_dict, 
                           period_names=period_names_options, 
                           school_years=school_years_options, 
                           initial_average_grade=initial_average_grade)


@app.route('/section/<uuid:section_id>/edit_admin', methods=['GET', 'POST'])
@login_required
@user_type_required('admin', 'teacher')
def edit_section_admin(section_id):
    try:
        section = g.session.query(Section).filter(Section.id == section_id).one()
        user_type = session.get('user_type')
        user_id = session.get('user_id')
        # Adviser password check for teachers
        if user_type == 'teacher':
            flag = f'adviser_password_verified_{section_id}'
            if not session.get(flag):
                flash('You do not have permission to access this page. Adviser password required.', 'error')
                return redirect(url_for('teacher_dashboard'))
        if request.method == 'POST':
            new_name = request.form.get('section_name')
            new_adviser = request.form.get('adviser_name')
            new_password = request.form.get('section_password')
            new_assigned_user_id = request.form.get('assigned_user_id')
            new_adviser_password = request.form.get('adviser_password')  # NEW

            if not new_name:
                flash('Section name cannot be empty.', 'error')
                return redirect(request.referrer or url_for('admin_dashboard'))

            section.name = new_name
            section.adviser_name = new_adviser
            section.section_password = new_password
            section.assigned_user_id = new_assigned_user_id if new_assigned_user_id else None
            if new_adviser_password:
                section.adviser_password = new_adviser_password
            g.session.commit()
            flash('Section updated successfully!', 'success')
            # Reset adviser password flag for this section after edit
            if user_type == 'teacher':
                session.pop(flag, None)
            return redirect(request.referrer or url_for('admin_dashboard'))
        else:
            return render_template('edit_section.html', section=section)
    except NoResultFound:
        flash('Section not found.', 'error')
        return redirect(request.referrer or url_for('admin_dashboard'))
    except Exception as e:
        g.session.rollback()
        flash(f'An error occurred: {e}', 'error')
        return redirect(request.referrer or url_for('admin_dashboard'))


@app.route('/section_period/<uuid:section_period_id>/edit', methods=['POST'])
@login_required
@user_type_required('admin')
def edit_section_period(section_period_id):
    try:
        section_period = g.session.query(SectionPeriod).filter(SectionPeriod.id == section_period_id).one()

        # Fetch form data
        new_period_name = request.form.get('period_name')
        new_school_year = request.form.get('school_year')
        new_teacher_id_str = request.form.get('assigned_teacher_id')

        # Convert teacher ID to UUID if provided
        new_teacher_id = uuid.UUID(new_teacher_id_str) if new_teacher_id_str else None

        # Basic validation
        if not all([new_period_name, new_school_year]):
            flash('Period name and school year are required.', 'error')
            return redirect(request.referrer)

        # Update fields
        section_period.period_name = new_period_name
        section_period.school_year = new_school_year
        section_period.assigned_teacher_id = new_teacher_id
        
        g.session.commit()
        flash('Section period updated successfully!', 'success')

    except NoResultFound:
        flash('Section period not found.', 'error')
    except Exception as e:
        g.session.rollback()
        flash(f'An error occurred: {e}', 'error')
        
    return redirect(request.referrer or url_for('admin_dashboard'))


@app.route('/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/gradebook', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher')
def manage_subject_grades(section_period_id, subject_id):
    subject = g.session.query(SectionSubject).options(
        joinedload(SectionSubject.section_period).joinedload(SectionPeriod.section),
        joinedload(SectionSubject.grading_system).joinedload(GradingSystem.components).joinedload(GradingComponent.items)
    ).get(subject_id)
    
    if not subject:
        flash('Subject not found.', 'error')
        return redirect(request.referrer or url_for('teacher_dashboard'))

    # Allow any teacher assigned to the section period to view/manage the gradebook
    section_period = subject.section_period
    teacher_id = uuid.UUID(session['user_id'])
    if str(section_period.assigned_teacher_id) != str(teacher_id):
        flash('You do not have permission to view this subject.', 'error')
        return redirect(request.referrer or url_for('teacher_dashboard'))

    # Check if the subject password has been verified
    if request.method == 'POST':
        password = request.form.get('subject_password')
        if not password or password != subject.subject_password:
            flash('Incorrect subject password.', 'error')
            return redirect(url_for('teacher_section_period_view', section_period_id=section_period_id))
        else:
            session['subject_password_verified'] = str(subject_id)
    elif 'subject_password_verified' not in session or session['subject_password_verified'] != str(subject_id):
        flash('Please enter the subject password to access the gradebook.', 'info')
        return redirect(url_for('teacher_section_period_view', section_period_id=section_period_id))

    # Check if the subject password has been verified
    if request.method == 'POST':
        password = request.form.get('subject_password')
    if 'subject_password_verified' not in session or session['subject_password_verified'] != str(subject_id):
        if request.method == 'POST':
            password = request.form.get('subject_password')
            if not password or password != subject.subject_password:
                flash('Incorrect subject password.', 'error')
                return render_template('confirm_password.html', 
                                    subject=subject,
                                    form_action=url_for('manage_subject_grades', section_period_id=section_period_id, subject_id=subject_id))
            else:
                session['subject_password_verified'] = str(subject_id)
        else:
            return render_template('confirm_password.html', 
                                subject=subject,
                                form_action=url_for('manage_subject_grades', section_period_id=section_period_id, subject_id=subject_id))

    students = g.session.query(StudentInfo).filter(
        StudentInfo.section_period_id == section_period_id
    ).order_by(StudentInfo.name).all()

    # Default values for when no grading system is set up
    components = []
    total_weight = 0
    scores_map = {}
    component_averages = {}
    total_grades = {}

    if subject.grading_system:
        components = sorted(subject.grading_system.components, key=lambda c: c.name)
        total_weight = sum(c.weight for c in components)

        # Pre-fetch all scores for all students for this subject to be efficient
        scores_query = g.session.query(StudentScore).join(GradableItem).join(GradingComponent).filter(
            GradingComponent.system_id == subject.grading_system.id
        ).all()
        
        # Create a nested dictionary for easy lookup: scores_map[student_id][item_id]
        for score in scores_query:
            scores_map.setdefault(score.student_info_id, {})[score.item_id] = score.score

        # Calculate averages and totals for each student
        for student in students:
            student_total_grade = decimal.Decimal('0.0')
            component_averages[student.id] = {}
            
            for component in components:
                component_items = component.items
                if not component_items:
                    continue

                student_scores_sum = decimal.Decimal('0.0')
                max_scores_sum = decimal.Decimal('0.0')

                for item in component_items:
                    score = scores_map.get(student.id, {}).get(item.id)
                    if score is not None:
                        student_scores_sum += decimal.Decimal(score)
                        max_scores_sum += decimal.Decimal(item.max_score)

                if max_scores_sum > 0:
                    # Calculate the average for this component (e.g., 85/100 = 0.85)
                    average = student_scores_sum / max_scores_sum
                    component_averages[student.id][component.id] = f"{average * 100:.2f}%"
                    
                    # Add the weighted average to the student's total grade
                    component_weight = decimal.Decimal(component.weight) / decimal.Decimal('100.0')
                    student_total_grade += average * component_weight
                else:
                    component_averages[student.id][component.id] = "N/A"

            # Format the final grade as a percentage
            total_grades[student.id] = f"{student_total_grade * 100:.2f}"

    return render_template('gradebook.html', 
                           subject=subject,
                           students=students,
                           scores=scores_map, # Renamed for clarity in template
                           components=components,
                           total_weight=total_weight,
                           component_averages=component_averages,
                           total_grades=total_grades)


@app.route('/subject/<uuid:subject_id>/grading-system/setup', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher')
def setup_grading_system(subject_id):
    subject = g.session.query(SectionSubject).get(subject_id)
    if not subject:
        flash('Subject not found.', 'error')
        return redirect(url_for('admin_dashboard'))

    grading_system = g.session.query(GradingSystem).filter_by(section_subject_id=subject_id).first()

    if request.method == 'POST':
        if not grading_system:
            grading_system = GradingSystem(
                section_subject_id=subject_id,
                teacher_id=session['user_id']
            )
            g.session.add(grading_system)
        
        # Clear old components
        for component in grading_system.components:
            g.session.delete(component)
        g.session.flush() # Process deletes before adding new ones

        total_weight = 0
        component_names = request.form.getlist('component_name')
        component_weights = request.form.getlist('component_weight')

        for name, weight_str in zip(component_names, component_weights):
            if name and weight_str:
                try:
                    weight = int(weight_str)
                    if weight > 0:
                        total_weight += weight
                        new_component = GradingComponent(
                            system=grading_system,
                            name=name.strip(),
                            weight=weight
                        )
                        g.session.add(new_component)
                except ValueError:
                    flash(f'Invalid weight for {name}. Please use whole numbers.', 'error')
                    return redirect(url_for('setup_grading_system', subject_id=subject_id))

        if total_weight != 100:
            flash(f'The total weight of all components must be exactly 100%, but it is currently {total_weight}%.', 'error')
            g.session.rollback() # Undo the changes
        else:
            g.session.commit()
            
            # Sync all existing total grades for this subject to the grades table
            students = g.session.query(StudentInfo).join(SectionPeriod).filter(
                SectionPeriod.id == subject.section_period_id
            ).all()
            
            for student in students:
                sync_total_grade_to_database(g.session, student.id, subject.id, uuid.UUID(session['user_id']), subject.section_period)
            
            flash('Grading system updated successfully!', 'success')
        
        return redirect(url_for('manage_subject_grades', section_period_id=subject.section_period_id, subject_id=subject.id))

    return render_template('grading_system_setup.html', subject=subject, grading_system=grading_system)

@app.route('/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/verify-gradebook-password', methods=['POST'])
@login_required
@user_type_required('teacher')
def verify_gradebook_password(section_period_id, subject_id):
    subject = g.session.query(SectionSubject).options(
        joinedload(SectionSubject.section_period)
    ).get(subject_id)
    
    if not subject:
        flash('Subject not found.', 'error')
        return redirect(request.referrer or url_for('teacher_dashboard'))

    section_period = subject.section_period
    teacher_id = uuid.UUID(session['user_id'])
    if str(section_period.assigned_teacher_id) != str(teacher_id):
        flash('You do not have permission to view this subject.', 'error')
        return redirect(request.referrer or url_for('teacher_dashboard'))

    password = request.form.get('subject_password')
    if not password or password != subject.subject_password:
        flash('Incorrect subject password.', 'error')
        return redirect(url_for('teacher_section_period_view', section_period_id=section_period_id))
    else:
        session['subject_password_verified'] = str(subject_id)
        return redirect(url_for('manage_subject_grades', section_period_id=section_period_id, subject_id=subject_id))

@app.route('/subject/<uuid:subject_id>/student/<uuid:student_id>/grade', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher')
def grade_student_for_subject(subject_id, student_id):
    subject = g.session.query(SectionSubject).options(
        joinedload(SectionSubject.grading_system).joinedload(GradingSystem.components).joinedload(GradingComponent.items),
        joinedload(SectionSubject.section_period) # Eager load for breadcrumbs
    ).get(subject_id)
    
    student = g.session.query(StudentInfo).get(student_id)

    if not subject or not student:
        flash('Subject or student not found.', 'error')
        return redirect(url_for('teacher_dashboard'))

    # Sort components for consistent order
    components = []
    if subject.grading_system:
        components = sorted(subject.grading_system.components, key=lambda c: c.name)

    if request.method == 'POST':
        teacher_username = session.get('username', 'unknown')
        teacher_id = uuid.UUID(session['user_id'])
        updated_scores = []
        deleted_scores = []
        
        # Use the sorted components list to ensure we process in a predictable order
        for component in components:
            for item in component.items:
                score_value_str = request.form.get(f'score-{item.id}')
                if score_value_str is not None and score_value_str.strip() != '':
                    try:
                        score_value = decimal.Decimal(score_value_str)
                        # Check if score already exists
                        score = g.session.query(StudentScore).filter_by(item_id=item.id, student_info_id=student.id).first()
                        if score:
                            score.score = score_value
                            updated_scores.append((item.title, score_value))
                        else:
                            # Create new score if it doesn't exist
                            score = StudentScore(item_id=item.id, student_info_id=student.id, score=score_value)
                            g.session.add(score)
                            updated_scores.append((item.title, score_value))
                    except (decimal.InvalidOperation, ValueError):
                        flash(f'Invalid score format for {item.title}. Please use numbers only.', 'error')
                        # We continue here to not block other valid scores from being saved
                        continue 
                else:
                    # If score input is empty, delete the existing score from the DB
                    score = g.session.query(StudentScore).filter_by(item_id=item.id, student_info_id=student.id).first()
                    if score:
                        deleted_scores.append(item.title)
                        g.session.delete(score)

        g.session.commit()
        
        # Log the bulk grade updates
        if updated_scores or deleted_scores:
            details_parts = []
            if updated_scores:
                details_parts.append(f"Updated scores: {', '.join([f'{title} ({score})' for title, score in updated_scores])}")
            if deleted_scores:
                details_parts.append(f"Deleted scores: {', '.join(deleted_scores)}")
            
            create_teacher_log(
                db_session=g.session,
                teacher_id=teacher_id,
                teacher_username=teacher_username,
                action_type='edit_grade',
                target_type='grade',
                target_id=student.id,
                target_name=f"{student.name} - {subject.subject_name}",
                details=f"Bulk grade update for {student.name} in {subject.subject_name}: {'; '.join(details_parts)}",
                section_period_id=subject.section_period_id,
                subject_id=subject.id
            )
        
        flash(f'Grades for {student.name} updated successfully!', 'success')
        
        # Sync the calculated total grade to the grades table
        sync_total_grade_to_database(g.session, student.id, subject.id, uuid.UUID(session['user_id']), subject.section_period)
        
        # Redirect back to the main gradebook to see the updated overview
        return redirect(url_for('manage_subject_grades', section_period_id=subject.section_period_id, subject_id=subject.id))

    # For GET request, load the scores for the form
    scores_query = g.session.query(StudentScore).filter(StudentScore.student_info_id == student_id).all()
    scores_map = {score.item_id: score.score for score in scores_query}
    
    # Pass the sorted components to the template
    return render_template('grade_student.html', subject=subject, student=student, scores_map=scores_map, components=components)


# --- API Endpoints for the Gradebook ---

@app.route('/api/gradable-item/add', methods=['POST'])
@login_required
@user_type_required('teacher')
def add_gradable_item():
    try:
        data = request.get_json()
        component_id = data.get('component_id')
        title = data.get('title')
        max_score = data.get('max_score')

        if not all([component_id, title, max_score]):
            return jsonify({'success': False, 'message': 'Missing required data.'}), 400

        # Check if component exists and belongs to the logged-in teacher to be safe
        component = g.session.query(GradingComponent).join(GradingSystem).filter(
            GradingComponent.id == component_id,
            GradingSystem.teacher_id == session['user_id']
        ).first()

        if not component:
            return jsonify({'success': False, 'message': 'Component not found or you do not have permission.'}), 404

        new_item = GradableItem(
            component_id=component_id,
            title=title.strip(),
            max_score=decimal.Decimal(max_score)
        )
        g.session.add(new_item)
        g.session.commit()

        return jsonify({'success': True, 'message': 'Item added successfully!', 'item_id': new_item.id})
    except (ValueError, decimal.InvalidOperation):
        g.session.rollback()
        return jsonify({'success': False, 'message': 'Invalid max score. Please enter a valid number.'}), 400
    except Exception as e:
        g.session.rollback()
        app.logger.error(f"Error adding gradable item: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/gradable-item/<uuid:item_id>/delete', methods=['POST'])
@login_required
@user_type_required('teacher')
def delete_gradable_item(item_id):
    try:
        item = g.session.query(GradableItem).join(GradingComponent).join(GradingSystem).filter(
            GradableItem.id == item_id,
            GradingSystem.teacher_id == session['user_id']
        ).first()

        if not item:
            return jsonify({'success': False, 'message': 'Item not found or you do not have permission.'}), 404
            
        g.session.delete(item)
        g.session.commit()
        return jsonify({'success': True, 'message': 'Item deleted successfully.'})
    except Exception as e:
        g.session.rollback()
        app.logger.error(f"Error deleting gradable item: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/api/item/<uuid:item_id>/student/<uuid:student_id>/score', methods=['POST'])
@login_required
@user_type_required('teacher')
def update_student_score(item_id, student_id):
    try:
        data = request.get_json()
        score_value_str = data.get('score')

        # Find the existing score record or create a new one
        score = g.session.query(StudentScore).filter_by(item_id=item_id, student_info_id=student_id).first()

        if score_value_str is None or score_value_str.strip() == '':
            # If the score is cleared, delete the record
            if score:
                # Log score deletion for teachers
                teacher_username = session.get('username', 'unknown')
                teacher_id = uuid.UUID(session['user_id'])
                student_name = g.session.query(StudentInfo).filter_by(id=student_id).first().name
                item_title = g.session.query(GradableItem).filter_by(id=item_id).first().title
                subject_name = g.session.query(GradableItem).join(GradingComponent).join(GradingSystem).join(SectionSubject).filter(GradableItem.id == item_id).first().section_subject.subject_name
                section_period_id = g.session.query(GradableItem).join(GradingComponent).join(GradingSystem).join(SectionSubject).filter(GradableItem.id == item_id).first().section_subject.section_period_id
                subject_id = g.session.query(GradableItem).join(GradingComponent).join(GradingSystem).join(SectionSubject).filter(GradableItem.id == item_id).first().section_subject.id
                
                create_teacher_log(
                    db_session=g.session,
                    teacher_id=teacher_id,
                    teacher_username=teacher_username,
                    action_type='delete_grade',
                    target_type='grade',
                    target_id=score.id,
                    target_name=f"{student_name} - {item_title}",
                    details=f"Deleted score for {student_name} in {subject_name} ({item_title})",
                    section_period_id=section_period_id,
                    subject_id=subject_id
                )
                
                g.session.delete(score)
                g.session.commit()
                return jsonify({'success': True, 'message': 'Score deleted.'})
            else:
                return jsonify({'success': True, 'message': 'No score to delete.'})

        score_value = decimal.Decimal(score_value_str)
        
        if score:
            score.score = score_value
            # Log score update for teachers
            teacher_username = session.get('username', 'unknown')
            teacher_id = uuid.UUID(session['user_id'])
            student_name = g.session.query(StudentInfo).filter_by(id=student_id).first().name
            item_title = g.session.query(GradableItem).filter_by(id=item_id).first().title
            subject_name = g.session.query(GradableItem).join(GradingComponent).join(GradingSystem).join(SectionSubject).filter(GradableItem.id == item_id).first().section_subject.subject_name
            section_period_id = g.session.query(GradableItem).join(GradingComponent).join(GradingSystem).join(SectionSubject).filter(GradableItem.id == item_id).first().section_subject.section_period_id
            subject_id = g.session.query(GradableItem).join(GradingComponent).join(GradingSystem).join(SectionSubject).filter(GradableItem.id == item_id).first().section_subject.id
            
            create_teacher_log(
                db_session=g.session,
                teacher_id=teacher_id,
                teacher_username=teacher_username,
                action_type='edit_grade',
                target_type='grade',
                target_id=score.id,
                target_name=f"{student_name} - {item_title}",
                details=f"Updated score for {student_name} in {subject_name} ({item_title}): {score_value}",
                section_period_id=section_period_id,
                subject_id=subject_id
            )
        else:
            # Security check: ensure the item belongs to the teacher before creating a score
            item = g.session.query(GradableItem).join(GradingComponent).join(GradingSystem).filter(
                GradableItem.id == item_id,
                GradingSystem.teacher_id == session['user_id']
            ).first()
            if not item:
                 return jsonify({'success': False, 'message': 'You do not have permission to grade this item.'}), 403
            
            score = StudentScore(item_id=item_id, student_info_id=student_id, score=score_value)
            g.session.add(score)
            
            # Log score addition for teachers
            teacher_username = session.get('username', 'unknown')
            teacher_id = uuid.UUID(session['user_id'])
            student_name = g.session.query(StudentInfo).filter_by(id=student_id).first().name
            subject_name = item.component.system.section_subject.subject_name
            section_period_id = item.component.system.section_subject.section_period_id
            subject_id = item.component.system.section_subject.id
            
            create_teacher_log(
                db_session=g.session,
                teacher_id=teacher_id,
                teacher_username=teacher_username,
                action_type='add_grade',
                target_type='grade',
                target_id=score.id,
                target_name=f"{student_name} - {item.title}",
                details=f"Added score for {student_name} in {subject_name} ({item.title}): {score_value}",
                section_period_id=section_period_id,
                subject_id=subject_id
            )
        
        g.session.commit()
        
        # Sync the calculated total grade to the grades table
        sync_total_grade_to_database(g.session, student_id, item.component.system.section_subject_id, uuid.UUID(session['user_id']), item.component.system.section_subject.section_period)
        
        # --- Recalculate averages for the response ---
        # This part could be abstracted into a helper function if it gets more complex
        item = g.session.query(GradableItem).get(item_id)
        component = item.component
        system = component.system
        
        # Get all scores for this student in this subject
        all_student_scores_query = g.session.query(StudentScore).join(GradableItem).join(GradingComponent).filter(
            GradingComponent.system_id == system.id,
            StudentScore.student_info_id == student_id
        ).all()
        student_scores_map = {s.item_id: s.score for s in all_student_scores_query}

        # Calculate this component's average
        component_items = component.items
        student_scores_sum = sum((decimal.Decimal(student_scores_map.get(i.id, 0)) for i in component_items), decimal.Decimal(0))
        max_scores_sum = sum((i.max_score for i in component_items), decimal.Decimal(0))
        component_average_val = (student_scores_sum / max_scores_sum) * 100 if max_scores_sum > 0 else 0
        component_average = f"{component_average_val:.2f}%"

        # Calculate total grade
        student_total_grade = decimal.Decimal('0.0')
        for comp in system.components:
            comp_items = comp.items
            if not comp_items: continue
            
            comp_student_sum = sum((decimal.Decimal(student_scores_map.get(i.id, 0)) for i in comp_items), decimal.Decimal(0))
            comp_max_sum = sum((i.max_score for i in comp_items), decimal.Decimal(0))

            if comp_max_sum > 0:
                average = comp_student_sum / comp_max_sum
                weight = decimal.Decimal(comp.weight) / decimal.Decimal('100.0')
                student_total_grade += average * weight
        
        total_grade = f"{student_total_grade * 100:.2f}"

        return jsonify({
            'success': True, 
            'message': 'Score updated.',
            'updates': {
                'component_id': str(component.id),
                'component_average': component_average,
                'total_grade': total_grade
            }
        })

    except (ValueError, decimal.InvalidOperation):
        g.session.rollback()
        return jsonify({'success': False, 'message': 'Invalid score format.'}), 400
    except Exception as e:
        g.session.rollback()
        app.logger.error(f"Error updating score: {e}")
        return jsonify({'success': False, 'message': 'An server error occurred.'}), 500

@app.route('/teacher/section_period/<uuid:section_period_id>/attendance_details/<uuid:subject_id>', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher', 'admin')
def teacher_section_attendance_details(section_period_id, subject_id):
    db_session = g.session
    teacher_id = uuid.UUID(session['user_id'])
    mode = request.args.get('mode')
    
    # Get the section period
    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand)
    ).filter(SectionPeriod.id == section_period_id).first()
    
    if not section_period:
        flash('Section period not found.', 'error')
        return redirect(url_for('teacher_dashboard'))

    # Check if teacher is assigned to this section period
    is_assigned_teacher = str(section_period.assigned_teacher_id) == str(teacher_id)
    
    if not is_assigned_teacher:
        flash('You do not have permission to view this section period.', 'error')
        return redirect(url_for('teacher_dashboard'))

    # Get the subject
    subject = db_session.query(SectionSubject).filter(
        SectionSubject.id == subject_id,
        SectionSubject.section_period_id == section_period_id
    ).first()
    
    if not subject:
        flash('Subject not found.', 'error')
        return redirect(url_for('teacher_section_period_view', section_period_id=section_period_id))

    # Check if the subject password has been verified
    if 'subject_password_verified' not in session or session['subject_password_verified'] != str(subject_id):
        flash('Please enter the subject password to access attendance.', 'info')
        return redirect(url_for('teacher_section_period_view', section_period_id=section_period_id))

    # If mode is history, show attendance history
    if mode == 'history':
        # Get all students in the section
        students = db_session.query(StudentInfo).filter(
            StudentInfo.section_period_id == section_period_id
        ).order_by(StudentInfo.name).all()

        # Calculate summary statistics for each student
        summary = []
        for student in students:
            attendance_records = db_session.query(Attendance).filter(
                Attendance.student_info_id == student.id,
                Attendance.section_subject_id == subject_id
            ).all()

            # Set gender to 'Unknown' if missing or empty
            gender = student.gender if student.gender else 'Unknown'

            stats = {
                'name': student.name,
                'gender': gender,  # Always set for template grouping
                'present_count': sum(1 for a in attendance_records if a.status == 'present'),
                'absent_count': sum(1 for a in attendance_records if a.status == 'absent'),
                'late_count': sum(1 for a in attendance_records if a.status == 'late'),
                'excused_count': sum(1 for a in attendance_records if a.status == 'excused')
            }
            summary.append(stats)

        # Get date-wise attendance summary
        dates_query = db_session.query(
            Attendance.attendance_date.label('date'),
            func.count(case((Attendance.status == 'present', 1))).label('present_count'),
            func.count(case((Attendance.status == 'absent', 1))).label('absent_count'),
            func.count(case((Attendance.status == 'late', 1))).label('late_count'),
            func.count(case((Attendance.status == 'excused', 1))).label('excused_count')
        ).filter(
            Attendance.section_subject_id == subject_id
        ).group_by(Attendance.attendance_date).order_by(Attendance.attendance_date.desc()).all()
        attendance_days_count = len(dates_query)
        return render_template('attendance_history.html',
                            section_period=section_period,
                            subject=subject,
                            summary=summary,
                         dates=dates_query,
                         attendance_days_count=attendance_days_count)

    # Get all students in this section period
    students = db_session.query(StudentInfo).filter(
        StudentInfo.section_period_id == section_period_id
    ).order_by(StudentInfo.name).all()

    if request.method == 'POST':
        attendance_date = request.form.get('attendance_date')
        if not attendance_date:
            flash('Attendance date is required.', 'error')
            return render_template('teacher_section_attendance_details.html',
                                section_period=section_period,
                                subject=subject,
                                students=students)

        try:
            # Parse attendance_date to a date object
            try:
                attendance_date_obj = datetime.strptime(attendance_date, '%Y-%m-%d').date()
            except Exception as date_exc:
                flash(f'Invalid date format: {attendance_date}. Please use YYYY-MM-DD.', 'error')
                return render_template('teacher_section_attendance_details.html',
                                    section_period=section_period,
                                    subject=subject,
                                    students=students)

            # Process attendance for each student
            for student in students:
                status = request.form.get(f'status_{student.id}')
                notes = request.form.get(f'notes_{student.id}')
                if status:
                    # Check if attendance record already exists for this date
                    existing_record = db_session.query(Attendance).filter(
                        Attendance.student_info_id == student.id,
                        Attendance.section_subject_id == subject_id,
                        Attendance.attendance_date == attendance_date_obj
                    ).first()

                    if existing_record:
                        existing_record.status = status
                        existing_record.recorded_by = teacher_id
                        existing_record.notes = notes if status in ['absent','late','excused'] else None
                    else:
                        new_attendance = Attendance(
                            student_info_id=student.id,
                            section_subject_id=subject_id,
                            attendance_date=attendance_date_obj,
                            status=status,
                            recorded_by=teacher_id,
                            notes=notes if status in ['absent','late','excused'] else None
                        )
                        db_session.add(new_attendance)

            db_session.commit()
            flash('Attendance recorded successfully!', 'success')
            return redirect(url_for('teacher_section_attendance_details',
                                  section_period_id=section_period_id,
                                  subject_id=subject_id,
                                  mode='history'))

        except Exception as e:
            db_session.rollback()
            flash(f'An error occurred while recording attendance: {e}', 'error')
            app.logger.error(f"Error recording attendance: {e}")

    return render_template('teacher_section_attendance_details.html',
                         section_period=section_period,
                         subject=subject,
                         students=students)

@app.route('/teacher/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/attendance/history')
@login_required
@user_type_required('teacher', 'admin')
def view_attendance_history(section_period_id, subject_id):
    db_session = g.session
    teacher_id = uuid.UUID(session['user_id'])

    # Get section period and subject details
    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand)
    ).filter(SectionPeriod.id == section_period_id).first()

    subject = db_session.query(SectionSubject).filter(
        SectionSubject.id == subject_id,
        SectionSubject.section_period_id == section_period_id
    ).first()

    if not section_period or not subject:
        flash('Section period or subject not found.', 'error')
        return redirect(url_for('teacher_dashboard'))

    # Check if teacher is assigned to this section period
    if str(section_period.assigned_teacher_id) != str(teacher_id):
        flash('You are not authorized to view this section\'s attendance.', 'error')
        return redirect(url_for('teacher_dashboard'))

    # Get all students in the section
    students = db_session.query(StudentInfo).filter(
        StudentInfo.section_period_id == section_period_id
    ).order_by(StudentInfo.name).all()

    # Calculate summary statistics for each student
    summary = []
    for student in students:
        attendance_records = db_session.query(Attendance).filter(
            Attendance.student_info_id == student.id,
            Attendance.section_subject_id == subject_id
        ).all()

        stats = {
            'name': student.name,
            'gender': student.gender,  # Add gender for template grouping
            'present_count': sum(1 for a in attendance_records if a.status == 'present'),
            'absent_count': sum(1 for a in attendance_records if a.status == 'absent'),
            'late_count': sum(1 for a in attendance_records if a.status == 'late'),
            'excused_count': sum(1 for a in attendance_records if a.status == 'excused')
        }
        summary.append(stats)

    # Get date-wise attendance summary
    dates_query = db_session.query(
        Attendance.attendance_date.label('date'),
        func.count(case((Attendance.status == 'present', 1))).label('present_count'),
        func.count(case((Attendance.status == 'absent', 1))).label('absent_count'),
        func.count(case((Attendance.status == 'late', 1))).label('late_count'),
        func.count(case((Attendance.status == 'excused', 1))).label('excused_count')
    ).filter(
        Attendance.section_subject_id == subject_id
    ).group_by(Attendance.attendance_date).order_by(Attendance.attendance_date.desc()).all()

    return render_template('attendance_history.html',
                         section_period=section_period,
                         subject=subject,
                         summary=summary,
                         dates=dates_query)

@app.route('/api/verify_adviser_password', methods=['POST'])
@login_required
@user_type_required('teacher')
def api_verify_adviser_password():
    data = request.get_json()
    section_id = data.get('section_id')
    password = data.get('password')
    if not section_id or not password:
        return jsonify({'success': False})
    db_session = g.session
    section = db_session.query(Section).filter_by(id=section_id).first()
    if section and section.adviser_password and password == section.adviser_password:
        # Set session flag for this section
        session[f'adviser_password_verified_{section_id}'] = True
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/subject/<uuid:subject_id>/sync-total-grades', methods=['POST'])
@login_required
@user_type_required('teacher')
def sync_total_grades_for_subject(subject_id):
    """Manually sync all total grades for a subject to the grades table."""
    try:
        subject = g.session.query(SectionSubject).get(subject_id)
        if not subject:
            return jsonify({'success': False, 'message': 'Subject not found.'}), 404
        
        # Check if teacher has permission
        if str(subject.section_period.assigned_teacher_id) != str(session['user_id']):
            return jsonify({'success': False, 'message': 'You do not have permission to sync grades for this subject.'}), 403
        
        # Get all students in this subject's section period
        students = g.session.query(StudentInfo).filter(
            StudentInfo.section_period_id == subject.section_period_id
        ).all()
        
        synced_count = 0
        for student in students:
            try:
                sync_total_grade_to_database(g.session, student.id, subject.id, uuid.UUID(session['user_id']), subject.section_period)
                synced_count += 1
            except Exception as e:
                app.logger.error(f"Error syncing grade for student {student.id}: {e}")
                continue
        # --- NEW: Update average_grade in students_info for each student ---
        for student in students:
            # Get all grades for this student in this section period
            grades = g.session.query(Grade).join(SectionSubject).filter(
                Grade.student_info_id == student.id,
                SectionSubject.section_period_id == subject.section_period_id
            ).all()
            if grades:
                avg = round(sum(float(g.grade_value) for g in grades) / len(grades), 3)
                student.average_grade = avg
            else:
                student.average_grade = None
        g.session.commit()
        # --- END NEW ---
        return jsonify({
            'success': True, 
            'message': f'Successfully synced total grades for {synced_count} students.'
        })
        
    except Exception as e:
        g.session.rollback()
        app.logger.error(f"Error syncing total grades: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while syncing grades.'}), 500

@app.route('/section_period/<uuid:section_period_id>/sync-average-grades', methods=['POST'])
@login_required
@user_type_required('admin', 'teacher')
def sync_average_grades(section_period_id):
    db_session = g.session
    # Get all students in this section period
    students = db_session.query(StudentInfo).filter_by(section_period_id=section_period_id).all()
    updated = 0
    for student in students:
        # Get all grades for this student in this period
        grades = db_session.query(Grade).join(SectionSubject).filter(
            Grade.student_info_id == student.id,
            SectionSubject.section_period_id == section_period_id
        ).all()
        if grades:
            avg = round(sum(float(g.grade_value) for g in grades) / len(grades), 3)
            student.average_grade = avg
            updated += 1
        else:
            student.average_grade = None
    db_session.commit()
    return jsonify({'success': True, 'message': f'Synced average grades for {updated} students.'})

@app.route('/teacher/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/quiz/create', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher')
def teacher_create_quiz(section_period_id, subject_id):
    db_session = g.session
    # Fetch the subject and its grading components
    subject = db_session.query(SectionSubject).filter_by(id=subject_id, section_period_id=section_period_id).first()
    if not subject:
        flash('Subject not found.', 'error')
        return redirect(url_for('teacher_section_period_view', section_period_id=section_period_id))
    grading_system = db_session.query(GradingSystem).filter_by(section_subject_id=subject_id).first()
    components = grading_system.components if grading_system else []

    if request.method == 'POST':
        # Basic stub: just flash a message and redirect back for now
        # (You can expand this to actually create a quiz object, etc.)
        flash('Quiz/Exam creation is not fully implemented yet.', 'info')
        return redirect(url_for('manage_subject_grades', section_period_id=section_period_id, subject_id=subject_id))

    return render_template('quiz/create_quiz.html', subject=subject, components=components)

@app.route('/teacher/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/quiz/maker')
@login_required
@user_type_required('teacher')
def quiz_maker(section_period_id, subject_id):
    db_session = g.session
    subject = db_session.query(SectionSubject).filter_by(id=subject_id, section_period_id=section_period_id).first()
    if not subject:
        flash('Subject not found.', 'error')
        return redirect(url_for('teacher_section_period_view', section_period_id=section_period_id))
    quiz_data = None
    edit_quiz_id = request.args.get('edit')
    if edit_quiz_id:
        from models import Quiz
        try:
            quiz = db_session.query(Quiz).filter_by(id=edit_quiz_id, subject_id=subject_id, section_period_id=section_period_id).first()
            if quiz:
                import json
                quiz_data = {
                    'id': str(quiz.id),
                    'title': quiz.title,
                    'questions': json.loads(quiz.questions_json) if quiz.questions_json else [],
                    'deadline': quiz.deadline.isoformat() if quiz.deadline else None,
                    'time_limit_minutes': quiz.time_limit_minutes
                }
        except Exception:
            quiz_data = None
    return render_template('quiz/quiz_maker.html', subject=subject, quiz_data=quiz_data)

@app.route('/api/quizzes', methods=['POST'])
@login_required
@user_type_required('teacher')
def api_create_quiz():
    try:
        data = request.get_json()
        db_session = g.session
        title = data.get('title')
        questions = data.get('questions')
        section_period_id = data.get('section_period_id')
        subject_id = data.get('subject_id')
        deadline = data.get('deadline')
        time_limit_minutes = data.get('time_limit_minutes')
        status = data.get('status', 'draft')
        if not (title and questions is not None and section_period_id and subject_id):
            return jsonify({'success': False, 'message': 'Missing required fields.'}), 400
        import json
        # Check for existing draft quiz for this title/subject/period
        existing_quiz = db_session.query(Quiz).filter_by(
            title=title,
            section_period_id=section_period_id,
            subject_id=subject_id
        ).first()
        if existing_quiz:
            # Update the existing quiz (draft or published)
            existing_quiz.questions_json = json.dumps(questions)
            existing_quiz.deadline = deadline if deadline else None
            existing_quiz.time_limit_minutes = time_limit_minutes if time_limit_minutes else None
            existing_quiz.status = status
            db_session.commit()
            return jsonify({'success': True, 'message': 'Quiz updated!', 'quiz_id': str(existing_quiz.id)})
        quiz = Quiz(
            title=title,
            description=None,
            section_period_id=section_period_id,
            subject_id=subject_id,
            questions_json=json.dumps(questions),
            deadline=deadline if deadline else None,
            time_limit_minutes=time_limit_minutes if time_limit_minutes else None,
            status=status
        )
        db_session.add(quiz)
        db_session.commit()
        return jsonify({'success': True, 'message': 'Quiz created!', 'quiz_id': str(quiz.id)})
    except Exception as e:
        import traceback
        app.logger.error(f"Error in /api/quizzes: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'message': str(e)}), 500

# --- Parent Portal Sync Helper Function ---
def sync_student_to_parent_portal(student, parent_id, logger=None):
    """
    Sync a student to the parent portal's students table.
    """
    from sqlalchemy.orm import sessionmaker as ParentSessionMaker, declarative_base as ParentDeclarativeBase
    from sqlalchemy import create_engine as create_parent_engine
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID
    from sqlalchemy import Column, String, DateTime, ForeignKey
    import datetime
    import uuid as uuidlib

    PARENT_DATABASE_URL = os.environ.get('DATABASE_URL')
    if not PARENT_DATABASE_URL:
        if logger: logger.error("No DATABASE_URL for parent portal sync.")
        return False, "No DATABASE_URL"

    parent_engine = create_parent_engine(PARENT_DATABASE_URL, pool_pre_ping=True)
    ParentSession = ParentSessionMaker(bind=parent_engine)
    parent_db_session = ParentSession()
    ParentPortalBase = ParentDeclarativeBase()

    try:
        ParentPortalBase.metadata.create_all(parent_engine)
        portal_student = parent_db_session.query(ParentPortalStudent).filter_by(student_id_number=student.student_id_number).first()
        name_parts = student.name.split()
        first_name = name_parts[0]
        last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
        section = student.section_period.section
        grade_level = section.grade_level.name if section and section.grade_level else ''
        section_name = section.name if section else ''
        strand_name = section.strand.name if section and section.strand else None

        if not portal_student:
            new_portal_student = ParentPortalStudent(
                id=uuidlib.uuid4(),
                parent_id=parent_id,
                student_id_number=student.student_id_number,
                first_name=first_name,
                last_name=last_name,
                grade_level=grade_level or '',
                section_name=section_name or '',
                strand_name=strand_name or '',
                created_at=datetime.datetime.utcnow()
            )
            parent_db_session.add(new_portal_student)
        else:
            setattr(portal_student, 'parent_id', parent_id)
            setattr(portal_student, 'first_name', first_name)
            setattr(portal_student, 'last_name', last_name)
            setattr(portal_student, 'grade_level', grade_level or '')
            setattr(portal_student, 'section_name', section_name or '')
            setattr(portal_student, 'strand_name', strand_name or '')
        parent_db_session.commit()
        return True, "Sync successful"
    except Exception as e:
        parent_db_session.rollback()
        if logger: logger.error(f"Error syncing to parent portal: {e}")
        return False, str(e)
    finally:
        parent_db_session.close()

@app.route('/section_period/<uuid:section_period_id>/sync_students_from_first_sem', methods=['POST'])
@login_required
@user_type_required('admin')
def sync_students_from_first_sem(section_period_id):
    db_session = g.session
    try:
        section_period = db_session.query(SectionPeriod).filter_by(id=section_period_id).first()
        if not section_period:
            flash('Section period not found.', 'danger')
            return redirect(url_for('section_period_details', section_period_id=section_period_id))

        # Only allow for 2nd Semester, SHS
        if section_period.period_type != 'Semester' or section_period.period_name.strip().lower() != '2nd semester':
            flash('Sync is only allowed for 2nd Semester periods.', 'warning')
            return redirect(url_for('section_period_details', section_period_id=section_period_id))

        # Find the 1st Semester for the same section and school year
        first_sem = db_session.query(SectionPeriod).filter_by(
            section_id=section_period.section_id,
            school_year=section_period.school_year,
            period_type='Semester',
            period_name='1st Semester'
        ).first()
        if not first_sem:
            flash('1st Semester period not found for this section and school year.', 'warning')
            return redirect(url_for('section_period_details', section_period_id=section_period_id))

        # Get all students in 1st Semester
        first_sem_students = db_session.query(StudentInfo).filter_by(section_period_id=first_sem.id).all()
        # Get all student_id_numbers already in 2nd Semester
        second_sem_students = db_session.query(StudentInfo).filter_by(section_period_id=section_period_id).all()
        second_sem_id_numbers = {s.student_id_number for s in second_sem_students}

        added = 0
        for student in first_sem_students:
            # Always append -S2 for 2nd Sem student_id_number
            base_id = student.student_id_number
            if not base_id.endswith('-S2'):
                new_id = f"{base_id}-S2"
            else:
                new_id = base_id
            if new_id not in second_sem_id_numbers:
                new_student = StudentInfo(
                    section_period_id=section_period_id,
                    name=student.name,
                    student_id_number=new_id,
                    gender=student.gender,
                    parent_id=student.parent_id,
                    password_hash=student.password_hash
                )
                db_session.add(new_student)
                added += 1
        db_session.commit()
        if added:
            flash(f'Successfully synced {added} students from 1st Semester.', 'success')
        else:
            flash('No new students to sync from 1st Semester.', 'info')
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error syncing students from 1st Semester: {e}")
        flash('An error occurred while syncing students.', 'danger')
    return redirect(url_for('section_period_details', section_period_id=section_period_id))

@app.route('/api/student/<uuid:student_id>/password')
def get_student_password(student_id):
    db_session = g.session
    student = db_session.query(StudentInfo).filter_by(id=student_id).first()
    if not student:
        return {'success': False, 'message': 'Student not found.'}, 404
    return {'success': True, 'password': student.password_hash or ''}

@app.route('/teacher/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/quiz/dashboard')
@login_required
@user_type_required('teacher')
def quiz_dashboard(section_period_id, subject_id):
    return render_template('quiz/quiz_dashboard.html', section_period_id=section_period_id, subject_id=subject_id)

@app.route('/teacher/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/quiz/manager')
@login_required
@user_type_required('teacher')
def manage_quiz(section_period_id, subject_id):
    from models import StudentQuizResult, StudentQuizAnswer
    db_session = g.session
    # Fetch the subject to verify it exists and teacher has access
    subject = db_session.query(SectionSubject).filter_by(id=subject_id, section_period_id=section_period_id).first()
    if not subject:
        flash('Subject not found.', 'error')
        return redirect(url_for('teacher_section_period_view', section_period_id=section_period_id))
    # Get all students in this section_period
    students = db_session.query(StudentInfo).filter_by(section_period_id=section_period_id).order_by(StudentInfo.name).all()
    # Get all quizzes for this subject
    quizzes = db_session.query(Quiz).filter_by(subject_id=subject_id).order_by(Quiz.created_at.desc()).all()
    # Calculate quiz statistics
    total_students = len(students)
    # Only count published quizzes for denominator
    published_quizzes = [q for q in quizzes if getattr(q, 'status', 'published') == 'published']
    total_published_quizzes = len(published_quizzes)
    total_quizzes = len(quizzes)
    # Calculate class average and recent activity
    class_average = "N/A"
    recent_activity = 0
    recent_activity_denominator = total_students * total_published_quizzes
    if total_published_quizzes > 0 and total_students > 0:
        all_results = db_session.query(StudentQuizResult).join(Quiz).filter(Quiz.subject_id == subject_id).all()
        if all_results:
            total_scores = sum(result.score for result in all_results)
            total_possible = sum(result.total_points for result in all_results)
            if total_possible > 0:
                class_average = f"{round((total_scores / total_possible) * 100, 1)}%"
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            # Only count submissions for published quizzes
            published_quiz_ids = [q.id for q in published_quizzes]
            recent_activity = len([
                r for r in all_results
                if r.completed_at and r.completed_at > week_ago and r.quiz_id in published_quiz_ids
            ])
    # Create quiz status map
    quiz_status_map = {}
    import json
    for quiz in quizzes:
        if getattr(quiz, 'status', 'published') != 'published':
            quiz_status_map[quiz.id] = 'draft'
            continue
        try:
            questions = json.loads(quiz.questions_json or '[]')
            essay_qids = [str(q['id']) for q in questions if q.get('type') == 'essay_type']
            if essay_qids:
                unscored_essays = db_session.query(StudentQuizAnswer).join(StudentQuizResult).filter(
                    StudentQuizResult.quiz_id == quiz.id,
                    StudentQuizAnswer.question_id.in_(essay_qids),
                    StudentQuizAnswer.score.is_(None)
                ).first()
                quiz_status_map[quiz.id] = 'pending' if unscored_essays else 'completed'
            else:
                quiz_status_map[quiz.id] = 'completed'
        except:
            quiz_status_map[quiz.id] = 'completed'
    # Calculate student averages and progress
    for student in students:
        student_results = db_session.query(StudentQuizResult).join(Quiz).filter(
            Quiz.subject_id == subject_id,
            StudentQuizResult.student_info_id == student.id
        ).all()
        if student_results:
            total_score = sum(r.score for r in student_results)
            total_possible = sum(r.total_points for r in student_results)
            if total_possible > 0:
                student.average_grade = round((total_score / total_possible) * 100, 1)
            else:
                student.average_grade = None
            student.progress = f"{len(student_results)}/{total_quizzes}"
        else:
            student.average_grade = None
            student.progress = f"0/{total_quizzes}"
    return render_template('quiz/manage_quiz.html', 
                         section_period_id=section_period_id, 
                         subject_id=subject_id,
                         students=students,
                         quizzes=quizzes,
                         quiz_status_map=quiz_status_map,
                         total_students=total_students,
                         total_quizzes=total_quizzes,
                         class_average=class_average,
                         recent_activity=recent_activity,
                         recent_activity_denominator=recent_activity_denominator)

@app.route('/teacher/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/student/<uuid:student_id>/quiz')
@login_required
@user_type_required('teacher')
def manage_student_quiz(section_period_id, subject_id, student_id):
    db_session = g.session
    
    # Fetch the subject and student to verify they exist and teacher has access
    subject = db_session.query(SectionSubject).filter_by(id=subject_id, section_period_id=section_period_id).first()
    if not subject:
        flash('Subject not found.', 'error')
        return redirect(url_for('teacher_section_period_view', section_period_id=section_period_id))
    
    student = db_session.query(StudentInfo).filter_by(id=student_id, section_period_id=section_period_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('manage_quiz', section_period_id=section_period_id, subject_id=subject_id))
    
    # Get all quizzes for this subject
    quizzes = db_session.query(Quiz).filter_by(subject_id=subject_id).order_by(Quiz.created_at.desc()).all()
    
    # Get student's quiz results and prepare quiz rows
    from models import StudentQuizResult, StudentQuizAnswer
    import json
    
    quiz_rows = []
    for quiz in quizzes:
        # Get student's attempt for this quiz
        attempt = db_session.query(StudentQuizResult).filter_by(
            student_info_id=student_id, 
            quiz_id=quiz.id
        ).first()
        
        # Check if quiz has essay questions
        essay_questions = []
        essay_answers = []
        try:
            questions = json.loads(quiz.questions_json or '[]')
            essay_questions = [q for q in questions if q.get('type') == 'essay_type']
        except:
            pass
        
        # Get essay answers if student has attempted the quiz
        if attempt and essay_questions:
            essay_answers = db_session.query(StudentQuizAnswer).filter_by(
                student_quiz_result_id=attempt.id
            ).all()
        
        # Determine status
        status = 'not_attempted'
        if attempt:
            if essay_questions:
                # Check if any essay questions are unscored
                unscored = db_session.query(StudentQuizAnswer).filter(
                    StudentQuizAnswer.student_quiz_result_id == attempt.id,
                    StudentQuizAnswer.question_id.in_([str(q['id']) for q in essay_questions]),
                    StudentQuizAnswer.score.is_(None)
                ).first()
                status = 'pending' if unscored else 'completed'
            else:
                status = 'completed'
        
        quiz_rows.append({
            'quiz': quiz,
            'attempt': attempt,
            'status': status,
            'essay_questions': essay_questions,
            'essay_answers': essay_answers
        })
    
    return render_template('quiz/manage_student_quiz.html',
                         section_period_id=section_period_id,
                         subject_id=subject_id,
                         student=student,
                         quiz_rows=quiz_rows)

@app.route('/teacher/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/student/<uuid:student_id>/quiz/<uuid:quiz_id>/score-essay', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher')
def score_student_essay(section_period_id, subject_id, student_id, quiz_id):
    db_session = g.session
    from models import StudentQuizResult, StudentQuizAnswer
    import json
    # Fetch the subject and student to verify they exist and teacher has access
    subject = db_session.query(SectionSubject).filter_by(id=subject_id, section_period_id=section_period_id).first()
    if not subject:
        flash('Subject not found.', 'error')
        return redirect(url_for('teacher_section_period_view', section_period_id=section_period_id))
    student = db_session.query(StudentInfo).filter_by(id=student_id, section_period_id=section_period_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('manage_quiz', section_period_id=section_period_id, subject_id=subject_id))
    quiz = db_session.query(Quiz).filter_by(id=quiz_id, subject_id=subject_id).first()
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('manage_student_quiz', section_period_id=section_period_id, subject_id=subject_id, student_id=student_id))
    quiz_result = db_session.query(StudentQuizResult).filter_by(
        student_info_id=student_id, 
        quiz_id=quiz_id
    ).first()
    if not quiz_result:
        flash('Student has not attempted this quiz.', 'error')
        return redirect(url_for('manage_student_quiz', section_period_id=section_period_id, subject_id=subject_id, student_id=student_id))
    questions = json.loads(quiz.questions_json or '[]')
    essay_questions = [q for q in questions if q.get('type') == 'essay_type']
    # GET: Render the essay scoring page
    if request.method == 'GET':
        # Get all essay answers for this attempt, use string keys
        all_answers = db_session.query(StudentQuizAnswer).filter_by(student_quiz_result_id=quiz_result.id).all()
        essay_answers = {str(a.question_id): a for a in all_answers}
        return render_template(
            'quiz/quiz_check_essay.html',
            quiz=quiz,
            student=student,
            essay_questions=essay_questions,
            essay_answers=essay_answers,
            section_period_id=section_period_id,
            subject_id=subject_id
        )
    # POST: Process essay scores
    try:
        total_essay_score = 0
        total_essay_points = 0
        for question in essay_questions:
            question_id = str(question['id'])
            score_key = f'score_{question_id}'
            if score_key in request.form:
                score_value = request.form[score_key]
                if score_value and score_value.strip():
                    try:
                        score = float(score_value)
                        max_points = float(question.get('points', 1))
                        essay_answer = db_session.query(StudentQuizAnswer).filter_by(
                            student_quiz_result_id=quiz_result.id,
                            question_id=question_id
                        ).first()
                        if essay_answer:
                            essay_answer.score = score
                        else:
                            essay_answer = StudentQuizAnswer(
                                student_quiz_result_id=quiz_result.id,
                                question_id=question_id,
                                answer_text=request.form.get(f'answer_{question_id}', ''),
                                score=score
                            )
                            db_session.add(essay_answer)
                        total_essay_score += score
                        total_essay_points += max_points
                    except ValueError:
                        flash(f'Invalid score for question {question_id}.', 'error')
                        return redirect(url_for('score_student_essay', section_period_id=section_period_id, subject_id=subject_id, student_id=student_id, quiz_id=quiz_id))
        # Update the quiz result with new total score
        if total_essay_points > 0:
            all_questions = questions
            all_answers = db_session.query(StudentQuizAnswer).filter_by(student_quiz_result_id=quiz_result.id).all()
            answer_map = {str(a.question_id): a for a in all_answers}
            total_score = 0
            total_points = 0
            for q in all_questions:
                qid = str(q['id'])
                pts = float(q.get('points', 1))
                total_points += pts
                if q.get('type') == 'essay_type':
                    ans = answer_map.get(qid)
                    if ans and ans.score is not None:
                        total_score += float(ans.score)
                else:
                    # For auto-scored questions, check if the answer was correct
                    # Find the student's original answer from StudentQuizAnswer if available
                    ans = answer_map.get(qid)
                    if ans and hasattr(ans, 'score') and ans.score is not None:
                        # If the answer was auto-scored and correct, score is points, else 0
                        total_score += float(ans.score)
            quiz_result.score = total_score
            quiz_result.total_points = total_points
        db_session.commit()
        flash('Essay scores saved successfully!', 'success')
        # PRG: Redirect to GET after POST
        return redirect(url_for('score_student_essay', section_period_id=section_period_id, subject_id=subject_id, student_id=student_id, quiz_id=quiz_id))
    except Exception as e:
        db_session.rollback()
        flash(f'Error saving essay scores: {str(e)}', 'error')
        return redirect(url_for('score_student_essay', section_period_id=section_period_id, subject_id=subject_id, student_id=student_id, quiz_id=quiz_id))

@app.route('/teacher/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/quiz/<uuid:quiz_id>/delete', methods=['POST'])
@login_required
@user_type_required('teacher')
def delete_quiz(section_period_id, subject_id, quiz_id):
    db_session = g.session
    from models import Quiz, StudentQuizResult, StudentQuizAnswer
    try:
        # Delete all related student quiz answers and results
        results = db_session.query(StudentQuizResult).filter_by(quiz_id=quiz_id).all()
        for result in results:
            db_session.query(StudentQuizAnswer).filter_by(student_quiz_result_id=result.id).delete()
            db_session.delete(result)
        # Delete the quiz itself
        quiz = db_session.query(Quiz).filter_by(id=quiz_id, subject_id=subject_id, section_period_id=section_period_id).first()
        if quiz:
            db_session.delete(quiz)
            db_session.commit()
            return {'success': True}
        else:
            return {'success': False, 'message': 'Quiz not found.'}
    except Exception as e:
        db_session.rollback()
        return {'success': False, 'message': str(e)}

if __name__ == '__main__':
    app.run(debug=True, port=5000)



