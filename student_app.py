import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import uuid
from datetime import date, datetime, timedelta, timezone
import decimal
from decimal import Decimal

# Import SQLAlchemy components
from sqlalchemy import create_engine, Column, String, Date, Numeric, ForeignKey, DateTime, and_, or_, func, UniqueConstraint
from sqlalchemy.orm import sessionmaker, relationship, declarative_base, joinedload
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from dotenv import load_dotenv
from sqlalchemy.sql import func

# Assuming your models are in app.py, you need to import them
# This is a circular dependency, so it's better to move models to a separate file
# For now, we will import them here
from app import SectionSubject, Grade, SectionPeriod
from models import Quiz, StudentQuizResult, Base, StudentQuizAnswer, StudentInfo, Parent, Section, GradingSystem, GradingComponent, GradableItem, StudentScore, Attendance

load_dotenv()

# --- Flask App Configuration ---
app = Flask(__name__, template_folder='student_templates')
app.secret_key = os.environ.get('STUDENT_FLASK_SECRET_KEY', 'student_secret_key_for_development_only')
app.permanent_session_lifetime = timedelta(days=30)
app.config['SESSION_COOKIE_NAME'] = 'sos_student_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True if using HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

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

@app.before_request
def make_session_permanent():
    session.permanent = True

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
    if request.method == 'POST':
        student_id_number = request.form.get('student_id_number')
        password = request.form.get('password')
        student = g.session.query(StudentInfo).filter_by(student_id_number=student_id_number).first()
        # Compare password as plain text
        if student and student.password_hash and password and student.password_hash == password:
            session.clear()
            session['student_id'] = str(student.id)
            flash('Login successful!', 'success')
            return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid student ID or password.', 'error')
    return render_template('student_login.html')

@app.route('/student/logout')
@login_required
def student_logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('student_login'))

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    if 'student_id' not in session:
        session.clear()
        return redirect(url_for('student_login'))
    student_id = uuid.UUID(session['student_id'])
    student = g.session.query(StudentInfo).filter_by(id=student_id).first()
    if not student:
        session.clear()
        flash('Student not found.', 'error')
        return redirect(url_for('student_login'))
    # Get latest grades
    latest_grades = g.session.query(Grade).filter_by(student_info_id=student.id).order_by(Grade.created_at.desc()).limit(5).all()
    # Calculate average grade
    grades = g.session.query(Grade.grade_value).filter_by(student_info_id=student.id).all()
    average_grade = sum(float(g[0]) for g in grades) / len(grades) if grades else None
    # Get recent attendance
    recent_attendance = g.session.query(Attendance).filter_by(student_info_id=student.id).order_by(Attendance.attendance_date.desc()).limit(10).all()

    # --- Quiz counts ---
    # All quizzes for this student's section_period
    all_quizzes = g.session.query(Quiz).filter_by(section_period_id=student.section_period_id).all()
    # Quiz IDs the student has completed
    completed_quiz_ids = set(
        r.quiz_id for r in g.session.query(StudentQuizResult).filter_by(student_info_id=student_id)
    )
    available_quiz_count = len([q for q in all_quizzes if q.id not in completed_quiz_ids])
    completed_quiz_count = len(completed_quiz_ids)

    return render_template('student_dashboard.html', student=student, latest_grades=latest_grades, average_grade=average_grade, recent_attendance=recent_attendance, available_quiz_count=available_quiz_count, completed_quiz_count=completed_quiz_count)

@app.route('/student/grades')
@login_required
def student_grades():
    db_session = g.session
    student_id = session.get('student_id')
    student = db_session.query(StudentInfo).filter_by(id=student_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('student_login'))

    base_id = student.student_id_number.split('-S2')[0]
    all_student_infos = db_session.query(StudentInfo).filter(
        StudentInfo.student_id_number.like(f"{base_id}%")
    ).all()
    all_student_ids = [info.id for info in all_student_infos]

    # Fetch all section periods for this student (1st and 2nd Sem, etc)
    section_periods = db_session.query(SectionPeriod).join(StudentInfo, SectionPeriod.id == StudentInfo.section_period_id).filter(
        StudentInfo.id.in_(all_student_ids)
    ).order_by(SectionPeriod.school_year.desc(), SectionPeriod.period_name).all()

    # Fetch all grades for all periods for this student
    grades = db_session.query(Grade).join(
        Grade.section_subject
    ).join(
        SectionSubject.section_period
    ).filter(
        Grade.student_info_id.in_(all_student_ids)
    ).options(
        joinedload(Grade.section_subject).joinedload(SectionSubject.section_period)
    ).order_by(
        SectionPeriod.school_year.desc(),
        SectionPeriod.period_name
    ).all()

    # Group grades by period (only if grades exist for that period)
    grades_by_period = {}
    activities_by_period = {}
    for grade in grades:
        period_key = f"{grade.section_subject.section_period.period_name} {grade.section_subject.section_period.school_year}"
        if period_key not in grades_by_period:
            grades_by_period[period_key] = {
                'period_name': grade.section_subject.section_period.period_name,
                'school_year': grade.section_subject.section_period.school_year,
                'grades': []
            }
            activities_by_period[period_key] = {}
        display_teacher = grade.section_subject.assigned_teacher_name if hasattr(grade.section_subject, 'assigned_teacher_name') else 'N/A'
        grade.display_teacher = display_teacher
        grades_by_period[period_key]['grades'].append(grade)

        # --- Fetch activities for this subject ---
        subject = grade.section_subject
        grading_system = db_session.query(GradingSystem).filter_by(section_subject_id=subject.id).first()
        if not grading_system:
            continue
        components = db_session.query(GradingComponent).filter_by(system_id=grading_system.id).all()
        items = db_session.query(GradableItem).join(GradingComponent).filter(GradingComponent.system_id == grading_system.id).all()
        scores = db_session.query(StudentScore).filter_by(student_info_id=grade.student_info_id).all()
        scores_map = {s.item_id: s.score for s in scores}
        # Organize by component
        subject_activities = []
        for component in components:
            comp_items = [i for i in items if i.component_id == component.id]
            for item in comp_items:
                subject_activities.append({
                    'component': component.name,
                    'weight': component.weight,
                    'item_title': item.title,
                    'max_score': float(item.max_score),
                    'score': float(scores_map.get(item.id, 0)),
                })
        activities_by_period[period_key][subject.subject_name] = subject_activities

    # For each section period, if there are no grades, add an empty entry for the template
    for period in section_periods:
        period_key = f"{period.period_name} {period.school_year}"
        if period_key not in grades_by_period:
            grades_by_period[period_key] = {
                'period_name': period.period_name,
                'school_year': period.school_year,
                'grades': []
            }
            activities_by_period[period_key] = {}

    # Calculate overall average only from actual grades
    all_grade_values = [float(g.grade_value) for g in grades]
    overall_average = sum(all_grade_values) / len(all_grade_values) if all_grade_values else None

    return render_template('student_grades.html', grades_by_period=grades_by_period, overall_average=overall_average, activities_by_period=activities_by_period)

@app.route('/student/attendance')
@login_required
def student_attendance():
    if 'student_id' not in session:
        session.clear()
        return redirect(url_for('student_login'))
    student_id = uuid.UUID(session['student_id'])
    student = g.session.query(StudentInfo).filter_by(id=student_id).first()
    if not student:
        session.clear()
        flash('Student not found.', 'error')
        return redirect(url_for('student_login'))

    # Get the base student_id_number (before -S2)
    base_id = student.student_id_number.split('-S2')[0]

    # Find all StudentInfo records for this base ID (1st and 2nd sem, etc)
    all_student_infos = g.session.query(StudentInfo).filter(
        StudentInfo.student_id_number.like(f"{base_id}%")
    ).all()
    all_student_ids = [info.id for info in all_student_infos]

    # Get all attendance records for these student_info ids
    attendance_records = g.session.query(Attendance).filter(
        Attendance.student_info_id.in_(all_student_ids)
    ).order_by(Attendance.attendance_date.desc()).all()

    # Build a mapping from section_subject_id to subject_name
    section_subject_ids = {r.section_subject_id for r in attendance_records}
    if section_subject_ids:
        from app import SectionSubject
        subjects = g.session.query(SectionSubject).filter(SectionSubject.id.in_(section_subject_ids)).all()
        subject_map = {s.id: s.subject_name for s in subjects}
    else:
        subject_map = {}

    # --- Filtering logic ---
    status_filter = request.args.get('status', '').strip().lower()
    search = request.args.get('search', '').strip().lower()
    subject_filter = request.args.get('subject', '').strip()

    filtered_records = []
    for record in attendance_records:
        if status_filter and record.status != status_filter:
            continue
        if subject_filter and str(record.section_subject_id) != subject_filter:
            continue
        if search:
            subject_name = subject_map.get(record.section_subject_id, '').lower()
            if search not in subject_name:
                continue
        filtered_records.append(record)

    # Group filtered_records by period (semester/quarter)
    period_map = {}
    section_period_cache = {}
    for record in filtered_records:
        student_info = next((info for info in all_student_infos if info.id == record.student_info_id), None)
        period_key = "Unknown Period"
        if student_info:
            sp_id = student_info.section_period_id
            if sp_id not in section_period_cache:
                section_period = g.session.query(SectionPeriod).filter_by(id=sp_id).first()
                section_period_cache[sp_id] = section_period
            else:
                section_period = section_period_cache[sp_id]
            if section_period:
                period_name = section_period.period_name
                school_year = section_period.school_year
                period_key = f"{period_name} {school_year}"
        if period_key not in period_map:
            period_map[period_key] = []
        period_map[period_key].append(record)

    # --- Sort periods so 1st semester is on top, 2nd semester below ---
    def period_sort_key(period):
        # Example: '1ST SEMESTER 2025-2026'
        import re
        match = re.match(r"(\d)(ST|ND|RD|TH) SEMESTER (\d{4}-\d{4})", period.upper())
        if match:
            num = int(match.group(1))
            year = match.group(3)
            # Lower num (1st) should come first
            return (year, num)
        # Fallback: sort by year descending, then name
        parts = period.rsplit(' ', 1)
        if len(parts) == 2:
            return (parts[1], parts[0])
        return (period,)
    sorted_period_items = sorted(period_map.items(), key=lambda x: period_sort_key(x[0]), reverse=False)
    sorted_period_map = dict(sorted_period_items)

    # Calculate summary statistics for all records (can also do per period if needed)
    present_count = sum(1 for a in filtered_records if a.status == 'present')
    absent_count = sum(1 for a in filtered_records if a.status == 'absent')
    late_count = sum(1 for a in filtered_records if a.status == 'late')
    excused_count = sum(1 for a in filtered_records if a.status == 'excused')
    total_classes = len(filtered_records)
    attendance_rate = round(((present_count + late_count) / total_classes * 100), 1) if total_classes > 0 else 0

    return render_template('student_attendance_history.html',
        student=student,
        attendance_records=filtered_records,
        present_count=present_count,
        absent_count=absent_count,
        late_count=late_count,
        excused_count=excused_count,
        total_classes=total_classes,
        attendance_rate=attendance_rate,
        records_by_period=sorted_period_map,
        subject_map=subject_map)

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
        if not current_password or not (
            student.password_hash == current_password or
            check_password_hash(student.password_hash, current_password)
        ):
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('student_profile'))
        if new_password:
            if new_password != confirm_password:
                flash('New passwords do not match.', 'error')
                return redirect(url_for('student_profile'))
            student.password_hash = new_password
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

@app.route('/student/quiz')
@login_required
def student_quiz():
    db_session = g.session
    student_id = session.get('student_id')
    student = db_session.query(StudentInfo).filter_by(id=student_id).first()
    quizzes = db_session.query(Quiz).filter_by(section_period_id=student.section_period_id, status='published').all()
    # Find pending quizzes for this student
    import json
    pending_quizzes = []
    for quiz in quizzes:
        try:
            questions = json.loads(quiz.questions_json or '[]')
        except Exception:
            questions = []
        essay_qids = [str(q['id']) for q in questions if q.get('type') == 'essay_type']
        if not essay_qids:
            continue
        # Get this student's attempt for this quiz
        sqr = db_session.query(StudentQuizResult).filter_by(student_info_id=student_id, quiz_id=quiz.id).first()
        if not sqr:
            continue  # Not taken yet
        # Check if any essay_type is unscored
        unscored = db_session.query(StudentQuizAnswer).filter(
            StudentQuizAnswer.student_quiz_result_id == sqr.id,
            StudentQuizAnswer.question_id.in_(essay_qids),
            StudentQuizAnswer.score.is_(None)
        ).first()
        if unscored:
            pending_quizzes.append(quiz)
    return render_template('student_quiz_templates/student_quiz_dashboard.html', quizzes=quizzes, pending_quizzes=pending_quizzes)

@app.route('/student/quiz/upcoming')
@login_required
def student_upcoming_quizzes():
    db_session = g.session
    student_id = session.get('student_id')
    student = db_session.query(StudentInfo).filter_by(id=student_id).first()
    all_quizzes = db_session.query(Quiz).filter_by(section_period_id=student.section_period_id, status='published').all()
    from models import SectionSubject, StudentQuizResult
    import json
    from datetime import datetime, timezone
    from decimal import Decimal
    upcoming_quizzes = []
    for q in all_quizzes:
        result = db_session.query(StudentQuizResult).filter_by(student_info_id=student_id, quiz_id=q.id).first()
        # --- Timer logic: auto-complete if expired ---
        expired = False
        if q.time_limit_minutes and result and not result.completed_at:
            now = datetime.now(timezone.utc)
            started_at = result.started_at
            if started_at:
                if started_at.tzinfo is None or started_at.tzinfo.utcoffset(started_at) is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                elapsed = (now - started_at).total_seconds()
                if elapsed >= q.time_limit_minutes * 60:
                    # Auto-complete
                    result.completed_at = now
                    # Set score to 0 if not graded
                    score_is_zero = (result.score is None) or (isinstance(result.score, Decimal) and result.score == Decimal(0))
                    points_is_zero = (result.total_points is None) or (isinstance(result.total_points, Decimal) and result.total_points == Decimal(0))
                    if score_is_zero and points_is_zero:
                        questions = json.loads(q.questions_json or '[]')
                        result.score = Decimal(0)
                        result.total_points = Decimal(str(sum(float(qq.get('points', 1)) for qq in questions)))
                    db_session.commit()
                    expired = True
        # Show if not started or in-progress (not completed and not just expired)
        if (not result or not result.completed_at) and not expired:
            subject_name = None
            if q.subject_id:
                subj = db_session.query(SectionSubject).filter_by(id=q.subject_id).first()
                subject_name = subj.subject_name if subj else None
            q.subject_name = subject_name
            q.deadline = getattr(q, 'deadline', None)
            # --- Timer logic for display ---
            q.time_left = None
            if q.time_limit_minutes:
                now = datetime.now(timezone.utc)
                started_at = None
                if result and hasattr(result, 'started_at') and result.started_at:
                    started_at = result.started_at
                    if started_at.tzinfo is None or started_at.tzinfo.utcoffset(started_at) is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)
                    elapsed = (now - started_at).total_seconds()
                    q.time_left = max(0, int(q.time_limit_minutes * 60 - elapsed))
                # If not started, do not set time_left (leave as None)
            upcoming_quizzes.append(q)
    return render_template('student_quiz_templates/student_upcoming_quizzes.html', upcoming_quizzes=upcoming_quizzes)

@app.route('/student/quiz/completed')
@login_required
def student_completed_quizzes():
    db_session = g.session
    student_id = session.get('student_id')
    from models import StudentQuizResult, StudentQuizAnswer, SectionSubject
    completed_results = db_session.query(StudentQuizResult).filter_by(student_info_id=student_id).filter(StudentQuizResult.completed_at.isnot(None)).all()
    completed_quizzes = []
    import json
    def format_number(n):
        return int(n) if n == int(n) else round(float(n), 1)
    for result in completed_results:
        quiz = db_session.query(Quiz).filter_by(id=result.quiz_id).first()
        is_essay_pending = False
        subject_name = None
        if quiz:
            if quiz.subject_id:
                subj = db_session.query(SectionSubject).filter_by(id=quiz.subject_id).first()
                subject_name = subj.subject_name if subj else None
            questions = json.loads(quiz.questions_json or '[]')
            essay_qids = [str(q['id']) for q in questions if q.get('type') == 'essay_type']
            if essay_qids:
                answers = db_session.query(StudentQuizAnswer).filter(
                    StudentQuizAnswer.student_quiz_result_id == result.id,
                    StudentQuizAnswer.question_id.in_(essay_qids),
                    StudentQuizAnswer.score.is_(None)
                ).all()
                if answers:
                    is_essay_pending = True
            completed_quizzes.append({
                'id': quiz.id,
                'title': quiz.title,
                'score': format_number(result.score),
                'total_points': format_number(result.total_points),
                'is_essay_pending': is_essay_pending,
                'subject_name': subject_name
            })
    return render_template('student_quiz_templates/student_completed_quizzes.html', completed_quizzes=completed_quizzes)

@app.route('/student/quiz/<uuid:quiz_id>', methods=['GET', 'POST'])
@login_required
def take_quiz(quiz_id):
    from decimal import Decimal  # Ensure Decimal is always in scope
    student_id = uuid.UUID(session['student_id'])
    quiz = g.session.query(Quiz).filter_by(id=quiz_id).first()
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('student_quiz'))
    import json
    questions = json.loads(quiz.questions_json)
    time_limit = quiz.time_limit_minutes
    now = datetime.now(timezone.utc)
    result = g.session.query(StudentQuizResult).filter_by(student_info_id=student_id, quiz_id=quiz_id).first()
    started_at = None
    time_left = None
    # --- Always create a result if not exists, regardless of timer ---
    if not result:
        result = StudentQuizResult(
            student_info_id=student_id,
            quiz_id=quiz_id,
            score=0,
            total_points=0,
            started_at=now
        )
        g.session.add(result)
        g.session.commit()
        started_at = now
    else:
        started_at = getattr(result, 'started_at', None)
        if not started_at:
            result.started_at = now
            g.session.commit()
            started_at = now
    # --- Timer logic only if time_limit is set ---
    if time_limit:
        if started_at:
            elapsed = (now - started_at).total_seconds()
            time_left = int(time_limit * 60 - elapsed)
            if time_left <= 0:
                # Auto-submit: mark as completed if not already
                if result and (result.completed_at is None):
                    result.completed_at = now  # type: ignore
                    # Optionally, set score to 0 if not already graded
                    score_is_zero = (result.score is None) or (isinstance(result.score, Decimal) and result.score == Decimal(0))
                    points_is_zero = (result.total_points is None) or (isinstance(result.total_points, Decimal) and result.total_points == Decimal(0))
                    if score_is_zero and points_is_zero:
                        result.score = Decimal(0)  # type: ignore
                        result.total_points = Decimal(str(sum(float(q.get('points', 1)) for q in questions)))  # type: ignore
                    g.session.commit()
                flash('Time is up! Your quiz was auto-submitted.')
                return redirect(url_for('view_quiz_score', quiz_id=quiz_id))
    if request.method == 'POST':
        if time_limit and time_left is not None and time_left <= 0:
            flash('Time is up! Your quiz was auto-submitted.')
            return redirect(url_for('view_quiz_score', quiz_id=quiz_id))
        total_score = 0
        total_points = 0
        answers_to_store = []
        for question in questions:
            qid = str(question['id'])
            correct = False
            answer = request.form.get(f'answer-{qid}')
            pts = float(question.get('points', 1))
            if question['type'] == 'multiple_choice':
                if question.get('allowMultiple'):
                    selected = request.form.getlist(f'answer-{qid}[]')
                    selected_indices = set(int(i) for i in selected)
                    correct_indices = set(i for i, opt in enumerate(question['options']) if opt.get('isCorrect'))
                    if selected_indices == correct_indices and correct_indices:
                        correct = True
                else:
                    correct_index = next((i for i, opt in enumerate(question['options']) if opt.get('isCorrect')), None)
                    if answer is not None and correct_index is not None and int(answer) == correct_index:
                        correct = True
                answer_score = pts if correct else 0
                answers_to_store.append({
                    'question_id': qid,
                    'answer_text': json.dumps(request.form.getlist(f'answer-{qid}[]')) if question.get('allowMultiple') else answer,
                    'score': answer_score
                })
            elif question['type'] == 'essay_type':
                answers_to_store.append({
                    'question_id': qid,
                    'answer_text': answer,
                    'score': None
                })
            elif question['type'] == 'true_false':
                if answer == (question.get('correctAnswer') or '').lower():
                    correct = True
                answer_score = pts if correct else 0
                answers_to_store.append({
                    'question_id': qid,
                    'answer_text': answer,
                    'score': answer_score
                })
            total_points += pts
            if correct:
                total_score += pts
        try:
            from decimal import Decimal, ROUND_HALF_UP
            dec_score = Decimal(str(total_score)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            dec_points = Decimal(str(total_points)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            result.score = dec_score  # type: ignore
            result.total_points = dec_points  # type: ignore
            result.completed_at = now  # type: ignore
            g.session.flush()
            for ans in answers_to_store:
                answer_obj = StudentQuizAnswer(
                    student_quiz_result_id=result.id,
                    question_id=ans['question_id'],
                    answer_text=ans['answer_text'],
                    score=ans['score']
                )
                g.session.add(answer_obj)
            g.session.commit()
            flash('Quiz submitted successfully!', 'success')
            return redirect(url_for('view_quiz_score', quiz_id=quiz_id))
        except Exception as e:
            g.session.rollback()
            flash('An error occurred while submitting your quiz. Please try again.', 'error')
            return redirect(url_for('student_quiz'))
    return render_template('student_quiz_templates/student_take_quiz.html', quiz=quiz, questions=questions, time_left=time_left, time_limit=time_limit)

@app.route('/student/quiz/<uuid:quiz_id>/score')
@login_required
def view_quiz_score(quiz_id):
    student_id = uuid.UUID(session['student_id'])
    quiz = g.session.query(Quiz).filter_by(id=quiz_id).first()
    result = g.session.query(StudentQuizResult).filter_by(student_info_id=student_id, quiz_id=quiz_id).first()
    if not quiz or not result:
        flash('Quiz or result not found.', 'error')
        return redirect(url_for('student_quiz'))
    def format_number(n):
        return int(n) if n == int(n) else round(float(n), 1)
    score = format_number(result.score)
    total_points = format_number(result.total_points)
    return render_template('student_quiz_templates/student_quiz_results.html', quiz_title=quiz.title, score=score, total_questions=total_points)

if __name__ == '__main__':
    # To access on your mobile device, run with host='0.0.0.0' and your desired port (e.g., 5002):
    # app.run(host='0.0.0.0', port=5002, debug=True)
    app.run(debug=True, port=5002, host='0.0.0.0')  # Default: localhost only
