-- Migration: Add student_quiz_answers table for per-question answers and manual scoring
CREATE TABLE student_quiz_answers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_quiz_result_id UUID NOT NULL REFERENCES student_quiz_results(id) ON DELETE CASCADE,
    question_id VARCHAR NOT NULL,
    answer_text TEXT,
    score NUMERIC(5,2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
); 