-- PostgreSQL CDC Incremental Backup
-- Generated: 2026-02-05T06:27:38.232525
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;
SET search_path = public, pg_catalog;

BEGIN;

-- LSN: 0/32285136, TXID: 765, TS: 2026-02-05T07:33:46.095649
INSERT INTO public.employee (id, name, designation) VALUES (34, 'micheal Jozi', 'CTO');

COMMIT;

