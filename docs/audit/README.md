> **SUPERSEDED PLANNING — 2026-10-27.** Retained as the Phase-0 design/evidence context. For implementation use [the January scope and roadmap](../../BIAVORA_PRODUCTION_READINESS_AUDIT/43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md) and master context 34. HTTP remains control plane; Kafka remains data/event plane; logical ownership precedes physical separation. Old Kafka-removal, service-move and next-phase directions below are not current instructions.

# Phase 0 audit index

**Audit complete; Phase 0 acceptance PARTIAL; production NOT READY.** Active business data is cleared and local startup smoke passes. Historical archives and Metabase metadata are intentionally preserved. Voice/notification migration parity, failing tests and critical security findings remain open.

Start with [the practical action plan](PRE_DEVELOPMENT_ACTION_PLAN.md), [console summary](CONSOLE_SUMMARY.txt), [main audit](PRE_DEVELOPMENT_SYSTEM_AUDIT.md), [data/backup report](DATA_STORAGE_AND_WIPE_REPORT.md), and [startup evidence](STARTUP_VERIFICATION.md).

## Required reports

- [PRE_DEVELOPMENT_SYSTEM_AUDIT.md](PRE_DEVELOPMENT_SYSTEM_AUDIT.md)
- [SECURITY_AUDIT.md](SECURITY_AUDIT.md)
- [DATA_STORAGE_AND_WIPE_REPORT.md](DATA_STORAGE_AND_WIPE_REPORT.md)
- [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)
- [TARGET_MICROSERVICES_ARCHITECTURE.md](TARGET_MICROSERVICES_ARCHITECTURE.md)
- [MICROSERVICES_RESTRUCTURING_PLAN.md](MICROSERVICES_RESTRUCTURING_PLAN.md)
- [DATABASE_OWNERSHIP_MATRIX.md](DATABASE_OWNERSHIP_MATRIX.md)
- [SERVICE_COMMUNICATION_MATRIX.md](SERVICE_COMMUNICATION_MATRIX.md)
- [PRODUCTION_READINESS_REPORT.md](PRODUCTION_READINESS_REPORT.md)
- [PRE_DEVELOPMENT_ACTION_PLAN.md](PRE_DEVELOPMENT_ACTION_PLAN.md)
- [issues.json](issues.json)

## Supporting evidence

- [SERVICE_INVENTORY.md](SERVICE_INVENTORY.md)
- [API_INVENTORY.md](API_INVENTORY.md)
- [ENVIRONMENT_VARIABLE_INVENTORY.md](ENVIRONMENT_VARIABLE_INVENTORY.md)
- [TEST_EXECUTION.md](TEST_EXECUTION.md)
- [STARTUP_VERIFICATION.md](STARTUP_VERIFICATION.md)
- [MODIFICATION_LEDGER.md](MODIFICATION_LEDGER.md)
- [inventory.json](inventory.json)
- [runtime_inventory.json](runtime_inventory.json)
- [storage_detail.json](storage_detail.json)
- [DATA_WIPE_MANIFEST.json](DATA_WIPE_MANIFEST.json)
- [backup_manifest.json](backup_manifest.json)
- [postgres_restore_verification.json](postgres_restore_verification.json)
- [metabase_metadata_verification.json](metabase_metadata_verification.json)
- [migration_verification.json](migration_verification.json)
- [container_migration_verification.json](container_migration_verification.json)
- [migration_drift_detail.json](migration_drift_detail.json)
- [startup_verification.json](startup_verification.json)
- [final_storage_verification.json](final_storage_verification.json)
- [summary.json](summary.json)

Before-state files are immutable snapshots of the original deployment. Startup/final-storage files describe the later verification. Counts are scoped and explained; NOT VERIFIED is not PASS. Backups are ignored and intentionally not linked as public downloadable artifacts.
