-- Migration: Create student_quiz_results table
CREATE TABLE student_quiz_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_info_id UUID NOT NULL REFERENCES students_info(id) ON DELETE CASCADE,
    quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    score NUMERIC(5, 2) NOT NULL,
    total_points NUMERIC(5, 2) NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_info_id, quiz_id)
); 