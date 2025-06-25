-- Create users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    user_type VARCHAR(10) NOT NULL, -- 'admin' or 'teacher'
    specialization VARCHAR(255), -- For teachers: STEM, ICT, ABM, HUMSS, GAS, HE (for SHS), NULL for JHS
    grade_level_assigned VARCHAR(50), -- e.g., 'Grade 7', 'Grade 11'. Null for admin.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create grade_levels table
CREATE TABLE grade_levels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) UNIQUE NOT NULL, -- e.g., 'Grade 7', 'Grade 11'
    level_type VARCHAR(10) NOT NULL, -- 'JHS' or 'SHS'
    created_by UUID REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create strands table (only for SHS grade levels)
CREATE TABLE strands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL, -- e.g., 'STEM', 'ICT'
    grade_level_id UUID NOT NULL REFERENCES grade_levels(id) ON DELETE CASCADE,
    created_by UUID REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (name, grade_level_id)
);

-- Create sections table (links to a specific grade level and optionally a strand)
CREATE TABLE sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL, -- e.g., 'A', 'Purity'
    grade_level_id UUID NOT NULL REFERENCES grade_levels(id) ON DELETE CASCADE,
    strand_id UUID REFERENCES strands(id) ON DELETE CASCADE, -- Null for JHS sections
    adviser_name VARCHAR(255),
    section_password VARCHAR(255),
    adviser_password VARCHAR(255),
    assigned_user_id UUID,
    created_by UUID REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (name, grade_level_id, strand_id)
);

-- Create section_periods table (handles semesters/quarters)
CREATE TABLE section_periods (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    period_type VARCHAR(50) NOT NULL, -- 'Semester' or 'Quarter'
    period_name VARCHAR(50) NOT NULL, -- e.g., '1st Semester', 'Q1'
    school_year VARCHAR(50) NOT NULL, -- e.g., '2025-2026'
    assigned_teacher_id UUID REFERENCES users(id) ON DELETE SET NULL, -- The account assigned to the period
    created_by_admin UUID REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (section_id, period_name, school_year)
);

-- Create students_info table
CREATE TABLE students_info (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_period_id UUID NOT NULL REFERENCES section_periods(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    student_id_number VARCHAR(255) UNIQUE NOT NULL,
    gender VARCHAR(10),
    password_hash VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create section_subjects table
CREATE TABLE section_subjects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_period_id UUID NOT NULL REFERENCES section_periods(id) ON DELETE CASCADE,
    subject_name VARCHAR(255) NOT NULL,
    assigned_teacher_name VARCHAR(255) NOT NULL, -- The name of the human teacher
    created_by_teacher_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, -- The account that created the subject
    subject_password VARCHAR(255), -- Password for accessing gradebook for this subject
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (section_period_id, subject_name)
);

-- Create attendance table
CREATE TABLE attendance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_info_id UUID NOT NULL REFERENCES students_info(id) ON DELETE CASCADE,
    section_subject_id UUID NOT NULL REFERENCES section_subjects(id) ON DELETE CASCADE,
    attendance_date DATE NOT NULL,
    status VARCHAR(50) NOT NULL, -- 'present', 'absent', 'late', 'excused'
    recorded_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_info_id, section_subject_id, attendance_date)
);

-- Create grades table (for final, computed grades)
CREATE TABLE grades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_info_id UUID NOT NULL REFERENCES students_info(id) ON DELETE CASCADE,
    section_subject_id UUID NOT NULL REFERENCES section_subjects(id) ON DELETE CASCADE,
    teacher_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    grade_value NUMERIC(5, 2) NOT NULL,
    semester VARCHAR(50),
    school_year VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_info_id, section_subject_id, semester, school_year)
);

-- Create grading_systems table (defines the overall system for a subject)
CREATE TABLE grading_systems (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_subject_id UUID UNIQUE NOT NULL REFERENCES section_subjects(id) ON DELETE CASCADE,
    teacher_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(section_subject_id)
);

-- Create grading_components table (defines the weighted parts of the system)
CREATE TABLE grading_components (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    system_id UUID NOT NULL REFERENCES grading_systems(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL, -- e.g., 'Quizzes', 'Exams', 'Behavior'
    weight INTEGER NOT NULL, -- e.g., 20 for 20%
    UNIQUE(system_id, name)
);

-- Create gradable_items table (defines each individual assignment, quiz, etc.)
CREATE TABLE gradable_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    component_id UUID NOT NULL REFERENCES grading_components(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL, -- e.g., 'Quiz 1: Chapters 1-3'
    max_score NUMERIC(10, 2) NOT NULL DEFAULT 100
);

-- Create student_scores table (stores the score a student got on an item)
CREATE TABLE student_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id UUID NOT NULL REFERENCES gradable_items(id) ON DELETE CASCADE,
    student_info_id UUID NOT NULL REFERENCES students_info(id) ON DELETE CASCADE,
    score NUMERIC(10, 2) NOT NULL,
    UNIQUE (item_id, student_info_id)
);



