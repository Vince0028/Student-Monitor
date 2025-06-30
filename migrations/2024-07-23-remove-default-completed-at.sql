-- Migration: Remove default from completed_at in student_quiz_results
ALTER TABLE student_quiz_results ALTER COLUMN completed_at DROP DEFAULT; 