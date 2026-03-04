-- PostgreSQL CDC Incremental Backup
-- RESTORE INSTRUCTION: Use 'psql -f <filename>' to restore this file.
-- DO NOT USE pg_restore.
-- Generated: 2026-02-15T22:12:36.644339
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;
SET search_path = public, pg_catalog;

BEGIN;

-- LSN: 0/33139680, TXID: 821, TS: 2026-02-15T22:12:41.729145
INSERT INTO public.cdc_test (id, data, created_at) VALUES (3, 'test_change_1', '2026-02-15 22:12:41.719927');

COMMIT;

BEGIN;

-- LSN: 0/33140184, TXID: 822, TS: 2026-02-15T22:12:43.768593
INSERT INTO public.cdc_test (id, data, created_at) VALUES (4, 'test_change_2', '2026-02-15 22:12:43.727881');

COMMIT;

BEGIN;

-- LSN: 0/33141064, TXID: 824, TS: 2026-02-15T22:21:23.596165
INSERT INTO public.employee (id, name, designation) VALUES (47, 'Sarang', 'Network Engineer');

COMMIT;

