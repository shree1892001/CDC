-- PostgreSQL CDC Incremental Backup
-- RESTORE INSTRUCTION: Use 'psql -f <filename>' to restore this file.
-- DO NOT USE pg_restore.
-- Generated: 2026-03-03T18:35:14.209130
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;
SET search_path = public, pg_catalog;

BEGIN;

-- LSN: 0/33147536, TXID: 830, TS: 2026-03-03T18:53:48.208024
INSERT INTO public.employee (id, name, designation) VALUES (50, 'Sarang', 'Network Engineer');

COMMIT;

