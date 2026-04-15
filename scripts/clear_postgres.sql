-- Clear PostgreSQL data while preserving schema.
-- Preserve core Django metadata tables to avoid post_migrate race conditions
-- when multiple services start and run migrations concurrently.

DO $$
DECLARE
    truncate_list text;
BEGIN
    SELECT string_agg(
        format('%I.%I', schemaname, tablename),
        ', ' ORDER BY schemaname, tablename
    )
    INTO truncate_list
    FROM pg_tables
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
      AND tablename NOT IN ('django_migrations', 'django_content_type', 'auth_permission');

    IF truncate_list IS NULL THEN
        RAISE NOTICE 'No PostgreSQL tables eligible for truncation.';
    ELSE
        EXECUTE 'TRUNCATE TABLE ' || truncate_list || ' RESTART IDENTITY CASCADE;';
        RAISE NOTICE 'PostgreSQL data truncation completed.';
    END IF;
END $$;
