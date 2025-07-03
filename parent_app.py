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
from models import Base, StudentInfo, Parent, Grade, SectionSubject, Attendance, SectionPeriod, Section, Strand, GradeLevel, GradingSystem, GradingComponent, GradableItem, StudentScore

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
    pool_size=20,   # Increased pool size for Supabase pooler
    max_overflow=10, # Allow 10 extra connections for short spikes
    pool_timeout=30,
)

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
    # Group by base student_id_number (before -S2)
    children_map = {}
    for student in students:
        base_id = student.student_id_number.split('-S2')[0]
        if base_id not in children_map:
            children_map[base_id] = {
                'base_id': base_id,
                'name': student.name,
                'first_name': student.name.split()[0],
                'last_name': ' '.join(student.name.split()[1:]) if len(student.name.split()) > 1 else '',
                'periods': []
            }
        # Fetch section, strand, grade_level
        section_period = g.session.query(SectionPeriod).filter_by(id=student.section_period_id).first()
        section = g.session.query(Section).filter_by(id=section_period.section_id).first() if section_period else None
        strand = g.session.query(Strand).filter_by(id=section.strand_id).first() if section and section.strand_id else None
        grade_level = g.session.query(GradeLevel).filter_by(id=section.grade_level_id).first() if section and section.grade_level_id else None
        children_map[base_id]['periods'].append({
            'id': student.id,
            'student_id_number': student.student_id_number,
            'section_name': section.name if section else '',
            'strand_name': strand.name if strand else '',
            'grade_level': grade_level.name if grade_level else '',
            'period_name': section_period.period_name if section_period else '',
            'school_year': section_period.school_year if section_period else '',
            'average_grade': student.average_grade if hasattr(student, 'average_grade') else None
        })
    children_with_periods = list(children_map.values())
    # Sort periods for each child: 1st Semester before 2nd Semester, and by school year ascending
    def period_sort_key(p):
        # Try to sort by school_year ascending, then by period_name (1st before 2nd)
        year = p.get('school_year', '')
        # Extract the first year as int for sorting
        try:
            year_int = int(year.split('-')[0])
        except Exception:
            year_int = 0
        # 1st Semester < 2nd Semester < Quarter 1 < Quarter 2 ...
        period_order = {
            '1st Semester': 1,
            '2nd Semester': 2,
            'Quarter 1': 3,
            'Quarter 2': 4,
            'Quarter 3': 5,
            'Quarter 4': 6
        }
        period_val = period_order.get(p.get('period_name', ''), 99)
        return (year_int, period_val)
    for child in children_with_periods:
        child['periods'] = sorted(child['periods'], key=period_sort_key)
    # Add overall average grade for each child
    for child in children_with_periods:
        grades = [p['average_grade'] for p in child['periods'] if p['average_grade'] is not None]
        child['overall_average_grade'] = round(sum(grades) / len(grades), 2) if grades else None
    return render_template('parent_dashboard.html', children_with_periods=children_with_periods)

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

    # --- Fetch all section periods for this student (for all periods/semesters) ---
    # For now, just use the current section_period_id
    section_period = g.session.query(SectionPeriod).filter_by(id=student.section_period_id).first()
    if not section_period:
        flash('Section period not found.', 'error')
        return redirect(url_for('parent_dashboard'))

    # Find all section periods for this student (by student_id_number)
    all_student_periods = g.session.query(StudentInfo).filter_by(student_id_number=student.student_id_number, parent_id=parent_id).all()
    period_ids = [s.section_period_id for s in all_student_periods]
    section_periods = g.session.query(SectionPeriod).filter(SectionPeriod.id.in_(period_ids)).all()
    period_map = {str(p.id): p for p in section_periods}

    # --- Fetch all grades for this student across all periods ---
    all_grades = g.session.query(Grade).filter(Grade.student_info_id.in_([s.id for s in all_student_periods])).all()
    all_section_subjects = g.session.query(SectionSubject).filter(SectionSubject.section_period_id.in_(period_ids)).all()
    all_section_subjects_map = {str(s.id): s for s in all_section_subjects}

    # --- Build nested structure: periods -> subjects -> details ---
    periods = {}
    for s in all_student_periods:
        period = period_map.get(str(s.section_period_id))
        if not period:
            continue
        period_key = (period.period_name, period.school_year)
        if period_key not in periods:
            periods[period_key] = {'subjects': {}}
        # Get all subjects for this period
        section_subjects = [subj for subj in all_section_subjects if subj.section_period_id == period.id]
        grades = [g for g in all_grades if g.student_info_id == s.id]
        for subject in section_subjects:
            subject_grades = [g for g in grades if g.section_subject_id == subject.id]
            # Fetch grading system and items for this subject
            grading_system = g.session.query(GradingSystem).filter_by(section_subject_id=subject.id).first()
            if not grading_system:
                continue
            components = g.session.query(GradingComponent).filter_by(system_id=grading_system.id).all()
            items = g.session.query(GradableItem).join(GradingComponent).filter(GradingComponent.system_id == grading_system.id).all()
            # Fetch scores for this student for all items in this subject
            scores = g.session.query(StudentScore).filter_by(student_info_id=s.id).all()
            scores_map = {sc.item_id: sc.score for sc in scores}
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
            periods[period_key]['subjects'][subject.subject_name] = {
                'total_grade': float(subject_grades[0].grade_value) if subject_grades else None,
                'details': subject_detail
            }

    # Sort periods by school year and period name
    sorted_periods = sorted(periods.items(), key=lambda x: (x[0][1], x[0][0]), reverse=True)

    return render_template('student_grades.html', student=student, periods=sorted_periods)

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
    # Build a dict: {(date, subject): {'status': ..., 'notes': ...}}
    attendance_map = {}
    for record, subject in attendance_records:
        attendance_map[(record.attendance_date, subject.subject_name)] = {
            'status': record.status,
            'notes': record.notes
        }
    # Build attendance_by_date for the template
    attendance_by_date = {}
    for date in all_dates:
        attendance_by_date[date] = {}
        for subject in subject_names:
            attendance_by_date[date][subject] = attendance_map.get((date, subject), {'status': 'Not Recorded', 'notes': None})
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
    app.run(debug=True, port=5001, host='0.0.0.0')  # Different port from main app 