"""Staged owner-schema migration for critical PostgreSQL business tables.

This is deliberately opt-in. Deploying application login roles/search paths is
a separate cutover; this script never changes a user-owned database by default.
"""

import argparse
import os

import psycopg2
from psycopg2 import sql


OWNERS = {
    "auth": (
        "users", "password_reset_codes", "token_blacklist_outstandingtoken",
        "token_blacklist_blacklistedtoken",
    ),
    "workspace": ("workspaces", "workspace_members", "invitations"),
    "integration": (
        "integration_data_sources", "integration_source_credentials",
        "integration_source_executions", "integration_source_candidates",
        "integration_source_operation_budgets",
    ),
    "query": ("manager_databases", "authorized_query_definitions"),
    "entitlement": (
        "subscription_plans", "workspace_subscriptions", "subscription_payments",
        "subscription_free_tier_usage",
    ),
}

JOURNAL = "biavora_c4_owner_migration"


def _role(domain, suffix):
    return f"biavora_{domain}_{suffix}"


def _schema(domain):
    return f"biavora_{domain}"


def apply(connection):
    """Move existing tables atomically; fail if the complete owner set is absent."""
    with connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(649947, 4)")
            for domain in OWNERS:
                for suffix in ("owner", "app"):
                    name = _role(domain, suffix)
                    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
                    if cursor.fetchone() is None:
                        cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(name)))
                cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}").format(
                    sql.Identifier(_schema(domain)), sql.Identifier(_role(domain, "owner")),
                ))
            cursor.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS public.{} (
                    table_name text PRIMARY KEY,
                    prior_owner text NOT NULL,
                    prior_schema text NOT NULL,
                    migrated_at timestamptz NOT NULL DEFAULT now()
                )
            """).format(sql.Identifier(JOURNAL)))
            cursor.execute(sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(JOURNAL)))
            if cursor.fetchone()[0]:
                cursor.execute(sql.SQL("SELECT table_name FROM public.{}").format(sql.Identifier(JOURNAL)))
                recorded = {row[0] for row in cursor.fetchall()}
                expected = {table for tables in OWNERS.values() for table in tables}
                if recorded != expected:
                    raise RuntimeError("Owner migration journal is incomplete.")
                for domain, tables in OWNERS.items():
                    for table in tables:
                        cursor.execute("""
                            SELECT r.rolname FROM pg_class c
                            JOIN pg_namespace n ON n.oid = c.relnamespace
                            JOIN pg_roles r ON r.oid = c.relowner
                            WHERE n.nspname = %s AND c.relname = %s
                        """, (_schema(domain), table))
                        row = cursor.fetchone()
                        if row != (_role(domain, "owner"),):
                            raise RuntimeError("Owner migration journal does not match the database.")
                return

            # Check every source table before moving the first one.
            for domain, tables in OWNERS.items():
                for table in tables:
                    cursor.execute("""
                        SELECT r.rolname FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        JOIN pg_roles r ON r.oid = c.relowner
                        WHERE n.nspname = 'public' AND c.relname = %s AND c.relkind IN ('r','p')
                    """, (table,))
                    if cursor.fetchone() is None:
                        raise RuntimeError(f"Required public table is missing: {table}")
                    cursor.execute("SELECT to_regclass(%s)", (f"{_schema(domain)}.{table}",))
                    if cursor.fetchone()[0] is not None:
                        raise RuntimeError(f"Target table already exists: {table}")

            for domain, tables in OWNERS.items():
                owner, app, schema = _role(domain, "owner"), _role(domain, "app"), _schema(domain)
                cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(app),
                ))
                for table in tables:
                    cursor.execute("""
                        SELECT r.rolname FROM pg_class c
                        JOIN pg_roles r ON r.oid = c.relowner
                        WHERE c.oid = %s::regclass
                    """, (f"public.{table}",))
                    prior_owner = cursor.fetchone()[0]
                    cursor.execute(sql.SQL("INSERT INTO public.{} (table_name, prior_owner, prior_schema) VALUES (%s, %s, 'public')").format(
                        sql.Identifier(JOURNAL),
                    ), (table, prior_owner))
                    cursor.execute(sql.SQL("ALTER TABLE {}.{} SET SCHEMA {}").format(
                        sql.Identifier("public"), sql.Identifier(table), sql.Identifier(schema),
                    ))
                    cursor.execute(sql.SQL("ALTER TABLE {}.{} OWNER TO {}").format(
                        sql.Identifier(schema), sql.Identifier(table), sql.Identifier(owner),
                    ))
                    cursor.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {}.{} TO {}").format(
                        sql.Identifier(schema), sql.Identifier(table), sql.Identifier(app),
                    ))
                cursor.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(app),
                ))
                cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(
                    sql.Identifier(owner), sql.Identifier(schema), sql.Identifier(app),
                ))


def rollback(connection):
    """Restore recorded table schemas/owners without dropping business data."""
    with connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(649947, 4)")
            cursor.execute("SELECT to_regclass(%s)", (f"public.{JOURNAL}",))
            if cursor.fetchone()[0] is None:
                return
            cursor.execute(sql.SQL("SELECT table_name, prior_owner, prior_schema FROM public.{} ORDER BY table_name").format(
                sql.Identifier(JOURNAL),
            ))
            recorded = {row[0]: row[1:] for row in cursor.fetchall()}
            if not recorded:
                return
            for domain, tables in OWNERS.items():
                schema, app = _schema(domain), _role(domain, "app")
                for table in tables:
                    if table not in recorded:
                        raise RuntimeError(f"Missing rollback journal entry: {table}")
                    prior_owner, prior_schema = recorded[table]
                    cursor.execute(sql.SQL("REVOKE ALL ON {}.{} FROM {}").format(
                        sql.Identifier(schema), sql.Identifier(table), sql.Identifier(app),
                    ))
                    cursor.execute(sql.SQL("ALTER TABLE {}.{} OWNER TO {}").format(
                        sql.Identifier(schema), sql.Identifier(table), sql.Identifier(prior_owner),
                    ))
                    cursor.execute(sql.SQL("ALTER TABLE {}.{} SET SCHEMA {}").format(
                        sql.Identifier(schema), sql.Identifier(table), sql.Identifier(prior_schema),
                    ))
            cursor.execute(sql.SQL("DELETE FROM public.{}").format(sql.Identifier(JOURNAL)))


def configure_runtime_roles(connection, passwords):
    """Create distinct LOGIN principals that inherit only their own app grants."""
    with connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(649947, 4)")
            for domain in OWNERS:
                password = passwords.get(domain, "")
                if len(password) < 32:
                    raise RuntimeError(f"Strong {domain} runtime password is required.")
                role = _role(domain, "runtime")
                app = _role(domain, "app")
                cursor.execute("SELECT rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname = %s", (role,))
                existing = cursor.fetchone()
                if existing is None:
                    cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(sql.Identifier(role)))
                elif existing != (True, False, False, False, False):
                    raise RuntimeError(f"Unsafe pre-existing runtime role: {role}")
                cursor.execute("""
                    SELECT parent.rolname FROM pg_auth_members membership
                    JOIN pg_roles member ON member.oid = membership.member
                    JOIN pg_roles parent ON parent.oid = membership.roleid
                    WHERE member.rolname = %s AND parent.rolname <> %s
                """, (role, app))
                if cursor.fetchone() is not None:
                    raise RuntimeError(f"Runtime role has an unexpected grant: {role}")
                cursor.execute(sql.SQL("ALTER ROLE {} PASSWORD %s").format(sql.Identifier(role)), (password,))
                cursor.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(app), sql.Identifier(role)))
                cursor.execute(sql.SQL("ALTER ROLE {} SET search_path = {}, public").format(
                    sql.Identifier(role), sql.Identifier(_schema(domain)),
                ))
                cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(connection.get_dsn_parameters()["dbname"]), sql.Identifier(role),
                ))
                # Django's startup migration check reads this shared recorder.
                # Application roles need no write or ownership rights on it.
                cursor.execute("SELECT to_regclass('public.django_migrations')")
                if cursor.fetchone()[0] is not None:
                    cursor.execute(sql.SQL("GRANT SELECT ON TABLE public.django_migrations TO {}").format(
                        sql.Identifier(role),
                    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("apply", "configure-roles", "rollback"))
    args = parser.parse_args()
    if os.getenv("BIAVORA_C4_ALLOW_OWNER_MIGRATION") != "1":
        raise SystemExit("Set BIAVORA_C4_ALLOW_OWNER_MIGRATION=1 only for a reviewed target.")
    connection = psycopg2.connect(
        host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    try:
        if args.action == "apply":
            apply(connection)
        elif args.action == "configure-roles":
            configure_runtime_roles(connection, {
                domain: os.environ.get(f"BIAVORA_{domain.upper()}_RUNTIME_PASSWORD", "")
                for domain in OWNERS
            })
        else:
            rollback(connection)
    finally:
        connection.close()
    print(f"Owner schema {args.action}: PASS")


if __name__ == "__main__":
    main()
