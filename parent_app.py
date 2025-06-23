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

load_dotenv()

# --- Flask App Configuration ---
app = Flask(__name__, template_folder='parent_templates')
app.secret_key = os.environ.get('PARENT_FLASK_SECRET_KEY', 'parent_secret_key_for_development_only')

# Database connection details (same as main app)
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set.")

# --- SQLAlchemy Setup ---
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
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
    
    # Get all students for this parent
    students = g.session.query(Student).filter_by(parent_id=parent_id).order_by(Student.first_name).all()
    
    # Calculate summary for each student
    for student in students:
        # Get latest grades
        latest_grades = g.session.query(StudentGrade).filter_by(student_id=student.id).order_by(StudentGrade.created_at.desc()).limit(5).all()
        student.latest_grades = latest_grades
        
        # Calculate average grade
        grades = g.session.query(StudentGrade.grade_value).filter_by(student_id=student.id).all()
        if grades:
            student.average_grade = sum(float(g[0]) for g in grades) / len(grades)
        else:
            student.average_grade = None
        
        # Get recent attendance
        recent_attendance = g.session.query(StudentAttendance).filter_by(student_id=student.id).order_by(StudentAttendance.attendance_date.desc()).limit(10).all()
        student.recent_attendance = recent_attendance

    return render_template('parent_dashboard.html', students=students)

@app.route('/parent/student/<uuid:student_id>')
@login_required
def student_details(student_id):
    parent_id = uuid.UUID(session['parent_id'])
    
    # Verify the student belongs to this parent
    student = g.session.query(Student).filter_by(id=student_id, parent_id=parent_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('parent_dashboard'))

    # Get all grades for this student
    grades = g.session.query(StudentGrade).filter_by(student_id=student_id).order_by(StudentGrade.school_year.desc(), StudentGrade.period_name).all()
    
    # Get all attendance records
    attendance_records = g.session.query(StudentAttendance).filter_by(student_id=student_id).order_by(StudentAttendance.attendance_date.desc()).all()
    
    # Calculate attendance summary
    attendance_summary = {
        'present': sum(1 for a in attendance_records if a.status == 'present'),
        'absent': sum(1 for a in attendance_records if a.status == 'absent'),
        'late': sum(1 for a in attendance_records if a.status == 'late'),
        'excused': sum(1 for a in attendance_records if a.status == 'excused')
    }

    return render_template('student_details.html', 
                         student=student, 
                         grades=grades, 
                         attendance_records=attendance_records,
                         attendance_summary=attendance_summary)

@app.route('/parent/student/<uuid:student_id>/grades')
@login_required
def student_grades(student_id):
    parent_id = uuid.UUID(session['parent_id'])
    
    student = g.session.query(Student).filter_by(id=student_id, parent_id=parent_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('parent_dashboard'))

    # Get grades grouped by school year and period
    grades = g.session.query(StudentGrade).filter_by(student_id=student_id).order_by(
        StudentGrade.school_year.desc(), 
        StudentGrade.period_name
    ).all()

    # Group grades by school year and period
    grades_by_period = {}
    for grade in grades:
        key = f"{grade.school_year}_{grade.period_name}"
        if key not in grades_by_period:
            grades_by_period[key] = {
                'school_year': grade.school_year,
                'period_name': grade.period_name,
                'grades': []
            }
        grades_by_period[key]['grades'].append(grade)

    return render_template('student_grades.html', 
                         student=student, 
                         grades_by_period=grades_by_period)

@app.route('/parent/student/<uuid:student_id>/attendance')
@login_required
def student_attendance(student_id):
    parent_id = uuid.UUID(session['parent_id'])
    
    student = g.session.query(Student).filter_by(id=student_id, parent_id=parent_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('parent_dashboard'))

    # Get attendance records grouped by subject
    attendance_records = g.session.query(StudentAttendance).filter_by(student_id=student_id).order_by(
        StudentAttendance.subject_name,
        StudentAttendance.attendance_date.desc()
    ).all()

    # Group by subject
    attendance_by_subject = {}
    for record in attendance_records:
        if record.subject_name not in attendance_by_subject:
            attendance_by_subject[record.subject_name] = []
        attendance_by_subject[record.subject_name].append(record)

    # Calculate summary for each subject
    subject_summaries = {}
    for subject, records in attendance_by_subject.items():
        subject_summaries[subject] = {
            'present': sum(1 for r in records if r.status == 'present'),
            'absent': sum(1 for r in records if r.status == 'absent'),
            'late': sum(1 for r in records if r.status == 'late'),
            'excused': sum(1 for r in records if r.status == 'excused'),
            'total': len(records)
        }

    return render_template('student_attendance.html', 
                         student=student, 
                         attendance_by_subject=attendance_by_subject,
                         subject_summaries=subject_summaries)

@app.route('/parent/profile', methods=['GET', 'POST'])
@login_required
def parent_profile():
    parent_id = uuid.UUID(session['parent_id'])
    parent = g.session.query(Parent).filter_by(id=parent_id).first()
    
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

    return render_template('parent_profile.html', parent=parent)

if __name__ == '__main__':
    app.run(debug=True, port=5001)  # Different port from main app 