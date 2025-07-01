-- Migration: Add notes column to attendance table for teacher notes
ALTER TABLE attendance ADD COLUMN notes TEXT; 