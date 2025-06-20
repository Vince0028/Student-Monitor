import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import uuid
from datetime import date, datetime
import decimal

# Import SQLAlchemy components
from sqlalchemy import create_engine, Column, String, Date, Numeric, ForeignKey, DateTime, and_, or_, func, UniqueConstraint
from sqlalchemy.orm import sessionmaker, relationship, declarative_base, joinedload
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from dotenv import load_dotenv

load_dotenv()

# --- Flask App Configuration ---
app = Flask(__name__, template_folder='student_templates')
app.secret_key = os.environ.get('STUDENT_FLASK_SECRET_KEY', 'student_secret_key_for_development_only')

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set.")

# --- SQLAlchemy Setup ---
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Base = declarative_base()

# --- Student Models ---
class Student(Base):
    __tablename__ = 'students'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    grade_level = Column(String(50), nullable=False)
    section_name = Column(String(255), nullable=False)
    strand_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    grades = relationship('StudentGrade', back_populates='student', cascade='all, delete-orphan')
    attendance_records = relationship('StudentAttendance', back_populates='student', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Student(id={self.id}, username='{self.username}', name='{self.first_name} {self.last_name}')>"

class StudentGrade(Base):
    __tablename__ = 'student_grades'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(PG_UUID(as_uuid=True), ForeignKey('students.id'), nullable=False)
    subject_name = Column(String(255), nullable=False)
    grade_value = Column(Numeric(5, 2), nullable=False)
    period_name = Column(String(50), nullable=False)
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
    status = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    student = relationship('Student', back_populates='attendance_records')

    def __repr__(self):
        return f"<StudentAttendance(date={self.attendance_date}, status='{self.status}', subject='{self.subject_name}')>"

class StudentInfo(Base):
    __tablename__ = 'students_info'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_period_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_periods.id'), nullable=False)
    name = Column(String(255), nullable=False)
    student_id_number = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Relationships omitted for brevity
    def __repr__(self):
        return f"<StudentInfo(id={self.id}, name='{self.name}', student_id_number='{self.student_id_number}')>"

class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_info_id = Column(PG_UUID(as_uuid=True), ForeignKey('students_info.id'), nullable=False)
    section_subject_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_subjects.id'), nullable=False)
    attendance_date = Column(Date, nullable=False)
    status = Column(String(50), nullable=False)
    recorded_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('student_info_id', 'section_subject_id', 'attendance_date'),)
    # Relationships omitted for brevity
    def __repr__(self):
        return f"<Attendance(id={self.id}, student_info_id={self.student_info_id}, date={self.attendance_date}, status='{self.status}')>"

class Grade(Base):
    __tablename__ = 'grades'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_info_id = Column(PG_UUID(as_uuid=True), ForeignKey('students_info.id'), nullable=False)
    section_subject_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_subjects.id'), nullable=False)
    teacher_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    grade_value = Column(Numeric(5, 2), nullable=False)
    semester = Column(String(50), nullable=True)
    school_year = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint('student_info_id', 'section_subject_id', 'semester', 'school_year'),)
    # Relationships omitted for brevity
    def __repr__(self):
        return f"<Grade(id={self.id}, student_info_id={self.student_info_id}, grade={self.grade_value})>"

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
        if 'student_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('student_login'))
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
    return redirect(url_for('student_login'))

@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    if 'student_id' in session:
        return redirect(url_for('student_dashboard'))
    if request.method == 'POST':
        student_id_number = request.form['student_id_number']  # Use student_id_number field from the form
        password = request.form['password']
        if not student_id_number or not password:
            flash('Student ID Number and password are required.', 'error')
            return render_template('student_login.html')
        student = g.session.query(StudentInfo).filter_by(student_id_number=student_id_number).first()
        if student and student.password_hash:
            # Accept both hashed and plain text passwords for compatibility
            valid = False
            try:
                valid = check_password_hash(student.password_hash, password)
            except Exception:
                pass
            if not valid:
                valid = (student.password_hash == password)
            if valid:
                session['student_id'] = str(student.id)
                session['student_id_number'] = student.student_id_number
                session['student_name'] = student.name
                response = redirect(url_for('student_dashboard'), code=303)
                response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'
                return response
        flash('Invalid Student ID Number or password.', 'error')
    response = render_template('student_login.html')
    # Set headers to prevent caching of the login page
    from flask import make_response
    resp = make_response(response)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/student/logout')
@login_required
def student_logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('student_login'))

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    student_id = uuid.UUID(session['student_id'])
    student = g.session.query(StudentInfo).filter_by(id=student_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('student_login'))
    # Get latest grades
    latest_grades = g.session.query(Grade).filter_by(student_info_id=student.id).order_by(Grade.created_at.desc()).limit(5).all()
    # Calculate average grade
    grades = g.session.query(Grade.grade_value).filter_by(student_info_id=student.id).all()
    average_grade = sum(float(g[0]) for g in grades) / len(grades) if grades else "N/A"
    # Get recent attendance
    recent_attendance = g.session.query(Attendance).filter_by(student_info_id=student.id).order_by(Attendance.attendance_date.desc()).limit(10).all()
    return render_template('student_dashboard.html', student=student, latest_grades=latest_grades, average_grade=average_grade, recent_attendance=recent_attendance)

@app.route('/student/grades')
@login_required
def student_grades():
    student_id = uuid.UUID(session['student_id'])
    student = g.session.query(StudentInfo).filter_by(id=student_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('student_login'))
    grades = g.session.query(Grade).filter_by(student_info_id=student_id).order_by(Grade.school_year.desc(), Grade.semester).all()
    grades_by_period = {}
    for grade in grades:
        key = f"{grade.school_year}_{grade.semester}"
        if key not in grades_by_period:
            grades_by_period[key] = {
                'school_year': grade.school_year,
                'period_name': grade.semester,
                'grades': []
            }
        grades_by_period[key]['grades'].append(grade)
    return render_template('student_grades.html', student=student, grades_by_period=grades_by_period)

@app.route('/student/attendance')
@login_required
def student_attendance():
    student_id = uuid.UUID(session['student_id'])
    student = g.session.query(StudentInfo).filter_by(id=student_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('student_login'))
    attendance_records = g.session.query(Attendance).filter_by(student_info_id=student_id).order_by(Attendance.attendance_date.desc()).all()
    attendance_by_subject = {}
    for record in attendance_records:
        subject = record.section_subject.subject_name if record.section_subject else 'Unknown'
        if subject not in attendance_by_subject:
            attendance_by_subject[subject] = []
        attendance_by_subject[subject].append(record)
    subject_summaries = {}
    for subject, records in attendance_by_subject.items():
        subject_summaries[subject] = {
            'present': sum(1 for r in records if r.status == 'present'),
            'absent': sum(1 for r in records if r.status == 'absent'),
            'late': sum(1 for r in records if r.status == 'late'),
            'excused': sum(1 for r in records if r.status == 'excused'),
            'total': len(records)
        }
    return render_template('student_attendance.html', student=student, attendance_by_subject=attendance_by_subject, subject_summaries=subject_summaries)

@app.route('/student/profile', methods=['GET', 'POST'])
@login_required
def student_profile():
    student_id = uuid.UUID(session['student_id'])
    student = g.session.query(StudentInfo).filter_by(id=student_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('student_login'))
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        if not check_password_hash(student.password_hash, current_password):
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('student_profile'))
        if new_password:
            if new_password != confirm_password:
                flash('New passwords do not match.', 'error')
                return redirect(url_for('student_profile'))
            student.password_hash = generate_password_hash(new_password)
            g.session.commit()
            flash('Password updated successfully!', 'success')
        student.name = request.form.get('name', student.name)
        g.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('student_profile'))
    return render_template('student_profile.html', student=student)

@app.route('/student/assignments')
@login_required
def student_assignments():
    # TODO: Integrate with backend/database to fetch assignments for the logged-in student
    # Example: assignments = g.session.query(Assignment).filter_by(student_id=session['student_id']).all()
    assignments = []  # Placeholder
    return render_template('student_assignments.html', assignments=assignments)

@app.route('/student/assignments/completed')
@login_required
def student_assignments_completed():
    # TODO: Integrate with backend/database to fetch completed assignments
    assignments = []  # Placeholder
    return render_template('student_assignments_completed.html', assignments=assignments)

@app.route('/student/assignments/past_due')
@login_required
def student_assignments_past_due():
    # TODO: Integrate with backend/database to fetch past due assignments
    assignments = []  # Placeholder
    return render_template('student_assignments_past_due.html', assignments=assignments)

@app.route('/student/assignments/upcoming')
@login_required
def student_assignments_upcoming():
    # TODO: Integrate with backend/database to fetch upcoming assignments
    assignments = []  # Placeholder
    return render_template('student_assignments_upcoming.html', assignments=assignments)

@app.route('/student/assignments/submit', methods=['GET', 'POST'])
@login_required
def student_submit_assignment():
    # TODO: Integrate with backend/database to handle assignment submission
    subjects = []  # Placeholder for subject list
    if request.method == 'POST':
        # Handle file upload and save assignment
        pass
    return render_template('student_submit_assignment.html', subjects=subjects)

if __name__ == '__main__':
    app.run(debug=True, port=5002)  # Different port from parent app
