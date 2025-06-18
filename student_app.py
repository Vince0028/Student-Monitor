from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app import StudentInfo, DATABASE_URL

app = Flask(__name__, template_folder='student_templates')
app.secret_key = 'your-secret-key-here'

# Create database session
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
db_session = Session()

# --- Student Login ---
@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        student_id = request.form['student_id_number']
        password = request.form['password']
        
        # Query student with password_hash field for authentication
        student = db_session.query(StudentInfo).filter_by(student_id_number=student_id).first()
        
        if student and student.password_hash and student.password_hash == password:
            session['student_id'] = str(student.id)
            session['student_name'] = student.name
            session['student_id_number'] = student.student_id_number
            return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid student ID or password', 'error')
    
    return render_template('student_login.html')

# --- Student Dashboard ---
@app.route('/student/dashboard')
def student_dashboard():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    return render_template('student_dashboard.html')

# --- Assignments Overview ---
@app.route('/student/assignments')
def student_assignments():
    # TODO: Query assignments for the logged-in student
    return render_template('student_assignments.html')

# --- Submit Assignment ---
@app.route('/student/assignments/submit', methods=['GET', 'POST'])
def student_submit_assignment():
    # TODO: Handle assignment submission
    return render_template('student_submit_assignment.html')

# --- Completed Assignments ---
@app.route('/student/assignments/completed')
def student_assignments_completed():
    # TODO: Query completed assignments
    return render_template('student_assignments_completed.html')

# --- Past Due Assignments ---
@app.route('/student/assignments/past_due')
def student_assignments_past_due():
    # TODO: Query past due assignments
    return render_template('student_assignments_past_due.html')

# --- Upcoming Assignments ---
@app.route('/student/assignments/upcoming')
def student_assignments_upcoming():
    # TODO: Query upcoming assignments
    return render_template('student_assignments_upcoming.html')

# --- Grades Summary ---
@app.route('/student/grades')
def student_grades():
    # TODO: Query grades for the logged-in student
    return render_template('student_grades.html')

# --- Attendance ---
@app.route('/student/attendance')
def student_attendance():
    # TODO: Query attendance records for the logged-in student
    return render_template('student_attendance.html')

# --- Student Logout ---
@app.route('/student/logout')
def student_logout():
    session.clear()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('student_login'))

@app.route('/')
def index():
    return redirect(url_for('student_login'))

if __name__ == '__main__':
    app.run(debug=True, port=5002)  