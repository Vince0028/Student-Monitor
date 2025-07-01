-- Migration: Add status column to quizzes table for draft/published support
ALTER TABLE quizzes ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'draft'; 