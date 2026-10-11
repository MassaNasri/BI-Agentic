# P0-C bounded dependency support review

Assessment date: 2026-10-04. This review classifies the current pins; it deliberately does not mass-upgrade dependencies during baseline stabilization.

| Dependency | Observed baseline | Status | Evidence / action |
|---|---|---|---|
| Django (main services) | 4.2.7 | **EOL / OUT OF SUPPORT** | Django 4.2 extended support ended April 7, 2026. Upgrade all main services to at least the 5.2 LTS current patch before production/R1, with migration and contract verification. [Django security notice](https://www.djangoproject.com/weblog/2026/apr/07/security-releases/) |
| Django (ETL images) | Unpinned; final build resolved 5.2.13 | **SUPPORTED BUT UNPINNED / PATCH-LAGGED** | Django 5.2 is LTS, but requirements must pin a reviewed current patch and use a lock/update process. [Django 5.2 LTS notes](https://docs.djangoproject.com/en/6.0/releases/5.2/) |
| Python application images | Main 3.11-slim; ETL 3.10-slim | **SUPPORTED / NEAR EOL** | Python 3.11 security support runs to 2027-10; 3.10 reaches the end of security support in 2026-10. Move ETL to a supported common runtime before production. [Python version status](https://devguide.python.org/versions/) |
| Python CI | 3.12 | **SUPPORTED** | Retain; separately test the exact production image runtimes. [Python version status](https://devguide.python.org/versions/) |
| Node CI | 22 | **SUPPORTED (Maintenance LTS)** | Upgraded from EOL Node 20 in P0-C. Node 22 is scheduled through 2027-04. [Node release schedule](https://github.com/nodejs/Release#release-schedule) |
| Local Node evidence | 24.7.0 | **SUPPORTED (Active LTS at assessment)** | Frontend test/lint/build passed. CI remains on Node 22 for a conservative supported baseline. [Node release schedule](https://github.com/nodejs/Release#release-schedule) |
| React / React DOM | 18.3.1 from lockfile | **PINNED BUT OLD** | React 19 is current; React publishes archived prior-major docs rather than an LTS schedule. Plan a separately tested major upgrade. [React versions](https://react.dev/versions) |
| Vite | 5.4.21 | **PINNED BUT OLD** | Build is green and Vite 5's Node requirement is satisfied, but this is an old major. Upgrade with frontend regression testing. [Vite 5 migration/support](https://v5.vite.dev/guide/migration) |
| ESLint | 8.57.1 | **EOL / OUT OF SUPPORT** | The new lint gate is valid, but ESLint 8 entered EOL in 2024. Migrate config/rules to the current major in a dedicated change. [ESLint version support](https://eslint.org/version-support/) |
| psycopg2-binary | Main 2.9.9; ETL 2.9.11 | **SUPPORTED LEGACY / PINNED BUT OLD** | Psycopg states v2 remains supported for legacy apps; Psycopg 3 is current. Do not combine adapter migration with P0-C. [Psycopg feature/support comparison](https://www.psycopg.org/features/) |
| PostgreSQL application DB | Shared external version not proven; Metabase DB 18.3 | **UNKNOWN / SUPPORTED BUT OLD MINOR** | Inventory the external shared server version. PostgreSQL 18 is supported, but 18.3 is behind the current 18.6 minor and should be patched. [PostgreSQL versioning](https://www.postgresql.org/support/versioning/) |
| Metabase | v0.58.8.5, digest-pinned | **PINNED BUT OLD** | Metabase 63 is current. Keep the digest and PostgreSQL app DB until a backup-backed upgrade rehearsal; Metabase recommends a specific version and app-DB backup. [Metabase releases](https://www.metabase.com/releases), [upgrade guide](https://www.metabase.com/docs/latest/installation-and-operation/upgrading-metabase) |
| Kafka Python client | Voice 2.0.2; ETL final image 2.3.1 | **PINNED BUT OLD** | The project has newer 3.x releases; retain current behavior for P0-C, then test manual-commit/rewind compatibility before upgrade. [kafka-python releases](https://github.com/dpkp/kafka-python/releases) |
| SurrealDB server/client | Server 3.0.1 digest; first-party HTTP client | **PINNED BUT OLD / CLIENT SUPPORT UNKNOWN** | Current releases include 3.3.0. The in-repo HTTP wrapper has no independent upstream support lifecycle; validate SQL/HTTP compatibility before a digest change. [SurrealDB releases](https://github.com/surrealdb/surrealdb/releases) |

Required pre-production/R-phase dependency work:

1. Upgrade Django 4.2.7 services to a supported LTS patch and repeat all migrations/security/E2E gates.
2. Move ETL off Python 3.10 and pin every unbounded ETL dependency through a reviewed lock/constraints workflow.
3. Upgrade ESLint, then Vite/React as separate frontend changes.
4. Prove the shared PostgreSQL server version; patch supported database minors.
5. Rehearse Metabase, Kafka client, and SurrealDB upgrades against retained backups and the disposable workflow.

These are explicit follow-up inputs, not hidden P0-C failures. The current baseline functions reproducibly, but EOL components keep the pre-production dependency gate **PARTIAL**.
