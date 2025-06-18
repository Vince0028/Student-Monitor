from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, template_folder='student_templates')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'supersecretkey_for_development_only')

# Database connection details
DATABASE_URL = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///student_portal.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Models
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    assignments = db.relationship('Assignment', backref='student', lazy=True)
    grades = db.relationship('Grade', backref='student', lazy=True)
    attendance = db.relationship('Attendance', backref='student', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    due_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='upcoming') # upcoming, completed, past_due
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)

class Grade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(80), nullable=False)
    value = db.Column(db.Float, nullable=False)
    period = db.Column(db.String(40))
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False) # present, absent, late
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)

# Routes
@app.route('/')
def index():
    return redirect(url_for('student_login'))

@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        student = Student.query.filter_by(username=username).first()
        if student and student.check_password(password):
            session['student_id'] = student.id
            session['student_name'] = f"{student.first_name} {student.last_name}"
            return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    return render_template('student_login.html')

@app.route('/student/logout')
def student_logout():
    session.clear()
    return redirect(url_for('student_login'))

@app.route('/student/dashboard')
def student_dashboard():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    student = Student.query.get(session['student_id'])
    assignments = Assignment.query.filter_by(student_id=student.id).all()
    grades = Grade.query.filter_by(student_id=student.id).all()
    attendance = Attendance.query.filter_by(student_id=student.id).all()
    return render_template('student_dashboard.html', student=student, assignments=assignments, grades=grades, attendance=attendance)

@app.route('/student/assignments')
def student_assignments():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    student = Student.query.get(session['student_id'])
    subject = request.args.get('subject')
    status = request.args.get('status')
    query = Assignment.query.filter_by(student_id=student.id)
    if subject:
        query = query.filter_by(subject=subject)
    if status:
        query = query.filter_by(status=status)
    assignments = query.all()
    return render_template('student_assignments.html', student=student, assignments=assignments)

@app.route('/student/assignments/submit/<int:assignment_id>', methods=['GET', 'POST'])
def submit_assignment(assignment_id):
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    assignment = Assignment.query.get_or_404(assignment_id)
    if request.method == 'POST':
        assignment.status = 'completed'
        db.session.commit()
        flash('Assignment submitted successfully!', 'success')
        return redirect(url_for('student_assignments'))
    return render_template('submit_assignment.html', assignment=assignment)

@app.route('/student/grades')
def student_grades():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    student = Student.query.get(session['student_id'])
    grades = Grade.query.filter_by(student_id=student.id).all()
    return render_template('student_grades.html', student=student, grades=grades)

@app.route('/student/attendance')
def student_attendance():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    student = Student.query.get(session['student_id'])
    attendance = Attendance.query.filter_by(student_id=student.id).all()
    return render_template('student_attendance.html', student=student, attendance=attendance)

if __name__ == '__main__':
    if not os.path.exists('student_portal.db'):
        with app.app_context():
            db.create_all()
    app.run(debug=True) 