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
    specialization = Column(String(255), nullable=True) # For teachers: STEM, ICT, ABM, HUMSS, GAS, HE, General Education
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    recorded_attendance = relationship('Attendance', back_populates='recorder_user')
    assigned_grades = relationship('Grade', back_populates='teacher')
    created_strands = relationship('Strand', back_populates='creator', cascade='all, delete-orphan')
    created_sections = relationship('Section', back_populates='creator', cascade='all, delete-orphan')
    added_section_subjects = relationship('SectionSubject', back_populates='adder_user', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', user_type='{self.user_type}', specialization='{self.specialization}')>"

class Strand(Base):
    __tablename__ = 'strands'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id')) # Student admin who created it
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    creator = relationship('User', back_populates='created_strands')
    sections = relationship('Section', back_populates='strand', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Strand(id={self.id}, name='{self.name}')>"

class Section(Base):
    __tablename__ = 'sections'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    strand_id = Column(PG_UUID(as_uuid=True), ForeignKey('strands.id'), nullable=False)
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id')) # Student admin OR Teacher who created it
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('name', 'strand_id'),
    )

    strand = relationship('Strand', back_populates='sections', lazy='joined')
    creator = relationship('User', back_populates='created_sections')
    students = relationship('StudentInfo', back_populates='section', cascade='all, delete-orphan')
    section_subjects = relationship('SectionSubject', back_populates='section', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Section(id={self.id}, name='{self.name}', strand_id={self.strand_id})>"

class StudentInfo(Base):
    __tablename__ = 'students_info'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id = Column(PG_UUID(as_uuid=True), ForeignKey('sections.id'), nullable=False)
    name = Column(String(255), nullable=False)
    student_id_number = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    section = relationship('Section', back_populates='students')
    attendance_records = relationship('Attendance', back_populates='student_info', cascade='all, delete-orphan')
    grades = relationship('Grade', back_populates='student_info', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<StudentInfo(id={self.id}, name='{self.name}', student_id_number='{self.student_id_number}')>"

class SectionSubject(Base):
    __tablename__ = 'section_subjects'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id = Column(PG_UUID(as_uuid=True), ForeignKey('sections.id'), nullable=False)
    subject_name = Column(String(255), nullable=False)
    added_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('section_id', 'subject_name'),
    )

    section = relationship('Section', back_populates='section_subjects')
    adder_user = relationship('User', back_populates='added_section_subjects')
    grades = relationship('Grade', back_populates='section_subject', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<SectionSubject(id={self.id}, section_id={self.section_id}, subject_name='{self.subject_name}')>"

class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_info_id = Column(PG_UUID(as_uuid=True), ForeignKey('students_info.id'), nullable=False)
    attendance_date = Column(Date, nullable=False)
    status = Column(String(50), nullable=False) # 'present', 'absent', 'late', 'excused'
    recorded_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'))
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
    teacher_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    grade_value = Column(Numeric(5, 2), nullable=False)
    semester = Column(String(50), nullable=False) # '1st Sem', '2nd Sem'
    school_year = Column(String(50), nullable=False) # '2025-2026'
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('student_info_id', 'section_subject_id', 'semester', 'school_year'),
    )

    student_info = relationship('StudentInfo', back_populates='grades')
    section_subject = relationship('SectionSubject', back_populates='grades')
    teacher = relationship('User', back_populates='assigned_grades')

    def __repr__(self):
        return f"<Grade(id={self.id}, student_info_id={self.student_info_id}, subject='{self.section_subject.subject_name}', grade={self.grade_value}')>"


Session = sessionmaker(bind=engine)

TEACHER_SPECIALIZATIONS = ['ICT', 'STEM', 'ABM', 'HUMSS', 'GAS', 'HE', 'General Education']
SEMESTERS = ['1st Sem', '2nd Sem']
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
        specialization = request.form.get('specialization')

        if not username or not password or not user_type:
            flash('All fields are required.', 'error')
            return render_template('register.html', teacher_specializations=TEACHER_SPECIALIZATIONS)
        
        if user_type == 'teacher' and not specialization:
            flash('Teacher specialization is required.', 'error')
            return render_template('register.html', teacher_specializations=TEACHER_SPECIALIZATIONS)

        hashed_password = generate_password_hash(password)
        db_session = g.session
        try:
            existing_user = db_session.query(User).filter_by(username=username).first()
            if existing_user:
                flash('Username already exists. Please choose a different one.', 'error')
                return render_template('register.html', teacher_specializations=TEACHER_SPECIALIZATIONS)

            new_user = User(username=username, password_hash=hashed_password, user_type=user_type, specialization=specialization if user_type == 'teacher' else None)
            db_session.add(new_user)
            db_session.commit()
            flash(f'Registration successful! You can now log in as a {user_type.capitalize()}.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error during registration: {e}")
            flash('An error occurred during registration. Please try again.', 'error')

    return render_template('register.html', teacher_specializations=TEACHER_SPECIALIZATIONS)

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
            session['specialization'] = user.specialization

            flash(f'Welcome, {user.username}! You are logged in as a {session["user_type"].capitalize()}.', 'success')
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

# --- Student Admin Dashboard Routes ---
@app.route('/student_dashboard')
@login_required
@user_type_required('student')
def student_dashboard():
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])
    strands = db_session.query(Strand).filter_by(created_by=student_admin_id).order_by(Strand.name).all()
    
    return render_template('student_dashboard.html', strands=strands)

@app.route('/add_strand', methods=['GET', 'POST'])
@login_required
@user_type_required('student')
def add_strand():
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])

    if request.method == 'POST':
        strand_name = request.form['name'].strip()
        if not strand_name:
            flash('Strand name cannot be empty.', 'error')
            return render_template('add_strand.html')

        try:
            existing_strand = db_session.query(Strand).filter(func.lower(Strand.name) == func.lower(strand_name)).first()
            if existing_strand:
                flash(f'Strand "{strand_name}" already exists.', 'error')
                return render_template('add_strand.html')

            new_strand = Strand(name=strand_name, created_by=student_admin_id)
            db_session.add(new_strand)
            db_session.commit()
            flash(f'Strand "{strand_name}" added successfully!', 'success')
            return redirect(url_for('student_dashboard'))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error adding strand: {e}")
            flash('An error occurred while adding the strand. Please try again.', 'error')

    return render_template('add_strand.html')

@app.route('/strand/<uuid:strand_id>')
@login_required
@user_type_required('student')
def strand_details(strand_id):
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])
    
    strand = db_session.query(Strand).filter_by(id=strand_id, created_by=student_admin_id).first()
    if not strand:
        flash('Strand not found or you do not have permission to view it.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    sections = db_session.query(Section).filter_by(strand_id=strand_id).order_by(Section.name).all()
    
    return render_template('strand_details.html', sections=sections, strand=strand)

@app.route('/strand/<uuid:strand_id>/add_section', methods=['GET', 'POST'])
@login_required
@user_type_required('student')
def add_section(strand_id):
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])

    strand = db_session.query(Strand).filter_by(id=strand_id, created_by=student_admin_id).first()
    if not strand:
        flash('Strand not found or you do not have permission to add sections to it.', 'danger')
        return redirect(url_for('student_dashboard'))

    if request.method == 'POST':
        section_name = request.form['name'].strip()
        if not section_name:
            flash('Section name cannot be empty.', 'error')
            return render_template('add_section.html', strand=strand)

        try:
            existing_section = db_session.query(Section).filter(
                func.lower(Section.name) == func.lower(section_name),
                Section.strand_id == strand_id
            ).first()
            if existing_section:
                flash(f'Section "{section_name}" already exists in this strand.', 'error')
                return render_template('add_section.html', strand=strand)

            new_section = Section(name=section_name, strand_id=strand_id, created_by=student_admin_id)
            db_session.add(new_section)
            db_session.commit()
            flash(f'Section "{section_name}" added to {strand.name} strand successfully!', 'success')
            return redirect(url_for('strand_details', strand_id=strand_id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error adding section: {e}")
            flash('An error occurred while adding the section. Please try again.', 'error')

    return render_template('add_section.html', strand=strand)


@app.route('/section/<uuid:section_id>')
@login_required
@user_type_required('student')
def section_details(section_id):
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])

    section_with_strand = db_session.query(Section).options(
        joinedload(Section.strand)
    ).filter(Section.id==section_id).first()
    
    if not section_with_strand or section_with_strand.created_by != student_admin_id:
        flash('Section not found or you do not have permission to view it.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    students = db_session.query(StudentInfo).filter_by(section_id=section_id).order_by(StudentInfo.name).all()
    
    return render_template('section_details.html', section=section_with_strand, students=students)

@app.route('/section/<uuid:section_id>/add_student', methods=['GET', 'POST'])
@login_required
@user_type_required('student')
def add_student_to_section(section_id):
    db_session = g.session
    student_admin_id = uuid.UUID(session['user_id'])

    section_with_strand = db_session.query(Section).options(
        joinedload(Section.strand)
    ).filter(Section.id==section_id).first()

    if not section_with_strand or section_with_strand.created_by != student_admin_id:
        flash('Section not found or you do not have permission to add students to it.', 'danger')
        return redirect(url_for('student_dashboard'))
    
    if request.method == 'POST':
        student_name = request.form['name'].strip()
        student_id_number = request.form['student_id_number'].strip()

        if not student_name or not student_id_number:
            flash('Student name and ID number are required.', 'error')
            return render_template('add_student_to_section.html', section=section_with_strand)

        try:
            existing_student_by_id = db_session.query(StudentInfo).filter_by(student_id_number=student_id_number).first()
            if existing_student_by_id:
                flash(f'Student with ID Number "{student_id_number}" already exists.', 'error')
                return render_template('add_student_to_section.html', section=section_with_strand)

            new_student = StudentInfo(
                section_id=section_id,
                name=student_name,
                student_id_number=student_id_number
            )
            db_session.add(new_student)
            db_session.commit()
            flash(f'Student "{student_name}" added to {section_with_strand.name} section successfully!', 'success')
            return redirect(url_for('section_details', section_id=section_id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error adding student: {e}")
            flash('An error occurred while adding the student. Please try again.', 'error')

    return render_template('add_student_to_section.html', section=section_with_strand)


@app.route('/edit_student/<uuid:student_id>', methods=['GET', 'POST'])
@login_required
@user_type_required('student')
def edit_student(student_id):
    db_session = g.session
    
    student_to_edit = db_session.query(StudentInfo).filter_by(id=student_id).first()
    if not student_to_edit:
        flash('Student not found.', 'danger')
        return redirect(url_for('student_dashboard')) 

    sections_for_dropdown = db_session.query(Section).options(
        joinedload(Section.strand)
    ).filter_by(created_by=uuid.UUID(session['user_id'])).all()
    
    current_section_manageable = any(s.id == student_to_edit.section_id for s in sections_for_dropdown)
    if not current_section_manageable:
         flash('You do not have permission to edit this student.', 'danger')
         if student_to_edit and student_to_edit.section_id:
             return redirect(url_for('section_details', section_id=student_to_edit.section_id))
         return redirect(url_for('student_dashboard'))


    if request.method == 'POST':
        student_name = request.form['name'].strip()
        student_id_number = request.form['student_id_number'].strip()
        new_section_id_str = request.form.get('section_id') 

        if not student_name or not student_id_number or not new_section_id_str:
            flash('All student fields are required.', 'error')
            return render_template('edit_student.html', student=student_to_edit, sections=sections_for_dropdown)
        
        new_section_id = uuid.UUID(new_section_id_str)

        try:
            if student_id_number != student_to_edit.student_id_number:
                existing_student_by_id = db_session.query(StudentInfo).filter(
                    StudentInfo.student_id_number == student_id_number,
                    StudentInfo.id != student_id
                ).first()
                if existing_student_by_id:
                    flash(f'Student ID Number "{student_id_number}" already exists for another student.', 'error')
                    return render_template('edit_student.html', student=student_to_edit, sections=sections_for_dropdown)
            
            new_section_obj_valid = any(s.id == new_section_id for s in sections_for_dropdown)
            if not new_section_obj_valid:
                flash('Selected new section is invalid or you do not have permission for it.', 'error')
                return render_template('edit_student.html', student=student_to_edit, sections=sections_for_dropdown)
            
            student_to_edit.name = student_name
            student_to_edit.student_id_number = student_id_number
            student_to_edit.section_id = new_section_id

            db_session.commit()
            flash(f'Student "{student_name}" updated successfully!', 'success')
            return redirect(url_for('section_details', section_id=student_to_edit.section_id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error editing student: {e}")
            flash('An error occurred while updating the student. Please try again.', 'error')

    return render_template('edit_student.html', student=student_to_edit, sections=sections_for_dropdown)


# --- Teacher Dashboard Routes ---
@app.route('/teacher_dashboard')
@login_required
@user_type_required('teacher')
def teacher_dashboard():
    db_session = g.session
    teacher_specialization = session.get('specialization')

    if teacher_specialization == 'General Education':
        sections = db_session.query(Section).options(joinedload(Section.strand)).order_by(Section.name).all()
    else:
        sections = db_session.query(Section).options(joinedload(Section.strand)).join(Strand).filter(
            Strand.name == teacher_specialization
        ).order_by(Section.name).all()
    
    # Calculate average grades per section
    sections_with_averages = []
    for section in sections:
        # Get all students in the section
        students_in_section_ids = [str(s.id) for s in section.students] # Convert UUID to string for filter

        total_grades_sum = 0
        total_grades_count = 0

        if students_in_section_ids:
            # Get all grades for these students across all subjects, semesters, and school years
            # Filter by student_info_id (as strings) to match type from students_in_section_ids
            all_grades = db_session.query(Grade.grade_value).filter(
                Grade.student_info_id.in_(students_in_section_ids)
            ).all()
            
            for grade_val in all_grades:
                total_grades_sum += float(grade_val.grade_value)
                total_grades_count += 1
        
        section_average = round(total_grades_sum / total_grades_count, 2) if total_grades_count > 0 else 'N/A'
        
        sections_with_averages.append({
            'id': section.id,
            'name': section.name,
            'strand_name': section.strand.name,
            'average_grade': section_average
        })

    return render_template('teacher_dashboard.html', sections=sections_with_averages, teacher_specialization=teacher_specialization)

@app.route('/teacher/section/<uuid:section_id>')
@login_required
@user_type_required('teacher')
def teacher_section_details(section_id):
    db_session = g.session
    teacher_specialization = session.get('specialization')

    section = db_session.query(Section).options(joinedload(Section.strand)).filter_by(id=section_id).first()
    
    if not section or (teacher_specialization != 'General Education' and section.strand.name != teacher_specialization):
        flash('Section not found or you do not have permission to view it.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    students = db_session.query(StudentInfo).filter_by(section_id=section_id).order_by(StudentInfo.name).all()
    section_subjects = db_session.query(SectionSubject).filter_by(section_id=section_id).order_by(SectionSubject.subject_name).all()
    
    return render_template('teacher_section_details.html', section=section, students=students, section_subjects=section_subjects)


@app.route('/teacher/section/<uuid:section_id>/add_subject', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher')
def add_subject_to_section(section_id):
    db_session = g.session
    teacher_id = uuid.UUID(session['user_id'])
    teacher_specialization = session.get('specialization')

    section = db_session.query(Section).options(joinedload(Section.strand)).filter_by(id=section_id).first()
    if not section or (teacher_specialization != 'General Education' and section.strand.name != teacher_specialization):
        flash('Section not found or you do not have permission to add subjects to it.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    if request.method == 'POST':
        subject_name = request.form['subject_name'].strip()
        if not subject_name:
            flash('Subject name cannot be empty.', 'error')
            return render_template('add_section_subject.html', section=section)
        
        try:
            existing_section_subject = db_session.query(SectionSubject).filter(
                SectionSubject.section_id == section_id,
                func.lower(SectionSubject.subject_name) == func.lower(subject_name)
            ).first()
            if existing_section_subject:
                flash(f'Subject "{subject_name}" already exists in this section.', 'error')
                return render_template('add_section_subject.html', section=section)

            new_section_subject = SectionSubject(
                section_id=section_id,
                subject_name=subject_name,
                added_by=teacher_id
            )
            db_session.add(new_section_subject)
            db_session.commit()
            flash(f'Subject "{subject_name}" added to {section.name} successfully!', 'success')
            return redirect(url_for('teacher_section_details', section_id=section_id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error adding subject to section: {e}")
            flash('An error occurred while adding the subject. Please try again.', 'error')

    return render_template('add_section_subject.html', section=section)


@app.route('/teacher/section/<uuid:section_id>/delete', methods=['POST'])
@login_required
@user_type_required('teacher')
def delete_teacher_section(section_id):
    db_session = g.session
    teacher_specialization = session.get('specialization')
    
    section_to_delete = db_session.query(Section).options(joinedload(Section.strand)).filter_by(id=section_id).first()

    if not section_to_delete:
        flash('Section not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    if teacher_specialization != 'General Education' and section_to_delete.strand.name != teacher_specialization:
        flash('You do not have permission to delete this section.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    try:
        db_session.delete(section_to_delete)
        db_session.commit()
        flash(f'Section "{section_to_delete.name}" has been deleted.', 'success')
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting section: {e}")
        flash('An error occurred while deleting the section. Please try again.', 'error')
    
    return redirect(url_for('teacher_dashboard'))


@app.route('/teacher/student/<uuid:student_id>/delete', methods=['POST'])
@login_required
@user_type_required('teacher')
def delete_student_from_section(student_id):
    db_session = g.session
    teacher_specialization = session.get('specialization')

    student_to_delete = db_session.query(StudentInfo).options(
        joinedload(StudentInfo.section).joinedload(Section.strand)
    ).filter_by(id=student_id).first()

    if not student_to_delete:
        flash('Student not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    redirect_section_id = student_to_delete.section.id

    if teacher_specialization != 'General Education' and student_to_delete.section.strand.name != teacher_specialization:
        flash('You do not have permission to delete this student.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    try:
        db_session.delete(student_to_delete)
        db_session.commit()
        flash(f'Student "{student_to_delete.name}" has been deleted from section "{student_to_delete.section.name}".', 'success')
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting student: {e}")
        flash('An error occurred while deleting the student. Please try again.', 'error')
    
    return redirect(url_for('teacher_section_details', section_id=redirect_section_id))


@app.route('/teacher/section/<uuid:section_id>/add_grades/<uuid:student_id>', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher')
def add_grades_for_student(section_id, student_id):
    db_session = g.session
    teacher_id = uuid.UUID(session['user_id'])
    teacher_specialization = session.get('specialization')

    student = db_session.query(StudentInfo).options(
        joinedload(StudentInfo.section).joinedload(Section.strand)
    ).filter_by(id=student_id, section_id=section_id).first()

    if not student or (teacher_specialization != 'General Education' and student.section.strand.name != teacher_specialization):
        flash('Student not found in this section or you do not have permission to grade them.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    section_subjects = db_session.query(SectionSubject).filter_by(section_id=section_id).order_by(SectionSubject.subject_name).all()
    
    section_subjects_data = [{
        'id': str(s.id),
        'subject_name': s.subject_name
    } for s in section_subjects]

    existing_grades_data = db_session.query(Grade, SectionSubject).join(SectionSubject).filter(
        Grade.student_info_id == student_id,
        SectionSubject.section_id == section_id
    ).all()

    grades_dict = {}
    for grade_obj, section_subject_obj in existing_grades_data:
        key = f"{section_subject_obj.subject_name}|{grade_obj.semester}|{grade_obj.school_year}"
        grades_dict[key] = {
            'grade_value': float(grade_obj.grade_value),
            'id': str(grade_obj.id),
            'section_subject_id': str(section_subject_obj.id)
        }

    current_year = date.today().year
    school_years = [f"{current_year}-{current_year+1}", f"{current_year-1}-{current_year}", f"{current_year+1}-{current_year+2}"]
    school_years = sorted(list(set(school_years)))

    default_semester = SEMESTERS[0] if SEMESTERS else ''
    default_school_year = school_years[0] if school_years else ''

    initial_average_grade = None
    grades_for_default_period = []
    if default_semester and default_school_year:
        for ss in section_subjects_data:
            key = f"{ss['subject_name']}|{default_semester}|{default_school_year}"
            if key in grades_dict:
                grades_for_default_period.append(grades_dict[key]['grade_value'])
        
        if grades_for_default_period:
            initial_average_grade = round(sum(grades_for_default_period) / len(grades_for_default_period), 2)


    if request.method == 'POST':
        semester = request.form['semester']
        school_year = request.form['school_year']

        if not semester or not school_year:
            flash('Semester and School Year are required.', 'error')
            return render_template('add_grades_for_student.html', student=student, section_subjects=section_subjects_data, grades_dict=grades_dict, semesters=SEMESTERS, school_years=school_years, initial_average_grade=initial_average_grade)

        if not re.fullmatch(r'\d{4}-\d{4}', school_year):
            flash('Invalid School Year format. Please use असाल-YYYY (e.g., 2025-2026).', 'error')
            return render_template('add_grades_for_student.html', student=student, section_subjects=section_subjects_data, grades_dict=grades_dict, semesters=SEMESTERS, school_years=school_years, initial_average_grade=initial_average_grade)


        grades_to_process = []
        for section_subject in section_subjects:
            grade_input_name = f"grade__{section_subject.id}"
            grade_value_str = request.form.get(grade_input_name)

            if grade_value_str:
                try:
                    grade_value = float(grade_value_str)
                    if not (0 <= grade_value <= 100):
                        flash(f'Grade for {section_subject.subject_name} must be between 0 and 100.', 'error')
                        return render_template('add_grades_for_student.html', student=student, section_subjects=section_subjects_data, grades_dict=grades_dict, semesters=SEMESTERS, school_years=school_years, initial_average_grade=initial_average_grade)
                    grades_to_process.append({
                        'section_subject_id': section_subject.id,
                        'grade_value': grade_value
                    })
                except ValueError:
                    flash(f'Invalid grade for {section_subject.subject_name}. Please enter a number.', 'error')
                    return render_template('add_grades_for_student.html', student=student, section_subjects=section_subjects_data, grades_dict=grades_dict, semesters=SEMESTERS, school_years=school_years, initial_average_grade=initial_average_grade)
        
        if not grades_to_process:
            flash('No grades provided to save.', 'warning')
            return render_template('add_grades_for_student.html', student=student, section_subjects=section_subjects_data, grades_dict=grades_dict, semesters=SEMESTERS, school_years=school_years, initial_average_grade=initial_average_grade)

        try:
            for grade_data in grades_to_process:
                existing_grade_record = db_session.query(Grade).filter(
                    Grade.student_info_id == student_id,
                    Grade.section_subject_id == grade_data['section_subject_id'],
                    Grade.semester == semester,
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
                        semester=semester,
                        school_year=school_year
                    )
                    db_session.add(new_grade)
            db_session.commit()
            flash(f'Grades for {student.name} ({semester} {school_year}) saved successfully!', 'success')
            return redirect(url_for('teacher_section_details', section_id=section_id))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error saving grades: {e}")
            flash('An error occurred while saving grades. Please try again.', 'error')
    
    return render_template('add_grades_for_student.html', student=student, section_subjects=section_subjects_data, grades_dict=grades_dict, semesters=SEMESTERS, school_years=school_years, initial_average_grade=initial_average_grade)


@app.route('/teacher/section/<uuid:section_id>/attendance_dates')
@login_required
@user_type_required('teacher')
def teacher_section_attendance_dates(section_id):
    db_session = g.session
    teacher_specialization = session.get('specialization')

    section = db_session.query(Section).options(joinedload(Section.strand)).filter_by(id=section_id).first()
    if not section or (teacher_specialization != 'General Education' and section.strand.name != teacher_specialization):
        flash('Section not found or you do not have permission to manage attendance for it.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    # Get all unique attendance dates for this section's students
    # Use distinct and order by date
    attendance_dates = db_session.query(Attendance.attendance_date).\
                        join(StudentInfo).\
                        filter(StudentInfo.section_id == section_id).\
                        distinct(Attendance.attendance_date).\
                        order_by(Attendance.attendance_date.desc()).\
                        all()
    
    # Extract just the date objects
    dates_list = [d[0] for d in attendance_dates]

    return render_template('teacher_attendance_dates.html',
                           section=section,
                           attendance_dates=dates_list)


@app.route('/teacher/section/<uuid:section_id>/attendance_details', methods=['GET', 'POST'])
@login_required
@user_type_required('teacher')
def teacher_section_attendance_details(section_id):
    db_session = g.session
    teacher_id = uuid.UUID(session['user_id'])
    teacher_specialization = session.get('specialization')

    section = db_session.query(Section).options(joinedload(Section.strand)).filter_by(id=section_id).first()
    if not section or (teacher_specialization != 'General Education' and section.strand.name != teacher_specialization):
        flash('Section not found or you do not have permission to manage attendance for it.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    # Determine the selected date
    selected_date_str = request.args.get('date') # From GET request (URL parameter)
    
    # Initialize show_summary flag
    show_summary = False

    if selected_date_str:
        try:
            selected_date = date.fromisoformat(selected_date_str)
            show_summary = True # If a date is provided in URL, it means we're viewing/editing an existing date
        except ValueError:
            # Fallback to today if date format is bad
            flash('Invalid date format provided in URL. Using today\'s date.', 'warning')
            selected_date = date.today()
    else:
        # If no date parameter is provided (e.g., from "Add Attendance" button)
        selected_date = date.today()
        # show_summary remains False here, as it's a fresh attendance entry

    students = db_session.query(StudentInfo).filter_by(section_id=section_id).order_by(StudentInfo.name).all()

    # Get existing attendance records for the selected date
    existing_attendance_records = db_session.query(Attendance).filter(
        Attendance.student_info_id.in_([s.id for s in students]),
        Attendance.attendance_date == selected_date
    ).all()
    
    attendance_status_map = {str(rec.student_info_id): rec.status for rec in existing_attendance_records}

    # If this is a POST request, process attendance submission
    if request.method == 'POST':
        # The date is explicitly submitted from the form's hidden input
        form_date_str = request.form.get('attendance_date')
        if not form_date_str:
            flash('Attendance date is missing from form submission.', 'error')
            # Render the form again with current data but without committing
            return render_template('teacher_attendance_details.html',
                                   section=section,
                                   students=students,
                                   selected_date=selected_date,
                                   attendance_status_map=attendance_status_map,
                                   attendance_statuses=ATTENDANCE_STATUSES,
                                   show_summary=True) # Always show summary after a POST attempt
        
        try:
            submission_date = date.fromisoformat(form_date_str)
            # No need to compare submission_date != selected_date here, as selected_date
            # is derived from the URL and submission_date from the form.
            # The important part is that submission_date is used for DB operations.

        except ValueError:
            flash('Invalid date format submitted. Please try again.', 'error')
            return render_template('teacher_attendance_details.html',
                                   section=section,
                                   students=students,
                                   selected_date=selected_date,
                                   attendance_status_map=attendance_status_map,
                                   attendance_statuses=ATTENDANCE_STATUSES,
                                   show_summary=True) # Always show summary after a POST attempt

        try:
            num_updated_or_added = 0 # Track how many records are processed
            for student_item in students:
                status_key = f'status_{student_item.id}'
                status = request.form.get(status_key)

                # Add debug print to check received status
                print(f"DEBUG: Student {student_item.name} ({student_item.id}) - Received status: {status}")

                # Only proceed if a status was actually provided for this student
                if status:
                    existing_record = db_session.query(Attendance).filter(
                        Attendance.student_info_id == student_item.id,
                        Attendance.attendance_date == submission_date
                    ).first()

                    if existing_record:
                        if existing_record.status != status: # Only update if status changed
                            print(f"DEBUG: Updating existing attendance for {student_item.name}: Old={existing_record.status}, New={status}")
                            existing_record.status = status
                            existing_record.recorded_by = teacher_id
                            num_updated_or_added += 1
                        else:
                            print(f"DEBUG: No status change for {student_item.name}. Status remains {status}.")
                    else:
                        print(f"DEBUG: Adding NEW attendance for {student_item.name} with status {status}")
                        new_record = Attendance(
                            student_info_id=student_item.id,
                            attendance_date=submission_date,
                            status=status,
                            recorded_by=teacher_id
                        )
                        db_session.add(new_record)
                        num_updated_or_added += 1
                else:
                    # If status is None or empty string, it means the radio button for this student was not selected.
                    # This scenario could happen if the form data is incomplete or there's an issue with JS.
                    # For consistency, we might want to ensure a default status or handle unselected.
                    # For now, we skip if status is None/empty, but print a debug message.
                    print(f"DEBUG: No status provided for student {student_item.name} - Skipping.")
            
            if num_updated_or_added > 0:
                db_session.commit()
                flash(f'Attendance for {submission_date.strftime("%A, %B %d, %Y")} saved successfully!', 'success')
                print(f"DEBUG: Successfully committed {num_updated_or_added} attendance records.")
            else:
                db_session.rollback() # Rollback if nothing was changed or added
                flash('No changes to attendance were detected or saved.', 'info')
                print(f"DEBUG: No changes detected. Rolling back session.")
                
            # Redirect to the attendance details page for the submitted date to show changes
            # This also ensures show_summary will be True after saving
            return redirect(url_for('teacher_section_attendance_details', section_id=section_id, date=submission_date.isoformat()))
        except Exception as e:
            db_session.rollback()
            app.logger.error(f"Error saving attendance: {e}", exc_info=True) # Log full traceback
            flash('An error occurred while saving attendance. Please try again.', 'error')

    # GET request: Render the attendance marking/viewing form
    return render_template('teacher_attendance_details.html',
                           section=section,
                           students=students,
                           selected_date=selected_date,
                           attendance_status_map=attendance_status_map,
                           attendance_statuses=ATTENDANCE_STATUSES,
                           show_summary=show_summary) # Pass the flag

# New route to delete attendance for a specific date
@app.route('/teacher/section/<uuid:section_id>/attendance_delete/<string:attendance_date_str>', methods=['POST'])
@login_required
@user_type_required('teacher')
def delete_section_attendance_date(section_id, attendance_date_str):
    db_session = g.session
    teacher_specialization = session.get('specialization')

    section = db_session.query(Section).options(joinedload(Section.strand)).filter_by(id=section_id).first()
    if not section or (teacher_specialization != 'General Education' and section.strand.name != teacher_specialization):
        flash('Section not found or you do not have permission to delete attendance for it.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    try:
        date_to_delete = date.fromisoformat(attendance_date_str)
    except ValueError:
        flash('Invalid date format provided for deletion.', 'error')
        return redirect(url_for('teacher_section_attendance_dates', section_id=section_id))

    try:
        # Delete all attendance records for this section and date
        attendance_records_to_delete = db_session.query(Attendance).join(StudentInfo).filter(
            StudentInfo.section_id == section_id,
            Attendance.attendance_date == date_to_delete
        ).all()

        if not attendance_records_to_delete:
            flash(f'No attendance records found for {date_to_delete.strftime("%B %d, %Y")} to delete.', 'warning')
            return redirect(url_for('teacher_section_attendance_dates', section_id=section_id))

        for record in attendance_records_to_delete:
            db_session.delete(record)
        
        db_session.commit()
        flash(f'Attendance for {date_to_delete.strftime("%A, %B %d, %Y")} deleted successfully!', 'success')
    except Exception as e:
        db_session.rollback()
        app.logger.error(f"Error deleting attendance for date {attendance_date_str}: {e}", exc_info=True) # Log full traceback
        flash('An error occurred while deleting attendance. Please try again.', 'error')
    
    return redirect(url_for('teacher_section_attendance_dates', section_id=section_id))


if __name__ == '__main__':
    app.run(debug=True)
