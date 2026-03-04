-- PostgreSQL CDC Incremental Backup
-- RESTORE INSTRUCTION: Use 'psql -f <filename>' to restore this file.
-- DO NOT USE pg_restore.
-- Generated: 2026-02-15T23:03:01.961316
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;
SET search_path = public, pg_catalog;

BEGIN;

-- LSN: 0/33142392, TXID: 826, TS: 2026-02-15T23:03:21.282350
INSERT INTO public.employee (id, name, designation) VALUES (48, 'Sarang', 'Network Engineer');

COMMIT;

