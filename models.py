import uuid
from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

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
    def __repr__(self):
        return f"<Quiz(id={self.id}, title='{self.title}')>"

class StudentQuizResult(Base):
    __tablename__ = 'student_quiz_results'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_info_id = Column(PG_UUID(as_uuid=True), ForeignKey('students_info.id'), nullable=False)
    quiz_id = Column(PG_UUID(as_uuid=True), ForeignKey('quizzes.id'), nullable=False)
    score = Column(Numeric(5, 2), nullable=False)
    total_points = Column(Numeric(5, 2), nullable=False)
    completed_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('student_info_id', 'quiz_id'),)

class StudentQuizAnswer(Base):
    __tablename__ = 'student_quiz_answers'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_quiz_result_id = Column(PG_UUID(as_uuid=True), ForeignKey('student_quiz_results.id'), nullable=False)
    question_id = Column(String, nullable=False)  # or Integer, depending on your question IDs
    answer_text = Column(String, nullable=True)
    score = Column(Numeric(5, 2), nullable=True)  # Teacher can fill this in 

class SectionPeriod(Base):
    __tablename__ = 'section_periods'
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id = Column(PG_UUID(as_uuid=True), ForeignKey('sections.id'), nullable=False)
    period_type = Column(String(50), nullable=False) # 'Semester' or 'Quarter'
    period_name = Column(String(50), nullable=False) # e.g., '1st Sem', 'Q1'
    school_year = Column(String(50), nullable=False) # e.g., '2025-2026'
    assigned_teacher_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    created_by_admin = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint('section_id', 'period_name', 'school_year'),
    )
    def __repr__(self):
        return f"<SectionPeriod(id={self.id}, section_id={self.section_id}, period='{self.period_name}', type='{self.period_type}', year='{self.school_year}', assigned_teacher_id='{self.assigned_teacher_id}')>" 