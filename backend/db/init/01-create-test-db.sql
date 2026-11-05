-- Runs once when the Postgres volume is first initialised.
-- Separate database used by the automated test suite so tests never touch dev data.
CREATE DATABASE logitrack_test;
