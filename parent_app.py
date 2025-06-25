import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import uuid
from datetime import date, timedelta, datetime
import decimal

# Import SQLAlchemy components
from sqlalchemy import create_engine, Column, Integer, String, Date, Numeric, ForeignKey, DateTime, UniqueConstraint, and_, or_, case, func
from sqlalchemy.orm import sessionmaker, relationship, declarative_base, joinedload
from sqlalchemy.sql import func
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

# Import the PostgreSQL specific UUID type
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from dotenv import load_dotenv
from app import GradingSystem, GradingComponent, GradableItem, StudentScore

load_dotenv()

# --- Flask App Configuration ---
app = Flask(__name__, template_folder='parent_templates')
app.secret_key = os.environ.get('PARENT_FLASK_SECRET_KEY', 'parent_secret_key_for_development_only')

# Database connection details (same as main app)
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set.")

# --- SQLAlchemy Setup ---
# For Supabase free tier on Render: pool_size=2, max_overflow=1 (safe for free tier, avoids connection exhaustion)
engine = create_engine(
    DATABASE_URL,  # Use the pooled connection string from Supabase
    pool_size=2,   # Supabase free tier allows max 2 connections
    max_overflow=1, # Allow 1 extra connection for short spikes
    pool_timeout=30,
)
Base = declarative_base()

# --- Parent and Student Models ---
class Parent(Base):
    __tablename__ = 'parents'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    phone_number = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship to students
    students = relationship('Student', back_populates='parent')

    def __repr__(self):
        return f"<Parent(id={self.id}, username='{self.username}', email='{self.email}')>"

class Student(Base):
    __tablename__ = 'students'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_id = Column(PG_UUID(as_uuid=True), ForeignKey('parents.id'), nullable=False)
    student_id_number = Column(String(255), unique=True, nullable=False)  # Links to main app's StudentInfo
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    grade_level = Column(String(50), nullable=False)  # e.g., 'Grade 7', 'Grade 11'
    section_name = Column(String(255), nullable=False)  # e.g., 'A', 'B'
    strand_name = Column(String(255), nullable=True)  # For SHS students
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    parent = relationship('Parent', back_populates='students')
    grades = relationship('StudentGrade', back_populates='student', cascade='all, delete-orphan')
    attendance_records = relationship('StudentAttendance', back_populates='student', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Student(id={self.id}, name='{self.first_name} {self.last_name}', student_id='{self.student_id_number}')>"

class StudentGrade(Base):
    __tablename__ = 'student_grades'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(PG_UUID(as_uuid=True), ForeignKey('students.id'), nullable=False)
    subject_name = Column(String(255), nullable=False)
    grade_value = Column(Numeric(5, 2), nullable=False)
    period_name = Column(String(50), nullable=False)  # e.g., '1st Sem', 'Q1'
    school_year = Column(String(50), nullable=False)
    teacher_name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    student = relationship('Student', back_populates='grades')

    def __repr__(self):
        return f"<StudentGrade(subject='{self.subject_name}', grade={self.grade_value}, period='{self.period_name}')>"

class StudentAttendance(Base):
    __tablename__ = 'student_attendance'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(PG_UUID(as_uuid=True), ForeignKey('students.id'), nullable=False)
    subject_name = Column(String(255), nullable=False)
    attendance_date = Column(Date, nullable=False)
    status = Column(String(50), nullable=False)  # 'present', 'absent', 'late', 'excused'
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    student = relationship('Student', back_populates='attendance_records')

    def __repr__(self):
        return f"<StudentAttendance(date={self.attendance_date}, status='{self.status}', subject='{self.subject_name}')>"

# --- Add StudentInfo model for direct access to students_info ---
class StudentInfo(Base):
    __tablename__ = 'students_info'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_period_id = Column(PG_UUID(as_uuid=True))
    name = Column(String(255), nullable=False)
    student_id_number = Column(String(255), unique=True, nullable=False)
    gender = Column(String(10), nullable=True)
    parent_id = Column(PG_UUID(as_uuid=True), nullable=True)
    average_grade = Column(Numeric(5, 2), nullable=True)
    # Add more fields if needed

# --- Add minimal models for SectionPeriod, Section, Strand, GradeLevel ---
class SectionPeriod(Base):
    __tablename__ = 'section_periods'
    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    section_id = Column(PG_UUID(as_uuid=True))
    period_name = Column(String(50))
    school_year = Column(String(50))

class Section(Base):
    __tablename__ = 'sections'
    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    name = Column(String(255))
    strand_id = Column(PG_UUID(as_uuid=True))
    grade_level_id = Column(PG_UUID(as_uuid=True))

class Strand(Base):
    __tablename__ = 'strands'
    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    name = Column(String(255))

class GradeLevel(Base):
    __tablename__ = 'grade_levels'
    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    name = Column(String(50))

# --- Add minimal models for Grade, SectionSubject, Attendance ---
class Grade(Base):
    __tablename__ = 'grades'
    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    student_info_id = Column(PG_UUID(as_uuid=True))
    section_subject_id = Column(PG_UUID(as_uuid=True))
    grade_value = Column(Numeric(5, 2))
    semester = Column(String(50))
    school_year = Column(String(50))

class SectionSubject(Base):
    __tablename__ = 'section_subjects'
    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    section_period_id = Column(PG_UUID(as_uuid=True))
    subject_name = Column(String(255))

class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    student_info_id = Column(PG_UUID(as_uuid=True))
    section_subject_id = Column(PG_UUID(as_uuid=True))
    attendance_date = Column(Date)
    status = Column(String(50))

# Create tables
Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)

# --- Database Session Management ---
def open_db_session():
    g.session = Session()

def close_db_session(exception):
    db_session = g.pop('session', None)
    if db_session is not None:
        if exception:
            db_session.rollback()
        db_session.close()

app.before_request(open_db_session)
app.teardown_appcontext(close_db_session)

# --- Authentication Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'parent_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('parent_login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Helper Functions ---
def get_school_year_options():
    current_year = date.today().year
    school_years = [f"{current_year}-{current_year+1}", f"{current_year-1}-{current_year}", f"{current_year+1}-{current_year+2}"]
    return sorted(list(set(school_years)), reverse=True)

# --- Routes ---

@app.route('/')
def index():
    return render_template('parent_index.html')

@app.route('/parent/register', methods=['GET', 'POST'])
def parent_register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        phone_number = request.form.get('phone_number', '')

        if not all([username, password, email, first_name, last_name]):
            flash('All required fields must be filled.', 'error')
            return render_template('parent_register.html')

        # Check if username or email already exists
        existing_user = g.session.query(Parent).filter(
            or_(Parent.username == username, Parent.email == email)
        ).first()
        
        if existing_user:
            flash('Username or email already exists.', 'error')
            return render_template('parent_register.html')

        # Create new parent
        hashed_password = generate_password_hash(password)
        new_parent = Parent(
            username=username,
            password_hash=hashed_password,
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone_number=phone_number
        )

        try:
            g.session.add(new_parent)
            g.session.commit()
            flash('Registration successful! You can now log in.', 'success')
            return redirect(url_for('parent_login'))
        except Exception as e:
            g.session.rollback()
            flash('An error occurred during registration.', 'error')

    return render_template('parent_register.html')

@app.route('/parent/login', methods=['GET', 'POST'])
def parent_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if not username or not password:
            flash('Username and password are required.', 'error')
            return render_template('parent_login.html')

        parent = g.session.query(Parent).filter_by(username=username).first()

        if parent and check_password_hash(parent.password_hash, password):
            session['parent_id'] = str(parent.id)
            session['parent_username'] = parent.username
            session['parent_name'] = f"{parent.first_name} {parent.last_name}"
            
            flash(f'Welcome, {parent.first_name}!', 'success')
            return redirect(url_for('parent_dashboard'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template('parent_login.html')

@app.route('/parent/logout')
@login_required
def parent_logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('parent_login'))

@app.route('/parent/dashboard')
@login_required
def parent_dashboard():
    parent_id = uuid.UUID(session['parent_id'])
    # Get all students_info for this parent
    students = g.session.query(StudentInfo).filter_by(parent_id=parent_id).order_by(StudentInfo.name).all()
    for student in students:
        name_parts = student.name.split()
        student.first_name = name_parts[0]
        student.last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
        # Fetch section, strand, grade_level
        section_period = g.session.query(SectionPeriod).filter_by(id=student.section_period_id).first()
        if section_period:
            section = g.session.query(Section).filter_by(id=section_period.section_id).first()
            if section:
                student.section_name = section.name or ''
                # Strand
                if section.strand_id:
                    strand = g.session.query(Strand).filter_by(id=section.strand_id).first()
                    student.strand_name = strand.name if strand else ''
                else:
                    student.strand_name = ''
                # Grade level
                if section.grade_level_id:
                    grade_level = g.session.query(GradeLevel).filter_by(id=section.grade_level_id).first()
                    student.grade_level = grade_level.name if grade_level else ''
                else:
                    student.grade_level = ''
            else:
                student.section_name = ''
                student.strand_name = ''
                student.grade_level = ''
        else:
            student.section_name = ''
            student.strand_name = ''
            student.grade_level = ''
        # Set latest_grades and average_grade to None for now (unless you want to join grades)
        student.latest_grades = []
        student.average_grade = student.average_grade if hasattr(student, 'average_grade') else None
    return render_template('parent_dashboard.html', students=students)

@app.route('/parent/student/<uuid:student_id>')
@login_required
def student_details(student_id):
    parent_id = uuid.UUID(session['parent_id'])
    student = g.session.query(StudentInfo).filter_by(id=student_id, parent_id=parent_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('parent_dashboard'))
    # Fetch section, grade, strand as in dashboard for display
    section_period = g.session.query(SectionPeriod).filter_by(id=student.section_period_id).first()
    if section_period:
        section = g.session.query(Section).filter_by(id=section_period.section_id).first()
        if section:
            student.section_name = section.name or ''
            if section.strand_id:
                strand = g.session.query(Strand).filter_by(id=section.strand_id).first()
                student.strand_name = strand.name if strand else ''
            else:
                student.strand_name = ''
            if section.grade_level_id:
                grade_level = g.session.query(GradeLevel).filter_by(id=section.grade_level_id).first()
                student.grade_level = grade_level.name if grade_level else ''
            else:
                student.grade_level = ''
        else:
            student.section_name = ''
            student.strand_name = ''
            student.grade_level = ''
    else:
        student.section_name = ''
        student.strand_name = ''
        student.grade_level = ''
    return render_template('student_details.html', student=student)

@app.route('/parent/student/<uuid:student_id>/grades')
@login_required
def student_grades(student_id):
    parent_id = uuid.UUID(session['parent_id'])
    student = g.session.query(StudentInfo).filter_by(id=student_id, parent_id=parent_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('parent_dashboard'))

    # --- Fetch all subjects for this student ---
    section_period = g.session.query(SectionPeriod).filter_by(id=student.section_period_id).first()
    section_subjects = g.session.query(SectionSubject).filter_by(section_period_id=student.section_period_id).all()

    # --- Fetch all grades for this student ---
    grades = g.session.query(Grade).filter_by(student_info_id=student.id).all()
    grades_by_subject = {}
    for subject in section_subjects:
        subject_grades = [g for g in grades if g.section_subject_id == subject.id]
        grades_by_subject[subject.subject_name] = {
            'total_grade': float(subject_grades[0].grade_value) if subject_grades else None,
            'grades': subject_grades
        }

    # --- Fetch grading system and items for each subject ---
    detailed_grades = {}
    for subject in section_subjects:
        grading_system = g.session.query(GradingSystem).filter_by(section_subject_id=subject.id).first()
        if not grading_system:
            continue
        components = g.session.query(GradingComponent).filter_by(system_id=grading_system.id).all()
        items = g.session.query(GradableItem).join(GradingComponent).filter(GradingComponent.system_id == grading_system.id).all()
        # Fetch scores for this student for all items in this subject
        scores = g.session.query(StudentScore).filter_by(student_info_id=student.id).all()
        scores_map = {s.item_id: s.score for s in scores}
        # Organize by component
        subject_detail = []
        for component in components:
            comp_items = [i for i in items if i.component_id == component.id]
            for item in comp_items:
                subject_detail.append({
                    'component': component.name,
                    'weight': component.weight,
                    'item_title': item.title,
                    'max_score': float(item.max_score),
                    'score': float(scores_map.get(item.id, 0)),
                })
        detailed_grades[subject.subject_name] = {
            'details': subject_detail,
            'total_grade': grades_by_subject[subject.subject_name]['total_grade']
        }

    return render_template('student_grades.html', student=student, detailed_grades=detailed_grades)

@app.route('/parent/student/<uuid:student_id>/attendance')
@login_required
def student_attendance(student_id):
    parent_id = uuid.UUID(session['parent_id'])
    student = g.session.query(StudentInfo).filter_by(id=student_id, parent_id=parent_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('parent_dashboard'))
    section_period_id = student.section_period_id
    # Get all subjects for the section period
    subjects = g.session.query(SectionSubject).filter_by(section_period_id=section_period_id).all()
    subject_names = [s.subject_name for s in subjects]
    subject_ids = [s.id for s in subjects]
    # Get all unique attendance dates for these subjects (for the section period, not just this student)
    all_dates_query = g.session.query(Attendance.attendance_date).filter(
        Attendance.section_subject_id.in_(subject_ids)
    ).distinct().all()
    all_dates = sorted({d[0] for d in all_dates_query}, reverse=True)
    # Get all attendance records for this student for these subjects
    attendance_records = g.session.query(
        Attendance, SectionSubject
    ).select_from(Attendance).join(
        SectionSubject, Attendance.section_subject_id == SectionSubject.id
    ).filter(
        Attendance.student_info_id == student.id,
        Attendance.section_subject_id.in_(subject_ids)
    ).all()
    # Build a dict: {(date, subject): status}
    attendance_map = {}
    for record, subject in attendance_records:
        attendance_map[(record.attendance_date, subject.subject_name)] = record.status
    # Build attendance_by_date for the template
    attendance_by_date = {}
    for date in all_dates:
        attendance_by_date[date] = {}
        for subject in subject_names:
            attendance_by_date[date][subject] = attendance_map.get((date, subject), 'Not Recorded')
    return render_template('student_attendance.html', student=student, attendance_by_date=attendance_by_date, subject_names=subject_names)

@app.route('/parent/profile', methods=['GET', 'POST'])
@login_required
def parent_profile():
    parent_id = uuid.UUID(session['parent_id'])
    parent = g.session.query(Parent).filter_by(id=parent_id).first()
    # Count children linked from students_info
    children_linked = g.session.query(StudentInfo).filter_by(parent_id=parent_id).count()
    if not parent:
        flash('Parent not found.', 'error')
        return redirect(url_for('parent_dashboard'))

    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # Verify current password
        if not check_password_hash(parent.password_hash, current_password):
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('parent_profile'))

        # Update password if provided
        if new_password:
            if new_password != confirm_password:
                flash('New passwords do not match.', 'error')
                return redirect(url_for('parent_profile'))
            
            parent.password_hash = generate_password_hash(new_password)
            g.session.commit()
            flash('Password updated successfully!', 'success')

        # Update other fields
        parent.first_name = request.form.get('first_name', parent.first_name)
        parent.last_name = request.form.get('last_name', parent.last_name)
        parent.email = request.form.get('email', parent.email)
        parent.phone_number = request.form.get('phone_number', parent.phone_number)
        
        g.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('parent_profile'))

    return render_template('parent_profile.html', parent=parent, children_linked=children_linked)

if __name__ == '__main__':
    app.run(debug=True, port=5001)  # Different port from main app 