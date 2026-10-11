# Current architecture

Source inspected on 2026-09-13. Use SERVICE_INVENTORY.md for all 24 unified Compose entries and runtime_inventory.json for actual containers, ports, mounts and networks. Declared dependencies do not establish successful runtime behavior. The legacy ETL deployment is a conflicting alternate topology, not six additional product domains.

```mermaid
flowchart TD
  Browser[React Vite frontend] -->|HTTP bearer| Gateway[Django API gateway]
  Gateway --> Auth[Auth]
  Gateway --> Workspace[Workspace]
  Gateway --> Report[Report proxy]
  Gateway --> Voice[Voice and report persistence]
  Gateway --> Query[Query and dataset metadata]
  Gateway --> Viz[Visualization]
  Gateway --> Sub[Subscription]
  Gateway --> Notify[Notification]
  Gateway --> AI[AI Django Dagster Whisper TimesFM]
  Auth <-->|HTTP| Workspace
  Report -->|HTTP report CRUD| Voice
  Voice -->|HTTP membership| Workspace
  Voice -->|HTTP| AI
  Voice -->|HTTP| Query
  Voice -->|HTTP| Viz
  Voice -->|HTTP limits| Sub
  Sub -->|HTTP| Workspace
  Sub -->|HTTP admin summaries| Auth
  Auth & Workspace & Sub & Voice -->|HTTP events| Notify
  Auth & Workspace & Voice & Query & Sub & Notify --> PG[(Shared bi_voice_agent PostgreSQL)]
  Notify -->|Foreign domain ORM reads| PG
  Query --> CH[(Shared ClickHouse)]
  AI -->|Schema and value reads| CH
  AI --> Redis[(Redis AI queue locks cache)]
  AI --> Models[Host Ollama and external OpenRouter]
  Viz --> Models
  Viz --> MB[Standalone Metabase]
  Voice -->|Fallback HTTP| MB
  MB --> H2[(H2 in container writable layer)]
  MB -.->|BI source connections require inventory| CH
  Query -->|HTTP multipart| Connector[ETL connector]
  Connector -->|Native scan| ClamAV[ClamAV]
  Connector --> Files[(Shared uploaded files)]
  Files --> Extractor[ETL extractor]
  Connector --> Kafka[Kafka business topics]
  Kafka --> Detector[ETL detector]
  Kafka --> Extractor
  Extractor --> Kafka
  Kafka --> Transformer[ETL transformer]
  Transformer --> Kafka
  Kafka --> Loader[ETL loader]
  Kafka --> Metadata[ETL metadata]
  Extractor & Transformer & Loader & Metadata --> CH
  Connector & Detector & Extractor & Transformer & Loader & Metadata --> Surreal[(Shared SurrealDB memory)]
  Voice -->|report events no consumer proved| Kafka
  Kafka --> ZK[ZooKeeper]
  KafkaUI[Public Kafka UI] --> Kafka
  Expiry[Notification expiry worker] --> PG
  Expiry & Notify --> SMTP[SMTP provider]
```

The diagram shows active source call categories. Gateway, report and visualization also configure the same PostgreSQL credentials for framework state; that grants access but is not proof of domain queries. AI and ETL configure local SQLite for Django framework state despite descriptions of statelessness. Report's copied ORM references workspace models but that app is absent from its active INSTALLED_APPS.

HTTP dependency depth can reach browser → gateway → report → voice → workspace/auth, or browser → gateway → voice → AI → several sequential model calls, followed by query and Metabase. Report CRUD requires voice availability. Gateway startup is gated on nearly every service, and voice on visualization/query/AI; optional expensive capabilities therefore affect availability of basic APIs.

The gateway checks that Authorization exists but delegates cryptographic verification downstream. It buffers request/response bodies, has a 360-second upstream timeout, uses in-process path/IP throttling, and lacks a TLS edge. No WebSocket implementation was discovered; normal JSON/multipart requests dominate.

PostgreSQL ownership is logically divided in the code but not enforced by database credentials. The notification service explicitly reads five other domains' tables. ETL shares repositories and SurrealDB access. Kafka business communication and shared files conflict with the requested target policy. Redis is presently internal infrastructure for AI, not a discovered inter-service pub/sub bus.

All host-published internal ports are **DEVELOPMENT ONLY** at best. PostgreSQL, ClickHouse, Redis, Kafka, ZooKeeper and SurrealDB should be **DATABASE/INFRASTRUCTURE INTERNAL**. Core services, ETL APIs, Kafka UI and model endpoints should be **INTERNAL ONLY**. Only frontend/TLS gateway and a controlled embedding edge should be **PUBLIC**. Initial bindings use all interfaces; firewall and Internet reachability were not verified.
