import os
from dotenv import load_dotenv
load_dotenv()
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set.")
from sqlalchemy import create_engine
engine = create_engine(
    DATABASE_URL,
    pool_size=1,
    max_overflow=0,
    pool_timeout=30,
)
import uuid
from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey, UniqueConstraint, Date, Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import relationship

Base = declarative_base()
Session = sessionmaker(bind=engine)

class Quiz(Base):
    __tablename__ = 'quizzes'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(String(255), nullable=True)
    section_period_id = Column(PG_UUID(as_uuid=True), nullable=True)
    subject_id = Column(PG_UUID(as_uuid=True), nullable=True)
    questions_json = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deadline = Column(DateTime(timezone=True), nullable=True)
    time_limit_minutes = Column(Integer, nullable=True)
    def __repr__(self):
        return f"<Quiz(id={self.id}, title='{self.title}')>"

class StudentQuizResult(Base):
    __tablename__ = 'student_quiz_results'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_info_id = Column(PG_UUID(as_uuid=True), ForeignKey('students_info.id'), nullable=False)
    quiz_id = Column(PG_UUID(as_uuid=True), ForeignKey('quizzes.id'), nullable=False)
    score = Column(Numeric(5, 2), nullable=False)
    total_points = Column(Numeric(5, 2), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint('student_info_id', 'quiz_id'),)

class StudentQuizAnswer(Base):
    __tablename__ = 'student_quiz_answers'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_quiz_result_id = Column(PG_UUID(as_uuid=True), ForeignKey('student_quiz_results.id'), nullable=False)
    question_id = Column(String, nullable=False)  # or Integer, depending on your question IDs
    answer_text = Column(String, nullable=True)
    score = Column(Numeric(5, 2), nullable=True)  # Teacher can fill this in 

class User(Base):
    __tablename__ = 'users'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    user_type = Column(String(10), nullable=False)
    specialization = Column(String(255), nullable=True)
    grade_level_assigned = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Relationships: see main app for back_populates
    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', user_type='{self.user_type}', specialization='{self.specialization}', grade_level_assigned='{self.grade_level_assigned}')>"

class GradeLevel(Base):
    __tablename__ = 'grade_levels'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False)
    level_type = Column(String(10), nullable=False)
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    def __repr__(self):
        return f"<GradeLevel(id={self.id}, name='{self.name}', level_type='{self.level_type}')>"

class Strand(Base):
    __tablename__ = 'strands'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    grade_level_id = Column(PG_UUID(as_uuid=True), ForeignKey('grade_levels.id'), nullable=False)
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    grade_level = relationship('GradeLevel', backref='strands')
    def __repr__(self):
        return f"<Strand(id={self.id}, name='{self.name}')>"

class Section(Base):
    __tablename__ = 'sections'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    grade_level_id = Column(PG_UUID(as_uuid=True), ForeignKey('grade_levels.id'), nullable=False)
    strand_id = Column(PG_UUID(as_uuid=True), ForeignKey('strands.id'), nullable=True)
    adviser_name = Column(String(255), nullable=True)
    section_password = Column(String(255), nullable=True)
    assigned_user_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    adviser_password = Column(String(255), nullable=True)
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    grade_level = relationship('GradeLevel', backref='sections')
    strand = relationship('Strand', backref='sections')
    section_periods = relationship('SectionPeriod', backref='section')
    def __repr__(self):
        return f"<Section(id={self.id}, name='{self.name}')>"

class SectionPeriod(Base):
    __tablename__ = 'section_periods'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id = Column(PG_UUID(as_uuid=True), ForeignKey('sections.id'), nullable=False)
    period_type = Column(String(50), nullable=False)
    period_name = Column(String(50), nullable=False)
    school_year = Column(String(50), nullable=False)
    assigned_teacher_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    created_by_admin = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    assigned_teacher = relationship('User', foreign_keys=[assigned_teacher_id], backref='assigned_section_periods')
    students_in_period = relationship('StudentInfo', back_populates='section_period')
    def __repr__(self):
        return f"<SectionPeriod(id={self.id}, section_id={self.section_id}, period='{self.period_name}', type='{self.period_type}', year='{self.school_year}', assigned_teacher_id='{self.assigned_teacher_id}')>"

class SectionSubject(Base):
    __tablename__ = 'section_subjects'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_period_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_periods.id'), nullable=False)
    subject_name = Column(String(255), nullable=False)
    created_by_teacher_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    assigned_teacher_name = Column(String(255), nullable=False)
    subject_password = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    section_period = relationship('SectionPeriod', backref='section_subjects')
    grading_system = relationship('GradingSystem', uselist=False, backref='section_subject')
    def __repr__(self):
        return f"<SectionSubject(id={self.id}, subject_name='{self.subject_name}')>"

class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_info_id = Column(PG_UUID(as_uuid=True), ForeignKey('students_info.id'), nullable=False)
    section_subject_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_subjects.id'), nullable=False)
    attendance_date = Column(Date, nullable=False)
    status = Column(String(50), nullable=False)
    recorded_by = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    student_info = relationship('StudentInfo', back_populates='attendance_records')
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
    section_subject = relationship('SectionSubject', backref='grades')
    student_info = relationship('StudentInfo', back_populates='grades')
    def __repr__(self):
        return f"<Grade(id={self.id}, student_info_id={self.student_info_id}, subject='{self.section_subject_id}', grade={self.grade_value}')>"

class StudentInfo(Base):
    __tablename__ = 'students_info'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_period_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_periods.id'), nullable=False)
    name = Column(String(255), nullable=False)
    student_id_number = Column(String(255), unique=True, nullable=False)
    gender = Column(String(10), nullable=True)
    password_hash = Column(String(255), nullable=True)
    parent_id = Column(PG_UUID(as_uuid=True), ForeignKey('parents.id'), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    average_grade = Column(Numeric(5, 2), nullable=True)
    parent = relationship('Parent', back_populates='students')
    # Relationships
    section_period = relationship('SectionPeriod', back_populates='students_in_period')
    attendance_records = relationship('Attendance', back_populates='student_info', cascade='all, delete-orphan')
    grades = relationship('Grade', back_populates='student_info', cascade='all, delete-orphan')
    scores = relationship('StudentScore', back_populates='student', cascade='all, delete-orphan')
    def __repr__(self):
        return f"<StudentInfo(id={self.id}, name='{self.name}', student_id_number='{self.student_id_number}', gender='{self.gender}')>"

class GradingSystem(Base):
    __tablename__ = 'grading_systems'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_subject_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_subjects.id'), unique=True, nullable=False)
    teacher_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    components = relationship('GradingComponent', backref='system', cascade='all, delete-orphan')
    def __repr__(self):
        return f"<GradingSystem(id={self.id}, section_subject_id={self.section_subject_id})>"

class GradingComponent(Base):
    __tablename__ = 'grading_components'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    system_id = Column(PG_UUID(as_uuid=True), ForeignKey('grading_systems.id'), nullable=False)
    name = Column(String(100), nullable=False)
    weight = Column(Integer, nullable=False)
    items = relationship('GradableItem', backref='component', cascade='all, delete-orphan')
    def __repr__(self):
        return f"<GradingComponent(name='{self.name}', weight={self.weight}%)>"

class GradableItem(Base):
    __tablename__ = 'gradable_items'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component_id = Column(PG_UUID(as_uuid=True), ForeignKey('grading_components.id'), nullable=False)
    title = Column(String(255), nullable=False)
    max_score = Column(Numeric(10, 2), nullable=False, default=100)
    # Relationships: see main app for back_populates
    def __repr__(self):
        return f"<GradableItem(title='{self.title}', max_score={self.max_score})>" 

class StudentScore(Base):
    __tablename__ = 'student_scores'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey('gradable_items.id'), nullable=False)
    student_info_id = Column(PG_UUID(as_uuid=True), ForeignKey('students_info.id'), nullable=False)
    score = Column(Numeric(10, 2), nullable=False)
    __table_args__ = (UniqueConstraint('item_id', 'student_info_id'),)
    student = relationship('StudentInfo', back_populates='scores')
    def __repr__(self):
        return f"<StudentScore(id={self.id}, item_id={self.item_id}, student_info_id={self.student_info_id}, score={self.score})>" 

class TeacherLog(Base):
    __tablename__ = 'teacher_logs'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    teacher_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    teacher_username = Column(String(255), nullable=False)
    action_type = Column(String(50), nullable=False)
    target_type = Column(String(50), nullable=False)
    target_id = Column(PG_UUID(as_uuid=True), nullable=True)
    target_name = Column(String(255), nullable=False)
    details = Column(String, nullable=True)
    section_period_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_periods.id'), nullable=True)
    subject_id = Column(PG_UUID(as_uuid=True), ForeignKey('section_subjects.id'), nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    # Relationships: see main app for back_populates
    def __repr__(self):
        return f"<TeacherLog(id={self.id}, teacher='{self.teacher_username}', action='{self.action_type}', target='{self.target_name}')>" 

class Parent(Base):
    __tablename__ = 'parents'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=True)
    password_hash = Column(String(255), nullable=True)
    email = Column(String(255), unique=True, nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    phone_number = Column(String(50), nullable=True)
    students = relationship('StudentInfo', back_populates='parent')
    def __repr__(self):
        return f"<Parent(id={self.id}, username='{self.username}', email='{self.email}')>"

class ParentPortalStudent(Base):
    __tablename__ = 'parent_portal_students'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_id = Column(PG_UUID(as_uuid=True), ForeignKey('parents.id'), nullable=False)
    student_id_number = Column(String(255), nullable=False)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    grade_level = Column(String(50), nullable=True)
    section_name = Column(String(255), nullable=True)
    strand_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    def __repr__(self):
        return f"<ParentPortalStudent(id={self.id}, student_id_number='{self.student_id_number}', first_name='{self.first_name}', last_name='{self.last_name}')>" 