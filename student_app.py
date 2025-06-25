import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import uuid
from datetime import date, datetime, timedelta
import decimal

# Import SQLAlchemy components
from sqlalchemy import create_engine, Column, String, Date, Numeric, ForeignKey, DateTime, and_, or_, func, UniqueConstraint
from sqlalchemy.orm import sessionmaker, relationship, declarative_base, joinedload
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from dotenv import load_dotenv

# Assuming your models are in app.py, you need to import them
# This is a circular dependency, so it's better to move models to a separate file
# For now, we will import them here
from app import SectionSubject, Grade, SectionPeriod
from models import Quiz, StudentQuizResult, Base, StudentQuizAnswer

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
    pool_size=1,   # Supabase free tier allows max 2 connections
    max_overflow=0, # Allow 1 extra connection for short spikes
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
                session.permanent = True
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

    # Fetch grades and eagerly load subject and section period details
    grades = db_session.query(Grade).join(
        Grade.section_subject
    ).join(
        SectionSubject.section_period
    ).filter(
        Grade.student_info_id == student_id
    ).options(
        joinedload(Grade.section_subject).joinedload(SectionSubject.section_period)
    ).order_by(
        SectionPeriod.school_year.desc(),
        SectionPeriod.period_name
    ).all()

    # Calculate overall average grade
    overall_average = sum(float(g.grade_value) for g in grades) / len(grades) if grades else None

    grades_by_period = {}
    for grade in grades:
        period_key = f"{grade.section_subject.section_period.period_name} {grade.section_subject.section_period.school_year}"
        if period_key not in grades_by_period:
            grades_by_period[period_key] = {
                'period_name': grade.section_subject.section_period.period_name,
                'school_year': grade.section_subject.section_period.school_year,
                'grades': []
            }
        grades_by_period[period_key]['grades'].append(grade)

    return render_template('student_grades.html', grades_by_period=grades_by_period, overall_average=overall_average)

@app.route('/student/attendance')
@login_required
def student_attendance():
    student_id = uuid.UUID(session['student_id'])
    student = g.session.query(StudentInfo).filter_by(id=student_id).first()
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('student_login'))
    # Get all attendance records for this student
    attendance_records = g.session.query(Attendance).filter_by(student_info_id=student_id).order_by(Attendance.attendance_date.desc()).all()
    # Build a mapping from section_subject_id to subject_name
    section_subject_ids = {r.section_subject_id for r in attendance_records}
    if section_subject_ids:
        from app import SectionSubject
        subjects = g.session.query(SectionSubject).filter(SectionSubject.id.in_(section_subject_ids)).all()
        subject_map = {s.id: s.subject_name for s in subjects}
    else:
        subject_map = {}
    # Calculate summary statistics
    present_count = sum(1 for a in attendance_records if a.status == 'present')
    absent_count = sum(1 for a in attendance_records if a.status == 'absent')
    late_count = sum(1 for a in attendance_records if a.status == 'late')
    excused_count = sum(1 for a in attendance_records if a.status == 'excused')
    total_classes = len(attendance_records)
    attendance_rate = round(((present_count + late_count) / total_classes * 100), 1) if total_classes > 0 else 0
    # Group records by subject for display
    records_by_subject = {}
    for record in attendance_records:
        subject = subject_map.get(record.section_subject_id, 'Unknown')
        if subject not in records_by_subject:
            records_by_subject[subject] = []
        records_by_subject[subject].append(record)
    return render_template('student_attendance_history.html',
        student=student,
        attendance_records=attendance_records,
        present_count=present_count,
        absent_count=absent_count,
        late_count=late_count,
        excused_count=excused_count,
        total_classes=total_classes,
        attendance_rate=attendance_rate,
        records_by_subject=records_by_subject,
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
        if not current_password or not check_password_hash(student.password_hash, current_password):
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

@app.route('/student/quiz')
@login_required
def student_quiz():
    db_session = g.session
    student_id = session.get('student_id')
    student = db_session.query(StudentInfo).filter_by(id=student_id).first()
    quizzes = db_session.query(Quiz).filter_by(section_period_id=student.section_period_id).all()
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
    # Get all quizzes for this student's section_period
    all_quizzes = db_session.query(Quiz).filter_by(section_period_id=student.section_period_id).all()
    # Get quiz IDs the student has completed
    completed_quiz_ids = set(
        r.quiz_id for r in db_session.query(StudentQuizResult).filter_by(student_info_id=student_id)
    )
    # Filter quizzes the student has not taken
    upcoming_quizzes = [q for q in all_quizzes if q.id not in completed_quiz_ids]
    return render_template('student_quiz_templates/student_upcoming_quizzes.html', upcoming_quizzes=upcoming_quizzes)

@app.route('/student/quiz/completed')
@login_required
def student_completed_quizzes():
    db_session = g.session
    student_id = session.get('student_id')
    # Get all completed quiz results for this student
    completed_results = db_session.query(StudentQuizResult).filter_by(student_info_id=student_id).all()
    completed_quizzes = []
    import json
    from models import StudentQuizAnswer
    def format_number(n):
        return int(n) if n == int(n) else round(float(n), 1)
    for result in completed_results:
        quiz = db_session.query(Quiz).filter_by(id=result.quiz_id).first()
        is_essay_pending = False
        if quiz:
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
                'is_essay_pending': is_essay_pending
            })
    return render_template('student_quiz_templates/student_completed_quizzes.html', completed_quizzes=completed_quizzes)

@app.route('/student/quiz/<uuid:quiz_id>', methods=['GET', 'POST'])
@login_required
def take_quiz(quiz_id):
    student_id = uuid.UUID(session['student_id'])
    # Check if already completed
    existing_result = g.session.query(StudentQuizResult).filter_by(student_info_id=student_id, quiz_id=quiz_id).first()
    if existing_result:
        # Already completed, redirect to results
        return redirect(url_for('view_quiz_score', quiz_id=quiz_id))
    quiz = g.session.query(Quiz).filter_by(id=quiz_id).first()
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('student_quiz'))
    import json
    questions = json.loads(quiz.questions_json)
    if request.method == 'POST':
        print('--- QUIZ SUBMISSION DEBUG ---')
        print('Quiz ID:', quiz_id)
        print('Student ID:', student_id)
        print('Questions:', questions)
        print('Form data:', dict(request.form))
        total_score = 0
        total_points = 0
        essay_answers = []
        for question in questions:
            qid = str(question['id'])
            correct = False
            answer = request.form.get(f'answer-{qid}')
            if question['type'] == 'multiple_choice':
                if question.get('allowMultiple'):
                    selected = request.form.getlist(f'answer-{qid}[]')
                    selected_indices = set(int(i) for i in selected)
                    correct_indices = set(i for i, opt in enumerate(question['options']) if opt.get('isCorrect'))
                    print(f'MULTI: selected={selected_indices}, correct={correct_indices}')
                    if selected_indices == correct_indices and correct_indices:
                        correct = True
                else:
                    correct_index = next((i for i, opt in enumerate(question['options']) if opt.get('isCorrect')), None)
                    print(f'SINGLE: answer={answer}, correct_index={correct_index}')
                    if answer is not None and correct_index is not None and int(answer) == correct_index:
                        correct = True
            elif question['type'] == 'essay_type':
                # Always require teacher to check, do not auto-score
                essay_answers.append({'question_id': qid, 'answer_text': answer})
                correct = False
            elif question['type'] == 'true_false':
                if answer == (question.get('correctAnswer') or '').lower():
                    correct = True
            pts = int(question.get('points', 1))
            total_points += pts
            if correct:
                total_score += pts
        print(f'Total Score: {total_score}, Total Points: {total_points}')
        # Record completion in StudentQuizResult with error handling
        try:
            result = StudentQuizResult(
                student_info_id=student_id,
                quiz_id=quiz_id,
                score=total_score,
                total_points=total_points
            )
            g.session.add(result)
            g.session.flush()  # Get result.id for answers
            # Store essay answers
            for ans in essay_answers:
                essay = StudentQuizAnswer(
                    student_quiz_result_id=result.id,
                    question_id=ans['question_id'],
                    answer_text=ans['answer_text'],
                    score=None
                )
                g.session.add(essay)
            g.session.commit()
            print('StudentQuizResult and essay answers created and committed.')
            flash('Quiz submitted successfully!', 'success')
            return redirect(url_for('view_quiz_score', quiz_id=quiz_id))
        except Exception as e:
            g.session.rollback()
            print(f'Error submitting quiz: {e}')
            flash('An error occurred while submitting your quiz. Please try again.', 'error')
            return redirect(url_for('student_quiz'))
    return render_template('student_quiz_templates/student_take_quiz.html', quiz=quiz, questions=questions)

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
    app.run(debug=True, port=5002)  # Different port from parent app
