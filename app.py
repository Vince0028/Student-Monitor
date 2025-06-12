import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import uuid
from datetime import date, timedelta
import re # For school year validation

# Import SQLAlchemy components
from sqlalchemy import create_engine, Column, Integer, String, Date, Numeric, ForeignKey, DateTime, UniqueConstraint, and_, or_
from sqlalchemy.orm import sessionmaker, relationship, declarative_base, aliased, joinedload
from sqlalchemy.sql import func
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

# Import the PostgreSQL specific UUID type
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from dotenv import load_dotenv

load_dotenv()

# --- Flask App Configuration ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'supersecretkey_for_development_only')

# Database connection details
DATABASE_URL = os.environ.get('DATABASE_URL')

print(f"DEBUG: DATABASE_URL being used: {DATABASE_URL}")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set. Please set it in your .env file or as a system environment variable before running the app.")

# --- SQLAlchemy Setup ---
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Base = declarative_base()

# Define SQLAlchemy Models
class User(Base):
    __tablename__ = 'users'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    user_type = Column(String(10), nullable=False) # 'student' or 'teacher'
    specialization = Column(String(255), nullable=True) # For teachers: STEM, ICT, ABM, HUMSS, GAS, HE (for SHS), NULL for JHS
    grade_level_assigned = Column(String(50), nullable=True) # e.g., 'Grade 7', 'Grade 11'. Null for student admin.
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships for Student Admin
    created_grade_levels = relationship('GradeLevel', back_populates='creator', cascade='all, delete-orphan', foreign_keys='GradeLevel.created_by')
    # CORRECTED TYPO: back_populates
    created_strands_admin = relationship('Strand', back_populates='creator', cascade='all, delete-orphan', foreign_keys='Strand.created_by')
    created_sections_admin = relationship('Section', back_populates='creator', cascade='all, delete-orphan', foreign_keys='Section.created_by')
    created_section_periods_admin = relationship('SectionPeriod', back_populates='creator_admin', cascade='all, delete-orphan', foreign_keys='SectionPeriod.created_by_admin')
    
    # Relationships for Teachers
    sections_periods_assigned_teacher = relationship('SectionPeriod', back_populates='assigned_teacher', foreign_keys='SectionPeriod.assigned_teacher_id')
    # Updated relationship: creator_teacher now refers to who created the SectionSubject record
    created_section_subjects = relationship('SectionSubject', back_populates='creator_teacher', cascade='all, delete-orphan', foreign_keys='SectionSubject.created_by_teacher_id')
    # No longer a direct relationship for 'assigned_section_subjects' as it's a string field
    recorded_attendance = relationship('Attendance', back_populates='recorder_user')
    assigned_grades = relationship('Grade', back_populates='teacher')

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', user_type='{self.user_type}', specialization='{self.specialization}', grade_level_assigned='{self.grade_level_assigned}')>"

class GradeLevel(Base):
    __tablename__ = 'grade_levels'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False) # e.g., 'Grade 7', 'Grade 11'
    level_type = Column(String(10), nullable=False) # 'JHS' or 'SHS'
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id')) # Student admin who created it
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    creator = relationship('User', back_populates='created_grade_levels')
    sections = relationship('Section', back_populates='grade_level', cascade='all, delete-orphan')
    strands = relationship('Strand', back_populates='grade_level', cascade='all, delete-orphan') # Strands belong to specific grade levels (11, 12)

    def __repr__(self):
        return f"<GradeLevel(id={self.id}, name='{self.name}', type='{self.level_type}')>"

class Strand(Base):
    __tablename__ = 'strands'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False) # e.g., 'STEM', 'ICT'
    grade_level_id = Column(PG_UUID(as_uuid=True), ForeignKey('grade_levels.id'), nullable=False) # Only for SHS grades (11/12)
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id')) # Student admin who created it
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('name', 'grade_level_id'),
    )

    creator = relationship('User', back_populates='created_strands_admin')
    grade_level = relationship('GradeLevel', back_populates='strands')
    sections = relationship('Section', back_populates='strand', cascade='all, delete-orphan') # NEW: Strand now has sections

    def __repr__(self):
        return f"<Strand(id={self.id}, name='{self.name}', grade_level_id={self.grade_level_id})>"

class Section(Base):
    __tablename__ = 'sections'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False) # e.g., 'A', 'B', 'Purity'
    grade_level_id = Column(PG_UUID(as_uuid=True), ForeignKey('grade_levels.id'), nullable=False) # Section belongs to a grade level
    strand_id = Column(PG_UUID(as_uuid=True), ForeignKey('strands.id'), nullable=True) # NEW: Section can belong to a Strand (for SHS)
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id')) # Student admin who created it
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('name', 'grade_level_id', 'strand_id'), # Updated unique constraint
    )

    grade_level = relationship('GradeLevel', back_populates='sections', lazy='joined')
    strand = relationship('Strand', back_populates='sections', foreign_keys=[strand_id]) # NEW relationship
    creator = relationship('User', back_populates='created_sections_admin')
    section_periods = relationship('SectionPeriod', back_populates='section', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Section(id={self.id}, name='{self.name}', grade_level_id={self.grade_level_id}, strand_id={self.strand_id})>"

class SectionPeriod(Base): # Renamed from SectionSemester
    __tablename__ = 'section_periods'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id = Column(PG_UUID(as_uuid=True), ForeignKey('sections.id'), nullable=False)
    period_type = Column(String(50), nullable=False) # 'Semester' or 'Quarter'
    period_name = Column(String(50), nullable=False) # e.g., '1st Sem', 'Q1'
    school_year = Column(String(50), nullable=False) # e.g., '2025-2026'
    assigned_teacher_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=True) # Teacher dynamically assigned or chosen
    created_by_admin = Column(PG_UUID(as_uuid=True), ForeignKey('users.id')) # Student admin
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('section_id', 'period_name', 'school_year'), # Updated unique constraint
    )

    section = relationship('Section', back_populates='section_periods')
    assigned_teacher = relationship('User', back_populates='sections_periods_assigned_teacher', foreign_keys=[assigned_teacher_id])
    creator_admin = relationship('User', back_populates='created_section_periods_admin', foreign_keys=[created_by_admin])

    students_in_period = relationship('StudentInfo', back_populates='section_period', cascade='all, delete-orphan')
    section_subjects = relationship('SectionSubject', back_populates='section_period', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<SectionPeriod(id={self.id}, section_id={self.section_id}, period='{self.period_name}', type='{self.period_type}', year='{self.school_year}', assigned_teacher_id='{self.assigned_teacher_id}')>"


class StudentInfo(Base):
    __tablename__ = 'students_info'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_period_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_periods.id'), nullable=False) # Links to SectionPeriod
    name = Column(String(255), nullable=False)
    student_id_number = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    section_period = relationship('SectionPeriod', back_populates='students_in_period')
    attendance_records = relationship('Attendance', back_populates='student_info', cascade='all, delete-orphan')
    grades = relationship('Grade', back_populates='student_info', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<StudentInfo(id={self.id}, name='{self.name}', student_id_number='{self.student_id_number}')>"

class SectionSubject(Base):
    __tablename__ = 'section_subjects'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_period_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_periods.id'), nullable=False) # Links to SectionPeriod
    subject_name = Column(String(255), nullable=False)
    # The teacher account who created this subject record (e.g., the g12ict account)
    created_by_teacher_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=False) 
    # NEW: The name of the human teacher assigned to this subject (free text)
    assigned_teacher_name = Column(String(255), nullable=False) 
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('section_period_id', 'subject_name'),
    )

    section_period = relationship('SectionPeriod', back_populates='section_subjects')
    creator_teacher = relationship('User', foreign_keys=[created_by_teacher_id], back_populates='created_section_subjects')
    # No direct relationship for assigned_teacher_for_subject anymore as it's a string
    grades = relationship('Grade', back_populates='section_subject', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<SectionSubject(id={self.id}, section_period_id={self.section_period_id}, subject_name='{self.subject_name}', assigned_teacher_name='{self.assigned_teacher_name}')>"

class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_info_id = Column(PG_UUID(as_uuid=True), ForeignKey('students_info.id'), nullable=False)
    attendance_date = Column(Date, nullable=False)
    status = Column(String(50), nullable=False) # 'present', 'absent', 'late', 'excused'
    recorded_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id')) # The specific teacher account that recorded this attendance
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('student_info_id', 'attendance_date'),
    )

    student_info = relationship('StudentInfo', back_populates='attendance_records')
    recorder_user = relationship('User', back_populates='recorded_attendance')

    def __repr__(self):
        return f"<Attendance(id={self.id}, student_info_id={self.student_info_id}, date={self.attendance_date}, status='{self.status}')>"

class Grade(Base):
    __tablename__ = 'grades'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_info_id = Column(PG_UUID(as_uuid=True), ForeignKey('students_info.id'), nullable=False)
    section_subject_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_subjects.id'), nullable=False)
    teacher_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=False) # The specific teacher account that assigned this grade
    grade_value = Column(Numeric(5, 2), nullable=False)
    semester = Column(String(50), nullable=True) # Will be derived from SectionPeriod.period_name if period_type is 'Semester'
    school_year = Column(String(50), nullable=False) # Will be derived from SectionPeriod.school_year
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('student_info_id', 'section_subject_id', 'semester', 'school_year'), # Keep for now
    )

    student_info = relationship('StudentInfo', back_populates='grades')
    section_subject = relationship('SectionSubject', back_populates='grades')
    teacher = relationship('User', back_populates='assigned_grades')

    def __repr__(self):
        return f"<Grade(id={self.id}, student_info_id={self.student_info_id}, subject='{self.section_subject.subject_name}', grade={self.grade_value}')>"


Session = sessionmaker(bind=engine)

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

def user_type_required(required_type):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_type' not in session or session['user_type'] != required_type:
                flash(f'Access denied. You must be a {required_type.capitalize()} to view this page.', 'danger')
                if session.get('user_type') == 'student':
                    return redirect(url_for('student_dashboard'))
                elif session.get('user_type') == 'teacher':
                    return redirect(url_for('teacher_dashboard'))
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

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

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
            session['user_id'] = str(user.id)
            session['username'] = user.username
            session['user_type'] = user.user_type
            session['specialization'] = user.specialization # Teacher specialization (will be None for JHS)
            session['grade_level_assigned'] = user.grade_level_assigned # Teacher assigned grade level

            flash(f'Welcome, {user.username}! You are logged in as a {user.user_type.capitalize()}.', 'success')
            if session['user_type'] == 'student':
                return redirect(url_for('student_dashboard'))
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
    return redirect(url_for('index'))

# --- User Profile Management ---
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    user = db_session.query(User).filter_by(id=user_id).first()

    if not user:
        flash('User profile not found. Please log in again.', 'danger')
        session.clear()
        return redirect(url_for('login'))

    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_username = request.form.get('new_username', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_new_password = request.form.get('confirm_new_password', '').strip()

        # --- Password verification for any changes ---
        if not current_password or not check_password_hash(user.password_hash, current_password):
            flash('Incorrect current password. No changes were saved.', 'danger')
            return render_template('profile.html', user=user)

        changes_made = False

        # --- Update Username ---
        if new_username and new_username != user.username:
            existing_user_with_new_username = db_session.query(User).filter_by(username=new_username).first()
            if existing_user_with_new_username and existing_user_with_new_username.id != user.id:
                flash(f'Username "{new_username}" is already taken. Please choose a different one.', 'danger')
                return render_template('profile.html', user=user)
            user.username = new_username
            session['username'] = new_username # Update session immediately
            flash('Username updated successfully!', 'success')
            changes_made = True
        elif new_username == user.username:
            pass # No change, no error
        else:
            # If new_username was empty or only whitespace, prevent setting it blank
            if request.form.get('new_username') is not None and not new_username: # Check if field was submitted, but empty
                flash('Username cannot be empty or just spaces.', 'danger')
                return render_template('profile.html', user=user)

        # --- Update Password ---
        if new_password:
            if new_password != confirm_new_password:
                flash('New password and confirmation do not match.', 'danger')
                return render_template('profile.html', user=user)
            if len(new_password) < 6: # Basic password length check
                flash('New password must be at least 6 characters long.', 'danger')
                return render_template('profile.html', user=user)
            
            user.password_hash = generate_password_hash(new_password)
            flash('Password updated successfully!', 'success')
            changes_made = True
        elif new_password and not confirm_new_password: # New password entered but no confirmation
            flash('Please confirm your new password.', 'danger')
            return render_template('profile.html', user=user)
        elif not new_password and confirm_new_password: # Confirmation entered but no new password
            flash('Please enter a new password to confirm.', 'danger')
            return render_template('profile.html', user=user)


        try:
            if changes_made:
                db_session.commit()
                flash('Your profile has been updated.', 'success')
            else:
                flash('No changes were submitted or detected.', 'info')
            return redirect(url_for('profile')) # Redirect to GET to clear form data
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error updating profile for user {user.username}: {e}")
            flash('An error occurred while updating your profile. Please try again.', 'danger')

    return render_template('profile.html', user=user)




# --- Student Admin Dashboard Routes ---
@app.route('/student_dashboard')
@login_required
@user_type_required('student')
def student_dashboard():
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])
    
    # Student admin dashboard now only shows Grade Levels
    grade_levels = db_session.query(GradeLevel).filter_by(created_by=student_admin_id).order_by(GradeLevel.name).all()
    
    return render_template('student_dashboard.html', grade_levels=grade_levels)

@app.route('/add_grade_level', methods=['GET', 'POST'])
@login_required
@user_type_required('student')
def add_grade_level():
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])

    if request.method == 'POST':
        grade_name = request.form['name'].strip()
        
        if not grade_name:
            flash('Grade Level name cannot be empty.', 'error')
            return render_template('add_grade_level.html', all_grade_levels=ALL_GRADE_LEVELS)

        # Determine level_type based on grade_name
        if grade_name in GRADE_LEVELS_SHS:
            level_type = 'SHS'
        elif grade_name in GRADE_LEVELS_JHS:
            level_type = 'JHS'
        else:
            flash('Invalid Grade Level selected.', 'error')
            return render_template('add_grade_level.html', all_grade_levels=ALL_GRADE_LEVELS)

        try:
            existing_grade_level = db_session.query(GradeLevel).filter(func.lower(GradeLevel.name) == func.lower(grade_name)).first()
            if existing_grade_level:
                flash(f'Grade Level "{grade_name}" already exists.', 'error')
                return render_template('add_grade_level.html', all_grade_levels=ALL_GRADE_LEVELS)

            new_grade_level = GradeLevel(name=grade_name, level_type=level_type, created_by=student_admin_id)
            db_session.add(new_grade_level)
            db_session.commit()
            flash(f'Grade Level "{grade_name}" added successfully!', 'success')
            return redirect(url_for('student_dashboard'))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error adding grade level: {e}")
            flash('An error occurred while adding the grade level. Please try again.', 'error')

    return render_template('add_grade_level.html', all_grade_levels=ALL_GRADE_LEVELS)

@app.route('/grade_level/<uuid:grade_level_id>/delete', methods=['POST'])
@login_required
@user_type_required('student')
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
        return jsonify({'success': True, 'message': f'Grade Level "{grade_level_to_delete.name}" and all its associated data (strands, sections, periods, students, subjects, attendance, and grades) have been deleted.'})
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting grade level: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred while deleting the grade level.'})


@app.route('/grade_level/<uuid:grade_level_id>')
@login_required
@user_type_required('student')
def grade_level_details(grade_level_id):
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])
    
    grade_level = db_session.query(GradeLevel).filter_by(id=grade_level_id, created_by=student_admin_id).first()
    if not grade_level:
        flash('Grade Level not found or you do not have permission to view it.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    sections = db_session.query(Section).options(joinedload(Section.strand)).filter_by(grade_level_id=grade_level_id).order_by(Section.name).all()
    
    strands = []
    if grade_level.level_type == 'SHS':
        strands = db_session.query(Strand).filter_by(grade_level_id=grade_level_id).order_by(Strand.name).all()

    return render_template('grade_level_details.html', 
                           grade_level=grade_level, 
                           sections=sections, 
                           strands=strands)

@app.route('/grade_level/<uuid:grade_level_id>/add_strand', methods=['GET', 'POST'])
@login_required
@user_type_required('student')
def add_strand(grade_level_id):
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])

    grade_level = db_session.query(GradeLevel).filter_by(id=grade_level_id, created_by=student_admin_id).first()
    if not grade_level or grade_level.level_type != 'SHS':
        flash('Strands can only be added to Senior High School grade levels (Grade 11 or Grade 12), or grade level not found/permission denied.', 'danger')
        return redirect(url_for('student_dashboard'))

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

            new_strand = Strand(name=strand_name, grade_level_id=grade_level_id, created_by=student_admin_id)
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
@user_type_required('student')
def edit_strand(strand_id):
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])

    strand = db_session.query(Strand).options(joinedload(Strand.grade_level)).filter_by(id=strand_id, created_by=student_admin_id).first()
    if not strand:
        flash('Strand not found or you do not have permission to edit it.', 'danger')
        return redirect(url_for('student_dashboard'))

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
@user_type_required('student')
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
@user_type_required('student')
def strand_details(strand_id):
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])

    strand = db_session.query(Strand).options(joinedload(Strand.grade_level)).filter_by(id=strand_id, created_by=student_admin_id).first()
    if not strand:
        flash('Strand not found or you do not have permission to view it.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    sections = db_session.query(Section).filter_by(strand_id=strand_id, grade_level_id=strand.grade_level.id).order_by(Section.name).all()

    return render_template('strand_details.html',
                           strand=strand,
                           sections=sections)


# MODIFIED: add_section now explicitly tied to a strand_id for SHS, or grade_level_id for JHS
@app.route('/add_section/<uuid:parent_id>/<string:parent_type>', methods=['GET', 'POST'])
@login_required
@user_type_required('student')
def add_section(parent_id, parent_type):
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])
    
    grade_level = None
    strand = None

    if parent_type == 'grade_level': # For JHS sections
        grade_level = db_session.query(GradeLevel).filter_by(id=parent_id, created_by=student_admin_id).first()
        if not grade_level:
            flash('Grade Level not found or you do not have permission.', 'danger')
            return redirect(url_for('student_dashboard'))
        if grade_level.level_type == 'SHS':
            flash('Sections for Senior High School must be added under a specific Strand. Please select a Strand first.', 'danger')
            return redirect(url_for('grade_level_details', grade_level_id=grade_level.id))
    elif parent_type == 'strand': # For SHS sections
        strand = db_session.query(Strand).options(joinedload(Strand.grade_level)).filter_by(id=parent_id, created_by=student_admin_id).first()
        if not strand:
            flash('Strand not found or you do not have permission.', 'danger')
            return redirect(url_for('student_dashboard'))
        grade_level = strand.grade_level
    else:
        flash('Invalid parent type for adding a section.', 'danger')
        return redirect(url_for('student_dashboard'))

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
                created_by=student_admin_id
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
@user_type_required('student')
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
    
    redirect_url_after_delete = url_for('student_dashboard') # Default fallback

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
@user_type_required('student')
def section_details(section_id):
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])

    section_obj = db_session.query(Section).options(
        joinedload(Section.grade_level),
        joinedload(Section.strand) # Load strand if it exists
    ).filter(Section.id==section_id).first()
    
    if not section_obj or section_obj.created_by != student_admin_id:
        flash('Section not found or you do not have permission to view it.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    period_type = 'Semester' if section_obj.grade_level.level_type == 'SHS' else 'Quarter'
    period_names = PERIOD_TYPES[section_obj.grade_level.level_type]
    school_years = get_school_year_options()

    # Get section periods for this specific section (strand is now part of the section definition)
    section_periods_query = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section), # Already loaded, but good practice
        joinedload(SectionPeriod.assigned_teacher) # Load assigned teacher for display
    ).filter_by(section_id=section_id)

    section_periods = section_periods_query.order_by(
        SectionPeriod.school_year.desc(), 
        SectionPeriod.period_name
    ).all()

    return render_template('section_details.html',
                           section=section_obj,
                           period_type=period_type,
                           period_names=period_names,
                           school_years=school_years,
                           section_periods=section_periods)


@app.route('/section/<uuid:section_id>/add_period', methods=['GET', 'POST'])
@login_required
@user_type_required('student')
def add_section_period(section_id): # Renamed from add_section_semester
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])

    section = db_session.query(Section).options(
        joinedload(Section.grade_level),
        joinedload(Section.strand) # Load the strand info for this section
    ).filter_by(id=section_id).first()
    if not section or section.created_by != student_admin_id:
        flash('Section not found or you do not have permission to add periods to it.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    period_type = 'Semester' if section.grade_level.level_type == 'SHS' else 'Quarter'
    period_names = PERIOD_TYPES[section.grade_level.level_type]
    school_years = get_school_year_options()

    print(f"\n--- Debugging add_section_period for Section: {section.name} (ID: {section.id}) ---")
    print(f"  Section Grade Level: '{section.grade_level.name}' (Type: {section.grade_level.level_type})")
    print(f"  Section Strand: '{section.strand.name if section.strand else 'N/A'}'")
    print(f"  Expected Period Type: '{period_type}'")

    # For teacher assignment logic:
    # If SHS, teacher needs to match grade_level_assigned and specialization (which is the strand name)
    # If JHS, teacher needs to match grade_level_assigned and specialization=None
    
    teacher_filter_conditions = [
        User.user_type == 'teacher',
        User.grade_level_assigned == section.grade_level.name
    ]

    if section.grade_level.level_type == 'SHS':
        if not section.strand: # This shouldn't happen if validation was correct, but for safety
            print("  ERROR: SHS Section has no assigned strand. Cannot determine teacher specialization match.")
            flash('Section has no assigned strand. Cannot add periods.', 'error')
            return redirect(url_for('section_details', section_id=section.id))
        teacher_filter_conditions.append(User.specialization == section.strand.name)
        print(f"  Teacher lookup criteria (SHS): Grade Level='{section.grade_level.name}', Specialization='{section.strand.name}'")
    else: # JHS
        teacher_filter_conditions.append(User.specialization == None)
        print(f"  Teacher lookup criteria (JHS): Grade Level='{section.grade_level.name}', Specialization=None")

    assigned_teacher_account = db_session.query(User).filter(
        *teacher_filter_conditions
    ).first()

    assigned_teacher_id = None
    if assigned_teacher_account:
        assigned_teacher_id = assigned_teacher_account.id
        print(f"  SUITABLE TEACHER FOUND: Username='{assigned_teacher_account.username}', ID='{assigned_teacher_id}'")
    else:
        specialization_info = f" with '{section.strand.name}' specialization" if section.strand else " (Junior High School General Education)"
        flash_message_no_teacher = f'No appropriate teacher account found for {section.grade_level.name} {specialization_info}. You can still add this {period_type.lower()}, but a teacher will need to be registered and assigned later to manage it.'
        flash(flash_message_no_teacher, 'warning')
        print(f"  WARNING: {flash_message_no_teacher}")


    if request.method == 'POST':
        period_name = request.form['period_name'].strip()
        school_year = request.form['school_year'].strip()

        print(f"\n--- POST Request for add_section_period ---")
        print(f"  Form Data: Period Name='{period_name}', School Year='{school_year}'")
        print(f"  Assigned Teacher ID for new Period (will be saved): {assigned_teacher_id}")

        if not period_name or not school_year:
            flash(f'{period_type} and School Year are required.', 'error')
            return render_template('add_section_period.html', 
                                   section=section, 
                                   period_type=period_type, 
                                   period_names=period_names, 
                                   school_years=school_years)

        if not re.fullmatch(r'\d{4}-\d{4}', school_year):
            flash('Invalid School Year format. Please use XXXX-YYYY (e.g., 2025-2026).', 'error')
            return render_template('add_section_period.html', 
                                   section=section, 
                                   period_type=period_type, 
                                   period_names=period_names, 
                                   school_years=school_years)
        
        try:
            # Check for existing period (unique constraint on section_id, period_name, school_year)
            existing_period = db_session.query(SectionPeriod).filter(
                SectionPeriod.section_id == section_id,
                func.lower(SectionPeriod.period_name) == func.lower(period_name),
                SectionPeriod.school_year == school_year
            ).first()

            if existing_period:
                flash(f'{period_name} for {school_year} already exists in this section.', 'error')
                return render_template('add_section_period.html', 
                                       section=section, 
                                       period_type=period_type, 
                                       period_names=period_names, 
                                       school_years=school_years)

            new_section_period = SectionPeriod(
                section_id=section_id,
                period_type=period_type,
                period_name=period_name,
                school_year=school_year,
                assigned_teacher_id=assigned_teacher_id, # This will be None if no teacher was found
                created_by_admin=student_admin_id
            )
            db_session.add(new_section_period)
            db_session.commit()
            
            success_message = f'{period_name} for {school_year} added to {section.name} successfully!'
            if assigned_teacher_account:
                success_message += f' It has been assigned to {assigned_teacher_account.username}.'
            else:
                success_message += ' No teacher was automatically assigned. An admin can assign one later.'

            flash(success_message, 'success')
            return redirect(url_for('section_details', section_id=section.id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error adding section period: {e}", exc_info=True)
            flash('An error occurred while adding the period. Please try again.', 'error')
            return render_template('add_section_period.html', 
                                   section=section, 
                                   period_type=period_type, 
                                   period_names=period_names, 
                                   school_years=school_years)

    return render_template('add_section_period.html', 
                           section=section, 
                           period_type=period_type, 
                           period_names=period_names, 
                           school_years=school_years)



@app.route('/section_period/<uuid:section_period_id>/delete', methods=['POST'])
@login_required
@user_type_required('student')
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
    
    redirect_url_after_delete = url_for('student_dashboard') # Default fallback

    if section_period_to_delete.section.strand_id: # If section belonged to a strand (SHS)
        redirect_url_after_delete = url_for('strand_details', strand_id=section_period_to_delete.section.strand_id)
    elif section_period_to_delete.section.grade_level_id: # If section belonged directly to a grade level (JHS)
        redirect_url_after_delete = url_for('section_details', section_id=section_period_to_delete.section.id) # Corrected: go to section details
    

    try:
        db_session.delete(section_period_to_delete)
        db_session.commit()
        period_info = f"{section_period_to_delete.period_name} {section_period_to_delete.school_year}"
        if section_period_to_delete.section.strand: # Check strand via section
            period_info += f" ({section_period_to_delete.section.strand.name})"
        return jsonify({'success': True, 'message': f'Period "{period_info}" and all its associated students, subjects, attendance, and grades have been deleted.', 'redirect_url': redirect_url_after_delete})
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting section period: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred while deleting the period.'})


@app.route('/section_period/<uuid:section_period_id>')
@login_required
@user_type_required('student')
def section_period_details(section_period_id): # Renamed from section_semester_details
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])

    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand), # Load strand via section
        joinedload(SectionPeriod.assigned_teacher)
    ).filter(SectionPeriod.id==section_period_id).first()

    if not section_period or section_period.created_by_admin != student_admin_id:
        flash('Period details not found or you do not have permission to view it.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    students = db_session.query(StudentInfo).filter_by(section_period_id=section_period_id).order_by(StudentInfo.name).all()
    
    return render_template('section_period_details.html',
                           section_period=section_period,
                           students=students)


@app.route('/section_period/<uuid:section_period_id>/add_student', methods=['GET', 'POST'])
@login_required
@user_type_required('student')
def add_student_to_section_period(section_period_id): # Renamed from add_student_to_section_semester
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])

    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand) # Load strand via section
    ).filter(SectionPeriod.id==section_period_id).first()

    if not section_period or section_period.created_by_admin != student_admin_id:
        flash('Period not found or you do not have permission to add students to it.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    if request.method == 'POST':
        student_name = request.form['name'].strip()
        student_id_number = request.form['student_id_number'].strip()

        if not student_name or not student_id_number:
            flash('Student name and ID number are required.', 'error')
            return render_template('add_student_to_section_period.html', section_period=section_period)

        try:
            existing_student_by_id = db_session.query(StudentInfo).filter_by(student_id_number=student_id_number).first()
            if existing_student_by_id:
                flash(f'Student with ID Number "{student_id_number}" already exists.', 'error')
                return render_template('add_student_to_section_period.html', section_period=section_period)

            new_student = StudentInfo(
                section_period_id=section_period_id,
                name=student_name,
                student_id_number=student_id_number
            )
            db_session.add(new_student)
            db_session.commit()
            period_info = f"{section_period.period_name} {section_period.school_year}"
            if section_period.section.strand: # Check strand via section
                period_info += f" ({section_period.section.strand.name})"
            flash(f'Student "{student_name}" added to {section_period.section.name} ({period_info}) successfully!', 'success')
            return redirect(url_for('section_period_details', section_period_id=section_period_id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error adding student: {e}")
            flash('An error occurred while adding the student. Please try again.', 'error')

    return render_template('add_student_to_section_period.html', section_period=section_period)

# --- Student Admin: Reassign Teachers to Periods ---
# --- Student Admin: Reassign Teachers to Periods ---
@app.route('/admin/reassign_period_teachers', methods=['POST'])
@login_required
@user_type_required('student')
def reassign_period_teachers():
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])
    password = request.form.get('password') # Require password for sensitive operation

    if not password or not verify_current_user_password(student_admin_id, password):
        return jsonify({'success': False, 'message': 'Incorrect password. Assignment aborted.'})

    print(f"\n--- Admin Triggered Teacher Reassignment ---")
    
    assigned_count = 0
    updated_periods = []

    try:
        # Find all section periods created by this admin that currently have no assigned teacher
        unassigned_periods = db_session.query(SectionPeriod).options(
            joinedload(SectionPeriod.section).joinedload(Section.grade_level),
            joinedload(SectionPeriod.section).joinedload(Section.strand)
        ).filter(
            SectionPeriod.created_by_admin == student_admin_id,
            SectionPeriod.assigned_teacher_id == None # Find periods without an assigned teacher
        ).all()

        print(f"Found {len(unassigned_periods)} unassigned periods created by this admin.")

        for period in unassigned_periods:
            print(f"  Processing unassigned period: '{period.period_name} {period.school_year}' for section '{period.section.name}'")
            
            teacher_filter_conditions = [
                User.user_type == 'teacher',
                User.grade_level_assigned == period.section.grade_level.name
            ]

            if period.section.grade_level.level_type == 'SHS':
                if not period.section.strand:
                    print(f"    WARNING: SHS Period '{period.period_name}' in section '{period.section.name}' has no associated strand. Cannot find matching teacher specialization.")
                    continue # Skip this period if SHS but no strand
                teacher_filter_conditions.append(User.specialization == period.section.strand.name)
                print(f"    Looking for teacher: Grade Level='{period.section.grade_level.name}', Specialization='{period.section.strand.name}'")
            else: # JHS
                teacher_filter_conditions.append(User.specialization == None)
                print(f"    Looking for teacher (JHS): Grade Level='{period.section.grade_level.name}', Specialization=None")

            suitable_teacher = db_session.query(User).filter(*teacher_filter_conditions).first()

            if suitable_teacher:
                period.assigned_teacher_id = suitable_teacher.id
                db_session.add(period) # Mark for update
                assigned_count += 1
                updated_periods.append(f"{period.section.name} - {period.period_name} {period.school_year}")
                print(f"    -> Successfully assigned '{suitable_teacher.username}' to period '{period.period_name} {period.school_year}'.")
            else:
                print(f"    -> No suitable teacher found for period '{period.period_name} {period.school_year}'.")
        
        db_session.commit()
        if assigned_count > 0:
            message = f"Successfully assigned {assigned_count} teachers to periods: {', '.join(updated_periods)}."
            flash(message, 'success')
            print(f"SUCCESS: {message}")
        else:
            message = "No unassigned periods found or no suitable teachers available for assignment."
            flash(message, 'info')
            print(f"INFO: {message}")
        
        return jsonify({'success': True, 'message': message, 'redirect_url': url_for('student_dashboard')})

    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error during teacher reassignment: {e}", exc_info=True)
        message = 'An error occurred during teacher reassignment. Please try again.'
        flash(message, 'danger')
        return jsonify({'success': False, 'message': message})







@app.route('/student/<uuid:student_id>/delete_admin', methods=['POST'])
@login_required
@user_type_required('student')
def delete_student_admin(student_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    password = request.form.get('password')

    if not password or not verify_current_user_password(user_id, password):
        return jsonify({'success': False, 'message': 'Incorrect password.'})

    student_to_delete = db_session.query(StudentInfo).options(
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.strand) # Load strand via section
    ).filter_by(id=student_id).first()

    if not student_to_delete:
        return jsonify({'success': False, 'message': 'Student not found.'})

    if not student_to_delete.section_period or student_to_delete.section_period.created_by_admin != user_id:
        return jsonify({'success': False, 'message': 'You do not have permission to delete this student.'})
    
    redirect_url_after_delete = url_for('student_dashboard') # Default fallback
    if student_to_delete.section_period:
        redirect_url_after_delete = url_for('section_period_details', section_period_id=student_to_delete.section_period.id)


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
@user_type_required('student')
def edit_student(student_id):
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])
    
    student_to_edit = db_session.query(StudentInfo).options(
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.strand)
    ).filter_by(id=student_id).first()

    if not student_to_edit:
        flash('Student not found.', 'danger')
        return redirect(url_for('student_dashboard')) 

    # Fetch all section periods manageable by this admin for the dropdown
    # Corrected ORDER BY clause to avoid DatatypeMismatch error
    section_periods_for_dropdown = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand) # Load strand via section
    ).filter_by(created_by_admin=student_admin_id).order_by(
        SectionPeriod.school_year.desc(), 
        SectionPeriod.period_name, 
        # Corrected ordering: Directly use columns from joined tables
        Section.name.asc(),  # Order by section name
        Strand.name.asc().nulls_first() # Order by strand name, putting None (JHS) first
    ).join(Section).outerjoin(Strand).all() # Ensure joins are explicit for ordering

    current_period_manageable = any(str(s.id) == str(student_to_edit.section_period_id) for s in section_periods_for_dropdown)
    if not current_period_manageable:
         flash('You do not have permission to edit this student.', 'danger')
         if student_to_edit and student_to_edit.section_period_id:
             return redirect(url_for('section_period_details', section_period_id=student_to_edit.section_period_id))
         return redirect(url_for('student_dashboard'))


    if request.method == 'POST':
        student_name = request.form['name'].strip()
        student_id_number = request.form['student_id_number'].strip()
        new_section_period_id_str = request.form.get('section_period_id')

        if not student_name or not student_id_number or not new_section_period_id_str:
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

            db_session.commit()
            flash(f'Student "{student_name}" updated successfully!', 'success')
            return redirect(url_for('section_period_details', section_period_id=student_to_edit.section_period.id))
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
    teacher_specialization = session.get('specialization') # This will be None for JHS teachers
    teacher_grade_level = session.get('grade_level_assigned')
    teacher_id = uuid.UUID(session['user_id'])
    
    print(f"\n--- Teacher Dashboard Debugging for User: {session.get('username')} (ID: {teacher_id}) ---")
    print(f"Logged-in Teacher Specialization (from session): '{teacher_specialization}'")
    print(f"Logged-in Teacher Grade Level Assigned (from session): '{teacher_grade_level}'")

    # Get the GradeLevel object for the teacher's assigned grade
    assigned_grade_level_obj = db_session.query(GradeLevel).filter_by(name=teacher_grade_level).first()
    if not assigned_grade_level_obj:
        print(f"ERROR: Assigned grade level '{teacher_grade_level}' not found for logged-in teacher. Logging out.")
        flash("Assigned grade level not found for your account. Please contact an admin.", "danger")
        session.clear() # Log out user if their assigned grade level is invalid
        return redirect(url_for('login'))
    print(f"Assigned Grade Level Object found from DB: {assigned_grade_level_obj.name} (Type: {assigned_grade_level_obj.level_type})")

    # Fetch ALL sections that match the teacher's grade level and specialization (if SHS)
    sections_query = db_session.query(Section).options(
        joinedload(Section.grade_level),
        joinedload(Section.strand), # Load strand for SHS sections
        joinedload(Section.section_periods).joinedload(SectionPeriod.assigned_teacher) # Load assigned teacher for periods
    ).filter(Section.grade_level_id == assigned_grade_level_obj.id)

    if assigned_grade_level_obj.level_type == 'SHS':
        # For SHS, only consider sections that have a strand matching the teacher's specialization
        sections_query = sections_query.filter(Section.strand.has(Strand.name == teacher_specialization))
    else: # JHS
        # For JHS, only consider sections that DO NOT have a strand assigned
        sections_query = sections_query.filter(Section.strand_id == None)

    sections = sections_query.order_by(Section.name).all()
    print(f"Initially fetched {len(sections)} sections matching teacher's grade level/specialization criteria from DB.")

    sections_with_averages_and_periods = []
    for section in sections:
        print(f"\n--- Processing Section: '{section.name}' (ID: {section.id}) ---")
        print(f"  Section Grade Level: '{section.grade_level.name}' (Type: {section.grade_level.level_type}), Section Strand: '{section.strand.name if section.strand else 'N/A'}'")
        
        relevant_periods_for_this_section = []
        
        # Iterate through ALL periods associated with this section (loaded via joinedload)
        if not section.section_periods:
            print(f"  No section_periods found for section '{section.name}' in the database relationship. Skipping period processing.")
            continue

        for sp in section.section_periods:
            print(f"    Evaluating Period: '{sp.period_name} {sp.school_year}' (ID: {sp.id}, Type: '{sp.period_type}')")
            print(f"      Period Assigned Teacher ID (DB): {sp.assigned_teacher_id}")
            print(f"      Logged-in Teacher ID (Session): {teacher_id}")

            is_assigned_teacher_match = (sp.assigned_teacher_id and str(sp.assigned_teacher_id) == str(teacher_id))
            print(f"      Comparison (str(DB ID) == str(Session ID)): {is_assigned_teacher_match}")

            is_correct_period_type = False
            if assigned_grade_level_obj.level_type == 'SHS' and sp.period_type == 'Semester':
                is_correct_period_type = True
            elif assigned_grade_level_obj.level_type == 'JHS' and sp.period_type == 'Quarter':
                is_correct_period_type = True
            print(f"      Is Correct Period Type ('{sp.period_type}' vs Expected '{assigned_grade_level_obj.level_type}'-period): {is_correct_period_type}")


            if is_assigned_teacher_match and is_correct_period_type:
                relevant_periods_for_this_section.append(sp)
                print(f"      -> Period '{sp.period_name} {sp.school_year}' INCLUDED for this teacher.")
            else:
                print(f"      -> Period '{sp.period_name} {sp.school_year}' EXCLUDED for this teacher.")

        # Only add the section to the dashboard view if it contains periods relevant to this teacher
        if not relevant_periods_for_this_section:
            print(f"  No relevant periods found for logged-in teacher in section '{section.name}'. Skipping section display on dashboard.")
            continue

        print(f"  Found {len(relevant_periods_for_this_section)} relevant periods for this teacher in section '{section.name}'.")

        # Calculate overall average grades for each section
        total_grades_sum = 0
        total_grades_count = 0

        student_ids_in_relevant_periods = db_session.query(StudentInfo.id).filter(
            StudentInfo.section_period_id.in_([p.id for p in relevant_periods_for_this_section])
        ).all()
        student_ids_in_relevant_periods = [s.id for s in student_ids_in_relevant_periods]

        if student_ids_in_relevant_periods:
            print(f"  Processing grades for {len(student_ids_in_relevant_periods)} students in relevant periods.")
            all_grades_summary = db_session.query(func.sum(Grade.grade_value), func.count(Grade.grade_value)).\
                         join(SectionSubject).\
                         join(StudentInfo).\
                         filter(
                             Grade.student_info_id.in_(student_ids_in_relevant_periods),
                             Grade.teacher_id == teacher_id, # Only sum grades entered by THIS teacher account
                             SectionSubject.section_period_id.in_([p.id for p in relevant_periods_for_this_section])
                         ).\
                         one_or_none() 

            if all_grades_summary and all_grades_summary[0] is not None and all_grades_summary[1] > 0:
                total_grades_sum = float(all_grades_summary[0])
                total_grades_count = all_grades_summary[1]
                print(f"  Calculated total grades sum: {total_grades_sum}, count: {total_grades_count}")
            else:
                print(f"  No grades found by this teacher for students in relevant periods.")
        else:
            print("  No students found in relevant periods for this section.")

        section_average = round(total_grades_sum / total_grades_count, 2) if total_grades_count > 0 else 'N/A'
        print(f"  Overall Section Average Grade (by this teacher): {section_average}")
        
        sections_with_averages_and_periods.append({
            'id': str(section.id),
            'name': section.name,
            'grade_level_name': section.grade_level.name,
            'type': section.grade_level.level_type,
            'strand_name': section.strand.name if section.strand else None,
            'average_grade': section_average,
            'periods': relevant_periods_for_this_section
        })

    display_specialization_text = teacher_specialization if teacher_specialization else "General Education"
    display_specialization_suffix = f"({display_specialization_text} Teacher)"

    print(f"--- End Teacher Dashboard Debugging ---")

    return render_template('teacher_dashboard.html', 
                           sections=sections_with_averages_and_periods, 
                           teacher_specialization=display_specialization_suffix, 
                           teacher_grade_level=teacher_grade_level)





@app.route('/teacher/section_period/<uuid:section_period_id>')
@login_required
@user_type_required('teacher')
def teacher_section_period_view(section_period_id): # Renamed from teacher_section_semester_view
    db_session = g.session
    teacher_specialization = session.get('specialization') # None for JHS
    teacher_grade_level = session.get('grade_level_assigned')
    teacher_id = uuid.UUID(session['user_id'])

    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand), # Load strand via section
        joinedload(SectionPeriod.assigned_teacher) # Load the assigned teacher for this period
    ).filter_by(id=section_period_id).first()

    if not section_period:
        flash('Period not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    # Permission check: Teacher can view this period if:
    # 1. It belongs to their assigned grade level.
    # 2. They are the assigned teacher for this specific period (if assigned_teacher_id is not null).
    # 3. (For SHS only) The section's strand matches their specialization.
    
    # 1. Check grade level
    if section_period.section.grade_level.name != teacher_grade_level:
        flash('You do not have permission to view details for this period (incorrect grade level).', 'danger')
        return redirect(url_for('teacher_dashboard'))

    # 2. Check if logged-in teacher is the assigned teacher for this specific period
    if section_period.assigned_teacher_id and str(section_period.assigned_teacher_id) != str(teacher_id):
        flash('You are not the assigned teacher for this period.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    # 3. For SHS, check section's strand match with teacher's specialization
    if section_period.section.grade_level.level_type == 'SHS':
        if not section_period.section.strand or section_period.section.strand.name != teacher_specialization:
             flash('You do not have permission to view details for this period (incorrect strand for your specialization).', 'danger')
             return redirect(url_for('teacher_dashboard'))
    elif section_period.section.grade_level.level_type == 'JHS':
        # For JHS, ensure the section does NOT have a strand assigned (should be NULL)
        if section_period.section.strand_id is not None:
             flash('You do not have permission to view details for this period (JHS section incorrectly assigned to a strand).', 'danger')
             return redirect(url_for('teacher_dashboard'))


    students = db_session.query(StudentInfo).filter_by(section_period_id=section_period_id).order_by(StudentInfo.name).all()

    # Fetch all subjects associated with this specific section_period
    # No longer filtering by assigned_teacher_for_subject_id here, as this teacher account manages the whole period
    section_subjects = db_session.query(SectionSubject).filter(
        SectionSubject.section_period_id == section_period_id
    ).order_by(SectionSubject.subject_name).all()
    
    # Calculate average grade for each student, considering only grades entered by the logged-in teacher for subjects within this period
    students_with_averages = []
    for student in students:
        # Sum grades only for subjects where THIS teacher is assigned to teach and for which they assigned grades
        student_grades_sum = db_session.query(func.sum(Grade.grade_value)).join(SectionSubject).filter(
            Grade.student_info_id == student.id,
            Grade.teacher_id == teacher_id, # Only sum grades entered by THIS teacher account
            SectionSubject.section_period_id == section_period_id
        ).scalar()

        student_grades_count = db_session.query(func.count(Grade.grade_value)).join(SectionSubject).filter(
            Grade.student_info_id == student.id,
            Grade.teacher_id == teacher_id,
            SectionSubject.section_period_id == section_period_id
        ).scalar()

        if student_grades_sum is not None and student_grades_count and student_grades_count > 0:
            average_grade = round(float(student_grades_sum) / student_grades_count, 2)
        else:
            average_grade = 'N/A'
        
        students_with_averages.append({
            'id': str(student.id),
            'name': student.name,
            'student_id_number': student.student_id_number,
            'average_grade': average_grade,
            'section_name': section_period.section.name,
            'period_info': f"{section_period.period_name} {section_period.school_year}",
            'section_period_id': str(section_period_id)
        })

    return render_template('teacher_section_period_details.html', # New template for teachers
                           section_period=section_period, # Pass the specific period object
                           students=students_with_averages,
                           section_subjects=section_subjects) # Pass all section_subjects for this period

@app.route('/teacher/section_period/<uuid:section_period_id>/add_subject', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher')
def add_subject_to_section_period(section_period_id):
    db_session = g.session
    current_teacher_id = uuid.UUID(session['user_id']) # The teacher account who is logged in and adding the subject
    teacher_specialization = session.get('specialization')
    teacher_grade_level = session.get('grade_level_assigned')

    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand),
        joinedload(SectionPeriod.assigned_teacher)
    ).filter_by(id=section_period_id).first()
    
    if not section_period:
        flash('Period not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    # Permission check for the logged-in teacher to add subjects to this period
    if section_period.section.grade_level.name != teacher_grade_level or \
       (section_period.assigned_teacher_id and str(section_period.assigned_teacher_id) != str(current_teacher_id)) :
        flash('You do not have permission to add subjects to this period.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    if section_period.section.grade_level.level_type == 'SHS':
        if not section_period.section.strand or section_period.section.strand.name != teacher_specialization:
            flash('You do not have permission to add subjects to this period (incorrect strand).', 'danger')
            return redirect(url_for('teacher_dashboard'))
    elif section_period.section.grade_level.level_type == 'JHS':
        if section_period.section.strand_id is not None:
             flash('You do not have permission to add subjects to this period (JHS period incorrectly assigned to a strand).', 'danger')
             return redirect(url_for('teacher_dashboard'))

    if request.method == 'POST':
        subject_name = request.form['subject_name'].strip()
        assigned_teacher_name = request.form['assigned_teacher_name'].strip() # Get the text input

        if not subject_name or not assigned_teacher_name:
            flash('Subject name and assigned teacher name are required.', 'error')
            return render_template('add_section_subject.html', section_period=section_period)
        
        try:
            existing_section_subject = db_session.query(SectionSubject).filter(
                SectionSubject.section_period_id == section_period_id,
                func.lower(SectionSubject.subject_name) == func.lower(subject_name)
            ).first()
            if existing_section_subject:
                flash(f'Subject "{subject_name}" already exists for this period.', 'error')
                return render_template('add_section_subject.html', section_period=section_period)

            new_section_subject = SectionSubject(
                section_period_id=section_period_id,
                subject_name=subject_name,
                created_by_teacher_id=current_teacher_id, # Logged-in teacher account created this record
                assigned_teacher_name=assigned_teacher_name # Store the free-text name
            )
            db_session.add(new_section_subject)
            db_session.commit()
            flash(f'Subject "{subject_name}" added to {section_period.period_name} {section_period.school_year} and assigned!', 'success')
            return redirect(url_for('teacher_section_period_view', section_period_id=section_period_id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error adding subject to section period: {e}")
            flash('An error occurred while adding the subject. Please try again.', 'error')

    return render_template('add_section_subject.html', section_period=section_period)


@app.route('/teacher/section_period/<uuid:section_period_id>/subject/<uuid:subject_id>/delete', methods=['POST'])
@login_required
@user_type_required('teacher')
def delete_section_subject(section_period_id, subject_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id']) # Logged-in teacher
    password = request.form.get('password')

    if not password or not verify_current_user_password(user_id, password):
        return jsonify({'success': False, 'message': 'Incorrect password.'})

    teacher_specialization = session.get('specialization')
    teacher_grade_level = session.get('grade_level_assigned')

    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand), # Load strand via section
        joinedload(SectionPeriod.assigned_teacher)
    ).filter_by(id=section_period_id).first()
    
    if not section_period:
        return jsonify({'success': False, 'message': 'Period not found.'})
    
    # Permission check for the logged-in teacher to delete subjects from this period
    # This is now based on the period's assigned_teacher_id matching the logged-in user
    if section_period.section.grade_level.name != teacher_grade_level or \
       (section_period.assigned_teacher_id and str(section_period.assigned_teacher_id) != str(user_id)) :
        return jsonify({'success': False, 'message': 'You do not have permission to delete subjects from this period.'})

    if section_period.section.grade_level.level_type == 'SHS':
        if not section_period.section.strand or section_period.section.strand.name != teacher_specialization:
            return jsonify({'success': False, 'message': 'You do not have permission to delete subjects from this period (incorrect strand).'})
    elif section_period.section.grade_level.level_type == 'JHS':
        if section_period.section.strand_id is not None:
             return jsonify({'success': False, 'message': 'You do not have permission to delete subjects from this period (JHS period incorrectly assigned to a strand).'})
    
    # Fetch the SectionSubject ensuring it belongs to this period
    # No longer filtering by assigned_teacher_for_subject_id == user_id, as the logged-in teacher (e.g., g12ict) can delete any subject in their managed period
    subject_to_delete = db_session.query(SectionSubject).filter(
        SectionSubject.id == subject_id,
        SectionSubject.section_period_id == section_period_id
    ).first()

    if not subject_to_delete:
        return jsonify({'success': False, 'message': 'Subject not found.'})

    try:
        db_session.delete(subject_to_delete)
        db_session.commit()
        return jsonify({'success': True, 'message': f'Subject "{subject_to_delete.subject_name}" has been deleted from its associated period (and its associated grades).'})
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting subject: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred while deleting the subject.'})


@app.route('/teacher/section/<uuid:section_id>/delete', methods=['POST'])
@login_required
@user_type_required('teacher')
def delete_teacher_section(section_id):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    password = request.form.get('password')

    if not password or not verify_current_user_password(user_id, password):
        return jsonify({'success': False, 'message': 'Incorrect password.'})

    teacher_specialization = session.get('specialization')
    teacher_grade_level = session.get('grade_level_assigned')
    
    section_to_delete = db_session.query(Section).options(joinedload(Section.grade_level), joinedload(Section.strand)).filter_by(id=section_id).first()

    if not section_to_delete:
        return jsonify({'success': False, 'message': 'Section not found.'})
    
    # A teacher can only delete a section if:
    # 1. The section belongs to their assigned grade level.
    # 2. They are the assigned teacher for *all* periods within that section (if any exist)
    #    OR, if there are no periods, it's an empty section.
    # 3. (For SHS) Their specialization matches the section's strand.
    # 4. (For JHS) The section has NULL strand_id.
    
    # 1. Check grade level
    if section_to_delete.grade_level.name != teacher_grade_level:
        return jsonify({'success': False, 'message': 'You do not have permission to delete this section (incorrect grade level).'})

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
    password = request.form.get('password')

    if not password or not verify_current_user_password(user_id, password):
        return jsonify({'success': False, 'message': 'Incorrect password.'})

    teacher_specialization = session.get('specialization')
    teacher_grade_level = session.get('grade_level_assigned')

    student_to_delete = db_session.query(StudentInfo).options(
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(StudentInfo.section_period).joinedload(SectionPeriod.section).joinedload(Section.strand) # Load strand via section
    ).filter_by(id=student_id).first()

    if not student_to_delete:
        return jsonify({'success': False, 'message': 'Student not found.'})
    
    # Permission check for deleting student by teacher
    if student_to_delete.section_period.section.grade_level.name != teacher_grade_level or \
       (student_to_delete.section_period.assigned_teacher_id and str(student_to_delete.section_period.assigned_teacher_id) != str(user_id)):
        return jsonify({'success': False, 'message': 'You do not have permission to delete this student.'})
    
    if student_to_delete.section_period.section.grade_level.level_type == 'SHS':
        if not student_to_delete.section_period.section.strand or student_to_delete.section_period.section.strand.name != teacher_specialization:
            return jsonify({'success': False, 'message': 'You do not have permission to delete this student (incorrect strand).'})
    elif student_to_delete.section_period.section.grade_level.level_type == 'JHS':
        if student_to_delete.section_period.section.strand_id is not None:
             return jsonify({'success': False, 'message': 'You do not have permission to delete this student (JHS student incorrectly assigned to a strand).'})

    try:
        db_session.delete(student_to_delete)
        db_session.commit()
        return jsonify({'success': True, 'message': f'Student "{student_to_delete.name}" has been deleted from section "{student_to_delete.section_period.section.name}".'})
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting student: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while deleting the student.'})


@app.route('/teacher/section_period/<uuid:section_period_id>/add_grades/<uuid:student_id>', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher')
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


@app.route('/teacher/section_period/<uuid:section_period_id>/attendance_dates')
@login_required
@user_type_required('teacher')
def teacher_section_attendance_dates(section_period_id):
    db_session = g.session
    teacher_specialization = session.get('specialization')
    teacher_grade_level = session.get('grade_level_assigned')
    teacher_id = uuid.UUID(session['user_id'])

    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand) # Load strand via section
    ).filter_by(id=section_period_id).first()
    
    if not section_period:
        flash('Period not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    # Permission check (same as teacher_section_period_view)
    if section_period.section.grade_level.name != teacher_grade_level or \
       (section_period.assigned_teacher_id and str(section_period.assigned_teacher_id) != str(teacher_id)) :
        flash('You do not have permission to manage attendance for this period.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    if section_period.section.grade_level.level_type == 'SHS':
        if not section_period.section.strand or section_period.section.strand.name != teacher_specialization:
            flash('You do not have permission to manage attendance for this period (incorrect strand).', 'danger')
            return redirect(url_for('teacher_dashboard'))
    elif section_period.section.grade_level.level_type == 'JHS':
        if section_period.section.strand_id is not None:
             flash('You do not have permission to manage attendance for this period (JHS period incorrectly assigned to a strand).', 'danger')
             return redirect(url_for('teacher_dashboard'))


    # Get all unique attendance dates for students in this specific section_period, recorded by this teacher account
    attendance_dates = db_session.query(Attendance.attendance_date).\
                        join(StudentInfo).\
                        filter(
                            StudentInfo.section_period_id == section_period_id,
                            Attendance.recorded_by == teacher_id # Only show dates recorded by this specific teacher account
                        ).\
                        distinct(Attendance.attendance_date).\
                        order_by(Attendance.attendance_date.desc()).\
                        all()
    
    dates_list = [d[0] for d in attendance_dates]

    return render_template('teacher_attendance_dates.html',
                           section_period=section_period,
                           attendance_dates=dates_list)


@app.route('/teacher/section_period/<uuid:section_period_id>/attendance_details', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher')
def teacher_section_attendance_details(section_period_id):
    db_session = g.session
    teacher_id = uuid.UUID(session['user_id'])
    teacher_specialization = session.get('specialization')
    teacher_grade_level = session.get('grade_level_assigned')

    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand) # Load strand via section
    ).filter_by(id=section_period_id).first()
    
    if not section_period:
        flash('Period not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    # Permission check (same as teacher_section_period_view)
    if section_period.section.grade_level.name != teacher_grade_level or \
       (section_period.assigned_teacher_id and str(section_period.assigned_teacher_id) != str(teacher_id)) :
        flash('You do not have permission to manage attendance for this period.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    if section_period.section.grade_level.level_type == 'SHS':
        if not section_period.section.strand or section_period.section.strand.name != teacher_specialization:
            flash('You do not have permission to manage attendance for this period (incorrect strand).', 'danger')
            return redirect(url_for('teacher_dashboard'))
    elif section_period.section.grade_level.level_type == 'JHS':
        if section_period.section.strand_id is not None:
             flash('You do not have permission to manage attendance for this period (JHS period incorrectly assigned to a strand).', 'danger')
             return redirect(url_for('teacher_dashboard'))


    selected_date_str = request.args.get('date')
    
    show_summary = False

    if selected_date_str:
        try:
            selected_date = date.fromisoformat(selected_date_str)
            show_summary = True
        except ValueError:
            flash('Invalid date format provided in URL. Using today\'s date.', 'warning')
            selected_date = date.today()
    else:
        selected_date = date.today()

    # Fetch students directly assigned to this specific section_period
    students = db_session.query(StudentInfo).filter_by(
        section_period_id=section_period_id
    ).order_by(StudentInfo.name).all()


    existing_attendance_records = db_session.query(Attendance).filter(
        Attendance.student_info_id.in_([s.id for s in students]),
        Attendance.attendance_date == selected_date
    ).all()
    
    attendance_status_map = {str(rec.student_info_id): rec.status for rec in existing_attendance_records}

    if request.method == 'POST':
        form_date_str = request.form.get('attendance_date')
        if not form_date_str:
            flash('Attendance date is missing from form submission.', 'error')
            return render_template('teacher_attendance_details.html',
                                   section_period=section_period,
                                   students=students,
                                   selected_date=selected_date,
                                   attendance_status_map=attendance_status_map,
                                   attendance_statuses=ATTENDANCE_STATUSES,
                                   show_summary=True)
        
        try:
            submission_date = date.fromisoformat(form_date_str)

        except ValueError:
            flash('Invalid date format submitted. Please try again.', 'error')
            return render_template('teacher_attendance_details.html',
                                   section_period=section_period,
                                   students=students,
                                   selected_date=selected_date,
                                   attendance_status_map=attendance_status_map,
                                   attendance_statuses=ATTENDANCE_STATUSES,
                                   show_summary=True)

        try:
            num_updated_or_added = 0
            for student_item in students:
                status_key = f'status_{student_item.id}'
                status = request.form.get(status_key)

                if status:
                    existing_record = db_session.query(Attendance).filter(
                        Attendance.student_info_id == student_item.id,
                        Attendance.attendance_date == submission_date
                    ).first()

                    if existing_record:
                        if existing_record.status != status:
                            existing_record.status = status
                            existing_record.recorded_by = teacher_id
                            num_updated_or_added += 1
                    else:
                        new_record = Attendance(
                            student_info_id=student_item.id,
                            attendance_date=submission_date,
                            status=status,
                            recorded_by=teacher_id
                        )
                        db_session.add(new_record)
                        num_updated_or_added += 1
            
            if num_updated_or_added > 0:
                db_session.commit()
                flash(f'Attendance for {submission_date.strftime("%A, %B %d, %Y")} saved successfully!', 'success')
            else:
                db_session.rollback()
                flash('No changes to attendance were detected or saved.', 'info')
                
            return redirect(url_for('teacher_section_attendance_details', section_period_id=section_period_id, date=submission_date.isoformat()))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error saving attendance: {e}", exc_info=True)
            flash('An error occurred while saving attendance. Please try again.', 'error')

    return render_template('teacher_attendance_details.html',
                           section_period=section_period,
                           students=students,
                           selected_date=selected_date,
                           attendance_status_map=attendance_status_map,
                           attendance_statuses=ATTENDANCE_STATUSES,
                           show_summary=show_summary)

@app.route('/teacher/section_period/<uuid:section_period_id>/attendance_delete/<string:attendance_date_str>', methods=['POST'])
@login_required
@user_type_required('teacher')
def delete_section_attendance_date(section_period_id, attendance_date_str):
    db_session = g.session
    user_id = uuid.UUID(session['user_id'])
    password = request.form.get('password')

    if not password or not verify_current_user_password(user_id, password):
        return jsonify({'success': False, 'message': 'Incorrect password.'})

    teacher_specialization = session.get('specialization')
    teacher_grade_level = session.get('grade_level_assigned')

    section_period = db_session.query(SectionPeriod).options(
        joinedload(SectionPeriod.section).joinedload(Section.grade_level),
        joinedload(SectionPeriod.section).joinedload(Section.strand) # Load strand via section
    ).filter_by(id=section_period_id).first()
    
    if not section_period:
        return jsonify({'success': False, 'message': 'Period not found.'})

    # Permission check (same as teacher_section_period_view)
    if section_period.section.grade_level.name != teacher_grade_level or \
       (section_period.assigned_teacher_id and str(section_period.assigned_teacher_id) != str(user_id)) :
        return jsonify({'success': False, 'message': 'You do not have permission to delete attendance for this period.'})

    if section_period.section.grade_level.level_type == 'SHS':
        if not section_period.section.strand or section_period.section.strand.name != teacher_specialization:
            return jsonify({'success': False, 'message': 'You do not have permission to delete attendance for this period (incorrect strand).'})
    elif section_period.section.grade_level.level_type == 'JHS':
        if section_period.section.strand_id is not None:
             return jsonify({'success': False, 'message': 'You do not have permission to delete attendance for this period (JHS period incorrectly assigned to a strand).'})

    try:
        date_to_delete = date.fromisoformat(attendance_date_str)
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid date format provided for deletion.'})

    try:
        attendance_records_to_delete = db_session.query(Attendance).join(StudentInfo).filter(
            StudentInfo.section_period_id == section_period_id,
            Attendance.recorded_by == user_id,
            Attendance.attendance_date == date_to_delete
        ).all()

        if not attendance_records_to_delete:
            return jsonify({'success': False, 'message': f'No attendance records found for {date_to_delete.strftime("%B %d, %Y")} to delete by you.'})

        for record in attendance_records_to_delete:
            db_session.delete(record)
        
        db_session.commit()
        return jsonify({'success': True, 'message': f'Attendance for {date_to_delete.strftime("%A, %B %d, %Y")} deleted successfully!'})
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting attendance for date {attendance_date_str}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred while deleting the attendance.'})


if __name__ == '__main__':
    # WARNING: This will drop and recreate all database tables, deleting existing data.
    # Use this for development when schema changes. In production, use migrations.
    #print("WARNING: Dropping and recreating all database tables. All existing data will be lost.")
    #Base.metadata.drop_all(engine) 
    #Base.metadata.create_all(engine)
    app.run(debug=True)
