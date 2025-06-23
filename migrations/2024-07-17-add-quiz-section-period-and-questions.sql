ALTER TABLE quizzes
ADD COLUMN section_period_id UUID,
ADD COLUMN subject_id UUID,
ADD COLUMN questions_json TEXT; 