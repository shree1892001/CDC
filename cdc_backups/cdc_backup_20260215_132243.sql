-- PostgreSQL CDC Incremental Backup
-- RESTORE INSTRUCTION: Use 'psql -f <filename>' to restore this file.
-- DO NOT USE pg_restore.
-- Generated: 2026-02-15T13:22:43.573062
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;
SET search_path = public, pg_catalog;

BEGIN;

-- LSN: 0/32430904, TXID: 768, TS: 2026-02-15T13:22:43.854479
INSERT INTO public.restore_test_kv (key, value) VALUES ('k1', 'v1');

COMMIT;

BEGIN;

-- LSN: 0/32431176, TXID: 769, TS: 2026-02-15T13:22:43.854479
INSERT INTO public.restore_test_kv (key, value) VALUES ('k2', 'v2');

COMMIT;

BEGIN;

-- LSN: 0/32431352, TXID: 770, TS: 2026-02-15T13:22:43.863489
INSERT INTO public.restore_test_kv (key, value) VALUES ('k3', 'v3');

COMMIT;

BEGIN;

-- LSN: 0/32431528, TXID: 771, TS: 2026-02-15T13:22:43.866352
UPDATE public.restore_test_kv SET value = 'v2_updated' WHERE key = 'k2';

COMMIT;

BEGIN;

-- LSN: 0/32947000, TXID: 817, TS: 2026-02-15T20:14:07.870998
INSERT INTO public.employee (id, name, designation) VALUES (44, 'Sarang', 'Network Engineer');

COMMIT;

BEGIN;

-- LSN: 0/32947640, TXID: 818, TS: 2026-02-15T20:22:21.890898
INSERT INTO public.employee (id, name, designation) VALUES (45, 'Sarang', 'Network Engineer');

COMMIT;

BEGIN;

-- LSN: 0/33136920, TXID: 819, TS: 2026-02-15T22:06:06.074798
INSERT INTO public.cdc_test (id, data, created_at) VALUES (1, 'test_change_1', '2026-02-15 22:06:05.809673');

COMMIT;

BEGIN;

-- LSN: 0/33139032, TXID: 820, TS: 2026-02-15T22:06:07.943038
INSERT INTO public.cdc_test (id, data, created_at) VALUES (2, 'test_change_2', '2026-02-15 22:06:07.937952');

COMMIT;

BEGIN;

-- LSN: 0/33139680, TXID: 821, TS: 2026-02-15T22:12:41.728800
INSERT INTO public.cdc_test (id, data, created_at) VALUES (3, 'test_change_1', '2026-02-15 22:12:41.719927');

COMMIT;

BEGIN;

-- LSN: 0/33140184, TXID: 822, TS: 2026-02-15T22:12:43.770911
INSERT INTO public.cdc_test (id, data, created_at) VALUES (4, 'test_change_2', '2026-02-15 22:12:43.727881');

COMMIT;

BEGIN;

-- LSN: 0/33141064, TXID: 824, TS: 2026-02-15T22:21:23.599198
INSERT INTO public.employee (id, name, designation) VALUES (47, 'Sarang', 'Network Engineer');

COMMIT;

