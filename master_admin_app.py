import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
import uuid
from sqlalchemy.exc import IntegrityError
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import click

# Load environment variables from .env
load_dotenv()



app = Flask(__name__, template_folder='master_admin_templates', static_folder='master_admin_static')
app.secret_key = 'supersecretkey'  # Change this in production

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Minimal models for read-only display
class GradeLevel(db.Model):
    __tablename__ = 'grade_levels'
    id = db.Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(50), unique=True, nullable=False)
    level_type = db.Column(db.String(10), nullable=False)

class Strand(db.Model):
    __tablename__ = 'strands'
    id = db.Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(255), nullable=False)
    grade_level_id = db.Column(PG_UUID(as_uuid=True), db.ForeignKey('grade_levels.id'), nullable=False)
    grade_level = db.relationship('GradeLevel', backref='strands')

# Hardcoded admin credentials are no longer needed, we will use the database.

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        user = User.query.filter_by(username=username, user_type='admin').first()
        print(f"Login attempt: {username}, found user: {user is not None}, user_type: {getattr(user, 'user_type', None)}")

        if user and check_password_hash(user.password_hash, password):
            session['admin_logged_in'] = True
            session['admin_username'] = user.username
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials. Please check your username and password.', 'danger')
            
    return render_template('login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    admin_user = User.query.filter_by(username=session.get('admin_username')).first()
    if admin_user:
        admin_name = f"{admin_user.firstname} {admin_user.lastname}".strip()
    else:
        admin_name = session.get('admin_username', 'Admin')
    return render_template('admin_dashboard.html', admin_name=admin_name)

@app.route('/admin/strands')
def manage_strands():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    # Query real strands and their grade levels
    strands = db.session.query(Strand).join(GradeLevel).order_by(Strand.name).all()
    strand_list = [
        {
            'id': str(s.id),
            'name': s.name,
            'grade_level': s.grade_level.name if s.grade_level else 'N/A'
        }
        for s in strands
    ]
    return render_template('manage_strands.html', strands=strand_list)

@app.route('/admin/strands/add', methods=['GET', 'POST'])
def add_strand_admin():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    grade_levels = GradeLevel.query.order_by(GradeLevel.name).all()
    if request.method == 'POST':
        name = request.form['name'].strip()
        grade_level_id = request.form['grade_level_id']
        if not name or not grade_level_id:
            flash('Strand name and grade level are required.', 'danger')
            return render_template('add_strand_admin.html', grade_levels=grade_levels)
        try:
            new_strand = Strand(name=name, grade_level_id=grade_level_id)
            db.session.add(new_strand)
            db.session.commit()
            flash('Strand added successfully!', 'success')
            return redirect(url_for('manage_strands'))
        except IntegrityError:
            db.session.rollback()
            flash('A strand with that name already exists for the selected grade level.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while adding the strand.', 'danger')
    return render_template('add_strand_admin.html', grade_levels=grade_levels)

@app.route('/admin/strands/<strand_id>/edit', methods=['GET', 'POST'])
def edit_strand_admin(strand_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    strand = Strand.query.get(strand_id)
    if not strand:
        flash('Strand not found.', 'danger')
        return redirect(url_for('manage_strands'))
    grade_levels = GradeLevel.query.order_by(GradeLevel.name).all()
    if request.method == 'POST':
        name = request.form['name'].strip()
        grade_level_id = request.form['grade_level_id']
        if not name or not grade_level_id:
            flash('Strand name and grade level are required.', 'danger')
            return render_template('edit_strand_admin.html', strand=strand, grade_levels=grade_levels)
        try:
            strand.name = name
            strand.grade_level_id = grade_level_id
            db.session.commit()
            flash('Strand updated successfully!', 'success')
            return redirect(url_for('manage_strands'))
        except IntegrityError:
            db.session.rollback()
            flash('A strand with that name already exists for the selected grade level.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while updating the strand.', 'danger')
    return render_template('edit_strand_admin.html', strand=strand, grade_levels=grade_levels)

@app.route('/admin/strands/<strand_id>/delete', methods=['POST'])
def delete_strand_admin(strand_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    strand = Strand.query.get(strand_id)
    if not strand:
        flash('Strand not found.', 'danger')
        return redirect(url_for('manage_strands'))
    try:
        db.session.delete(strand)
        db.session.commit()
        flash('Strand deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while deleting the strand.', 'danger')
    return redirect(url_for('manage_strands'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    return redirect(url_for('admin_login'))

# --- Section Management ---
class Section(db.Model):
    __tablename__ = 'sections'
    id = db.Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(255), nullable=False)
    grade_level_id = db.Column(PG_UUID(as_uuid=True), db.ForeignKey('grade_levels.id'), nullable=False)
    strand_id = db.Column(PG_UUID(as_uuid=True), db.ForeignKey('strands.id'))
    grade_level = db.relationship('GradeLevel', backref='sections')
    strand = db.relationship('Strand', backref='sections')

@app.route('/admin/sections')
def manage_sections():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    sections = db.session.query(Section).join(GradeLevel).order_by(Section.name).all()
    section_list = [
        {
            'id': str(s.id),
            'name': s.name,
            'grade_level': s.grade_level.name if s.grade_level else 'N/A',
            'strand': s.strand.name if s.strand else 'N/A'
        }
        for s in sections
    ]
    return render_template('manage_sections.html', sections=section_list)

@app.route('/admin/sections/add', methods=['GET', 'POST'])
def add_section_admin():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    grade_levels = GradeLevel.query.order_by(GradeLevel.name).all()
    strands = Strand.query.order_by(Strand.name).all()
    if request.method == 'POST':
        name = request.form['name'].strip()
        grade_level_id = request.form['grade_level_id']
        strand_id = request.form.get('strand_id') or None
        if not name or not grade_level_id:
            flash('Section name and grade level are required.', 'danger')
            return render_template('add_section_admin.html', grade_levels=grade_levels, strands=strands)
        try:
            new_section = Section(name=name, grade_level_id=grade_level_id, strand_id=strand_id)
            db.session.add(new_section)
            db.session.commit()
            flash('Section added successfully!', 'success')
            return redirect(url_for('manage_sections'))
        except IntegrityError:
            db.session.rollback()
            flash('A section with that name already exists for the selected grade level/strand.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while adding the section.', 'danger')
    return render_template('add_section_admin.html', grade_levels=grade_levels, strands=strands)

@app.route('/admin/sections/<section_id>/edit', methods=['GET', 'POST'])
def edit_section_admin(section_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    section = Section.query.get(section_id)
    if not section:
        flash('Section not found.', 'danger')
        return redirect(url_for('manage_sections'))
    grade_levels = GradeLevel.query.order_by(GradeLevel.name).all()
    strands = Strand.query.order_by(Strand.name).all()
    if request.method == 'POST':
        name = request.form['name'].strip()
        grade_level_id = request.form['grade_level_id']
        strand_id = request.form.get('strand_id') or None
        if not name or not grade_level_id:
            flash('Section name and grade level are required.', 'danger')
            return render_template('edit_section_admin.html', section=section, grade_levels=grade_levels, strands=strands)
        try:
            section.name = name
            section.grade_level_id = grade_level_id
            section.strand_id = strand_id
            db.session.commit()
            flash('Section updated successfully!', 'success')
            return redirect(url_for('manage_sections'))
        except IntegrityError:
            db.session.rollback()
            flash('A section with that name already exists for the selected grade level/strand.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while updating the section.', 'danger')
    return render_template('edit_section_admin.html', section=section, grade_levels=grade_levels, strands=strands)

@app.route('/admin/sections/<section_id>/delete', methods=['POST'])
def delete_section_admin(section_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    section = Section.query.get(section_id)
    if not section:
        flash('Section not found.', 'danger')
        return redirect(url_for('manage_sections'))
    try:
        db.session.delete(section)
        db.session.commit()
        flash('Section deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while deleting the section.', 'danger')
    return redirect(url_for('manage_sections'))

# --- User Management ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = db.Column(db.String(255), unique=True, nullable=False)
    user_type = db.Column(db.String(10), nullable=False)
    specialization = db.Column(db.String(255))
    grade_level_assigned = db.Column(db.String(50))
    firstname = db.Column(db.String(255))
    lastname = db.Column(db.String(255))
    middlename = db.Column(db.String(255))
    password_hash = db.Column(db.String(255))

# --- Admin Log Model ---
class AdminLog(db.Model):
    __tablename__ = 'admin_logs'
    id = db.Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_id = db.Column(PG_UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    admin_username = db.Column(db.String(255), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    target_type = db.Column(db.String(50), nullable=False)
    target_id = db.Column(PG_UUID(as_uuid=True), nullable=True)
    target_name = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    timestamp = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

# --- Helper Functions for Logging ---
def get_client_info(request):
    """Helper function to get client IP and user agent"""
    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip_address and ',' in ip_address:
        ip_address = ip_address.split(',')[0].strip()
    user_agent = request.headers.get('User-Agent', 'Unknown')
    return ip_address, user_agent

def create_admin_log_entry(db_session, admin_id, admin_username, action_type, target_type, target_id, target_name, details=None, request=None):
    """
    Helper function to create admin log entries
    """
    try:
        ip_address, user_agent = get_client_info(request) if request else (None, None)
        log_entry = AdminLog(
            admin_id=admin_id,
            admin_username=admin_username,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db_session.add(log_entry)
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        print(f"Error creating admin log: {e}")
        return False

@app.route('/admin/admin_logs')
def admin_logs():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    logs = AdminLog.query.order_by(AdminLog.timestamp.desc()).all()
    return render_template('admin_logs.html', logs=logs)

@app.route('/admin/teacher_logs')
def teacher_logs():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    logs = TeacherLog.query.order_by(TeacherLog.timestamp.desc()).all()
    return render_template('teacher_logs.html', logs=logs)

# Add Parent model for admin viewing
class Parent(db.Model):
    __tablename__ = 'parents'
    id = db.Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    first_name = db.Column(db.String(255), nullable=False)
    last_name = db.Column(db.String(255), nullable=False)
    phone_number = db.Column(db.String(50), nullable=True)
    # created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

# --- StudentInfo Model for Admin Read-Only Display ---
class StudentInfo(db.Model):
    __tablename__ = 'students_info'
    id = db.Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(255), nullable=False)
    student_id_number = db.Column(db.String(255), unique=True, nullable=False)
    gender = db.Column(db.String(10), nullable=True)

@app.route('/admin/users')
def manage_users():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    user_type = request.args.get('user_type', 'admin')
    search = request.args.get('search', '').strip()
    grade_level = request.args.get('grade_level', '')
    strand = request.args.get('strand', '')
    grade_levels = [f'Grade {i}' for i in range(7, 13)]
    strands = ['STEM', 'ABM', 'HUMMS', 'HE', 'EIM']
    normalized_grade_level = grade_level
    users = []
    if user_type == 'parent':
        query = Parent.query
        if search:
            query = query.filter(Parent.username.ilike(f'%{search}%'))
        parents = query.order_by(Parent.username.asc()).all()
        users = [
            {
                'id': str(p.id),
                'username': p.username,
                'user_type': 'parent',
                'email': p.email,
                'first_name': p.first_name,
                'last_name': p.last_name
            }
            for p in parents
        ]
    elif user_type == 'student':
        query = StudentInfo.query
        if search:
            query = query.filter(StudentInfo.name.ilike(f'%{search}%') | StudentInfo.student_id_number.ilike(f'%{search}%'))
        students = query.order_by(StudentInfo.name.asc()).all()
        users = [
            {
                'id': str(s.id),
                'lrn': s.student_id_number,
                'name': s.name,
                'gender': s.gender
            }
            for s in students
        ]
    else:
        query = User.query
        if user_type:
            query = query.filter_by(user_type=user_type)
        if user_type == 'student' and grade_level:
            grade_level_options = [grade_level]
            if grade_level.startswith('Grade '):
                grade_level_options.append(grade_level.replace('Grade ', ''))
            elif grade_level.isdigit():
                grade_level_options.append(f'Grade {grade_level}')
            query = query.filter(User.grade_level_assigned.in_(grade_level_options))
            if grade_level in ['11', '12', 'Grade 11', 'Grade 12'] and strand:
                query = query.filter(User.specialization == strand)
            if grade_level in ['11', '12', 'Grade 11', 'Grade 12']:
                normalized_grade_level = '11or12'
        if search:
            query = query.filter(User.username.ilike(f'%{search}%'))
        users = [
            {
                'id': str(u.id),
                'username': u.username,
                'user_type': u.user_type,
                'grade_level_assigned': u.grade_level_assigned or '',
                'specialization': u.specialization or ''
            }
            for u in query.order_by(User.username.asc()).all()
        ]
    return render_template(
        'manage_users.html',
        users=users,
        selected_user_type=user_type,
        search=search,
        selected_grade_level=grade_level,
        normalized_grade_level=normalized_grade_level,
        selected_strand=strand,
        grade_levels=grade_levels,
        strands=strands
    )

@app.route('/admin/users/add', methods=['GET', 'POST'])
def add_user_admin():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    user_type = request.args.get('user_type', 'admin')
    grade_levels = [f'Grade {i}' for i in range(7, 13)]
    strands = ['STEM', 'ABM', 'HUMMS', 'HE', 'EIM']
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        user_type = request.form['user_type']
        firstname = request.form.get('firstname', '').strip()
        lastname = request.form.get('lastname', '').strip()
        middlename = request.form.get('middlename', '').strip()
        specialization = request.form.get('specialization') or None
        grade_level_assigned = request.form.get('grade_level_assigned') or None
        if not username or not user_type or not password or not firstname or not lastname:
            flash('Username, password, first name, last name, and user type are required.', 'danger')
            return render_template('add_user_admin.html', user_type=user_type, grade_levels=grade_levels, strands=strands)
        # For students, use grade_level_assigned and specialization (strand)
        if user_type == 'student':
            grade_level_assigned = request.form.get('grade_level_assigned')
            if grade_level_assigned in ['Grade 11', 'Grade 12', '11', '12']:
                specialization = request.form.get('specialization')
            else:
                specialization = None
        # For teachers, use grade_level_assigned and specialization
        if user_type == 'teacher':
            grade_level_assigned = request.form.get('grade_level_assigned')
            specialization = request.form.get('specialization')
        try:
            hashed_password = generate_password_hash(password)
            new_user = User(
                username=username,
                user_type=user_type,
                specialization=specialization,
                grade_level_assigned=grade_level_assigned,
                firstname=firstname,
                lastname=lastname,
                middlename=middlename,
                password_hash=hashed_password
            )
            db.session.add(new_user)
            db.session.commit()
            # Log the action for student add
            if user_type == 'student':
                acting_admin = session.get('admin_username', 'unknown')
                log = AdminLog(action='add', target_username=username, acting_admin=acting_admin)
                db.session.add(log)
                db.session.commit()
            flash(f'{user_type.capitalize()} user added successfully!', 'success')
            return redirect(url_for('manage_users', user_type=user_type))
        except IntegrityError:
            db.session.rollback()
            flash('A user with that username already exists.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while adding the user.', 'danger')
    return render_template('add_user_admin.html', user_type=user_type, grade_levels=grade_levels, strands=strands)

@app.route('/admin/users/<user_id>/edit', methods=['GET', 'POST'])
def edit_user(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    user = User.query.get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('manage_users'))
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form.get('password', '').strip()
        if not username:
            flash('Username is required.', 'danger')
            return render_template('edit_user_admin.html', user=user)
        user.username = username
        if password:
            user.password_hash = generate_password_hash(password)
        db.session.commit()
        # Log the action
        acting_admin = session.get('admin_username', 'unknown')
        log = AdminLog(action='edit', target_username=username, acting_admin=acting_admin)
        db.session.add(log)
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('manage_users', user_type=user.user_type))
    return render_template('edit_user_admin.html', user=user)

@app.route('/admin/users/<user_id>/delete', methods=['POST'])
def delete_user_admin(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    user = User.query.get(user_id)
    if not user or user.user_type != 'admin':
        flash('Admin user not found.', 'danger')
        return redirect(url_for('manage_users'))
    try:
        username = user.username
        db.session.delete(user)
        db.session.commit()
        # Log the action
        acting_admin = session.get('admin_username', 'unknown')
        log = AdminLog(action='delete', target_username=username, acting_admin=acting_admin)
        db.session.add(log)
        db.session.commit()
        flash('Admin user deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while deleting the user.', 'danger')
    return redirect(url_for('manage_users'))

@app.route('/admin/register', methods=['GET', 'POST'])
def register_admin():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        firstname = request.form.get('firstname', '').strip()
        lastname = request.form.get('lastname', '').strip()
        middlename = request.form.get('middlename', '').strip()

        if not all([username, password, firstname, lastname]):
            flash('Username, password, first name, and last name are required.', 'danger')
            return render_template('register_admin.html')

        if not username.endswith('@masteradmin.pcshs.edu.ph'):
            flash('Invalid email domain. Only "@masteradmin.pcshs.edu.ph" is allowed.', 'danger')
            return render_template('register_admin.html')

        try:
            hashed_password = generate_password_hash(password)
            new_admin = User(
                username=username,
                password_hash=hashed_password,
                user_type='admin',
                firstname=firstname,
                lastname=lastname,
                middlename=middlename
            )
            db.session.add(new_admin)
            db.session.commit()
            flash('Admin account created successfully! Please log in.', 'success')
            return redirect(url_for('admin_login'))
        except IntegrityError:
            db.session.rollback()
            flash('That username is already taken. Please choose another.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred: {e}', 'danger')

    return render_template('register_admin.html')

@app.route('/')
def root_redirect():
    return redirect(url_for('admin_login'))

# CLI Command to create a master admin
@app.cli.command("create-admin")
@click.argument("username")
@click.argument("password")
def create_admin_command(username, password):
    """Creates a new admin user with a hashed password."""
    if not username.endswith('@masteradmin.pcshs.edu.ph'):
        print('Error: Invalid email domain. Only "@masteradmin.pcshs.edu.ph" is allowed.')
        return

    if User.query.filter_by(username=username).first():
        print(f"Error: User with username '{username}' already exists.")
        return

    hashed_password = generate_password_hash(password)
    new_admin = User(
        username=username,
        password_hash=hashed_password,
        user_type='admin',
        firstname='Admin',
        lastname='User',
        middlename=''
    )
    db.session.add(new_admin)
    db.session.commit()
    print(f"Admin user '{username}' created successfully.")

@app.route('/admin/parents/<parent_id>/edit', methods=['GET', 'POST'])
def edit_parent(parent_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    parent = Parent.query.get(parent_id)
    if not parent:
        flash('Parent not found.', 'danger')
        return redirect(url_for('manage_users', user_type='parent'))
    if request.method == 'POST':
        parent.username = request.form['username'].strip()
        password = request.form.get('password', '').strip()
        if password:
            parent.password_hash = generate_password_hash(password)
        db.session.commit()
        flash('Parent updated successfully!', 'success')
        return redirect(url_for('manage_users', user_type='parent'))
    return render_template('edit_parent_admin.html', parent=parent)

@app.route('/admin/students/<student_id>/edit', methods=['GET', 'POST'])
def edit_student(student_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    student = StudentInfo.query.get(student_id)
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('manage_users', user_type='student'))
    if request.method == 'POST':
        student.name = request.form['name'].strip()
        student.student_id_number = request.form['student_id_number'].strip()
        db.session.commit()
        # Log the action for student edit
        acting_admin = session.get('admin_username', 'unknown')
        log = AdminLog(action='edit', target_username=student.student_id_number, acting_admin=acting_admin)
        db.session.add(log)
        db.session.commit()
        flash('Student updated successfully!', 'success')
        return redirect(url_for('manage_users', user_type='student'))
    return render_template('edit_user_admin.html', user=student, is_student=True)

@app.route('/admin/students/<student_id>/delete', methods=['POST'])
def delete_student_admin(student_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    student = StudentInfo.query.get(student_id)
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('manage_users', user_type='student'))
    try:
        db.session.delete(student)
        db.session.commit()
        # Log the action for student delete
        acting_admin = session.get('admin_username', 'unknown')
        log = AdminLog(action='delete', target_username=student.student_id_number, acting_admin=acting_admin)
        db.session.add(log)
        db.session.commit()
        flash('Student deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while deleting the student.', 'danger')
    return redirect(url_for('manage_users', user_type='student'))

# --- Teacher Log Model ---
class TeacherLog(db.Model):
    __tablename__ = 'teacher_logs'
    id = db.Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    teacher_id = db.Column(PG_UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    teacher_username = db.Column(db.String(255), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)  # 'add_student', 'edit_student', 'delete_student', 'add_grade', 'edit_grade', 'delete_grade'
    target_type = db.Column(db.String(50), nullable=False)  # 'student' or 'grade'
    target_id = db.Column(PG_UUID(as_uuid=True), nullable=True)  # student_id or grade_id
    target_name = db.Column(db.String(255), nullable=False)  # student name or grade description
    details = db.Column(db.Text, nullable=True)  # Additional details about the action
    section_period_id = db.Column(PG_UUID(as_uuid=True), db.ForeignKey('section_periods.id'), nullable=True)
    subject_id = db.Column(PG_UUID(as_uuid=True), db.ForeignKey('section_subjects.id'), nullable=True)
    timestamp = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

if __name__ == '__main__':
    app.run(debug=True, port=5005) 