-- PostgreSQL CDC Incremental Backup
-- RESTORE INSTRUCTION: Use 'psql -f <filename>' to restore this file.
-- DO NOT USE pg_restore.
-- Generated: 2026-03-03T22:22:42.428311
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;
SET search_path = public, pg_catalog;

BEGIN;

-- LSN: 0/33148792, TXID: 831, TS: 2026-03-03T22:23:29.311361
INSERT INTO public.employee (id, name, designation) VALUES (51, 'Sarang', 'Network Engineer');

COMMIT;

