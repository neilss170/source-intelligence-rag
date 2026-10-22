-- Runs once, when the database volume is first created.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;

-- A separate database for the test suite, so tests never touch real data.
CREATE DATABASE source_intelligence_test;
\connect source_intelligence_test
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;
