import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
import uuid
from sqlalchemy.exc import IntegrityError
from datetime import datetime

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

# Hardcoded admin credentials
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin123'

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    return render_template('admin_dashboard.html')

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

# --- Admin Log Model ---
class AdminLog(db.Model):
    __tablename__ = 'admin_logs'
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(50), nullable=False)
    target_username = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    acting_admin = db.Column(db.String(255), nullable=False)

@app.route('/admin/admin_logs')
def admin_logs():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    logs = AdminLog.query.order_by(AdminLog.timestamp.desc()).all()
    return render_template('admin_logs.html', logs=logs)

@app.route('/admin/users')
def manage_users():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    users = User.query.filter_by(user_type='admin').order_by(User.username).all()
    user_list = [
        {
            'id': str(u.id),
            'username': u.username,
            'user_type': u.user_type,
            'specialization': u.specialization or 'N/A',
            'grade_level_assigned': u.grade_level_assigned or 'N/A'
        }
        for u in users
    ]
    return render_template('manage_users.html', users=user_list)

@app.route('/admin/users/add', methods=['GET', 'POST'])
def add_user_admin():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        username = request.form['username'].strip()
        user_type = request.form['user_type']
        specialization = request.form.get('specialization') or None
        grade_level_assigned = request.form.get('grade_level_assigned') or None
        if not username or not user_type:
            flash('Username and user type are required.', 'danger')
            return render_template('add_user_admin.html')
        if user_type != 'admin':
            flash('You can only add admin users here.', 'danger')
            return render_template('add_user_admin.html')
        try:
            new_user = User(username=username, user_type=user_type, specialization=specialization, grade_level_assigned=grade_level_assigned)
            db.session.add(new_user)
            db.session.commit()
            # Log the action
            acting_admin = ADMIN_USERNAME if 'admin_logged_in' in session else 'unknown'
            log = AdminLog(action='add', target_username=username, acting_admin=acting_admin)
            db.session.add(log)
            db.session.commit()
            flash('Admin user added successfully!', 'success')
            return redirect(url_for('manage_users'))
        except IntegrityError:
            db.session.rollback()
            flash('A user with that username already exists.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while adding the user.', 'danger')
    return render_template('add_user_admin.html')

@app.route('/admin/users/<user_id>/edit', methods=['GET', 'POST'])
def edit_user_admin(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    user = User.query.get(user_id)
    if not user or user.user_type != 'admin':
        flash('Admin user not found.', 'danger')
        return redirect(url_for('manage_users'))
    if request.method == 'POST':
        username = request.form['username'].strip()
        user_type = request.form['user_type']
        specialization = request.form.get('specialization') or None
        grade_level_assigned = request.form.get('grade_level_assigned') or None
        if not username or not user_type:
            flash('Username and user type are required.', 'danger')
            return render_template('edit_user_admin.html', user=user)
        if user_type != 'admin':
            flash('You can only set user type to admin here.', 'danger')
            return render_template('edit_user_admin.html', user=user)
        try:
            user.username = username
            user.user_type = user_type
            user.specialization = specialization
            user.grade_level_assigned = grade_level_assigned
            db.session.commit()
            # Log the action
            acting_admin = ADMIN_USERNAME if 'admin_logged_in' in session else 'unknown'
            log = AdminLog(action='edit', target_username=username, acting_admin=acting_admin)
            db.session.add(log)
            db.session.commit()
            flash('Admin user updated successfully!', 'success')
            return redirect(url_for('manage_users'))
        except IntegrityError:
            db.session.rollback()
            flash('A user with that username already exists.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while updating the user.', 'danger')
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
        acting_admin = ADMIN_USERNAME if 'admin_logged_in' in session else 'unknown'
        log = AdminLog(action='delete', target_username=username, acting_admin=acting_admin)
        db.session.add(log)
        db.session.commit()
        flash('Admin user deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while deleting the user.', 'danger')
    return redirect(url_for('manage_users'))

if __name__ == '__main__':
    app.run(debug=True, port=5005) 