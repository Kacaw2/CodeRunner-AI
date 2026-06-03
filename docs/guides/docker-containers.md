# Docker Containers

> Last updated: 2026-06-01
> Source of truth: root `compose.yaml`

This file records the Docker services used by the local CodeRunner-AI runtime,
what each container is responsible for, and which repository modules it runs.

## Current Service List

Run this from the repository root to verify the active service list:

```powershell
docker compose config --services
docker compose ps
```

The root compose deployment defines six services:

| Service | Container | Role | Main Port |
|---|---|---|---|
| `db` | `educode_db` | MySQL application database | `${MYSQL_PORT:-3306}:3306` |
| `redis` | `educode_redis` | Redis cache / coordination backend | `${REDIS_PORT:-6379}:6379` |
| `executor` | `educode_executor` | Isolated code execution sandbox | internal `8300` |
| `mcp_gateway` | `educode_mcp_gateway` | MCP tool gateway over streamable HTTP | `${MCP_PORT:-8200}:8200` |
| `web` | `educode_web` | Flask main business application and user-facing API | `${WEB_PORT:-9900}:9900` |
| `workers` | `educode_workers` | FastAPI Agent Host / async agent worker runtime | `${AGENT_HOST_PORT:-8100}:8100` |

On this Windows machine, `9900` may be reserved by the OS excluded-port range.
Use `WEB_PORT=19900` in local `.env` when Docker cannot bind `9900`.
The browser entry then becomes:

```text
http://localhost:19900
```

## Runtime Topology

```text
Browser / API client
  -> web (Flask main app, :9900 inside container)
      -> db (MySQL)
      -> redis
      -> executor (sandbox HTTP service, internal :8300)
      -> workers (Agent Host, internal :8100)
          -> mcp_gateway (MCP transport, internal/external :8200)
              -> tool runtime modules
```

The important boundary is:

- `web` owns user-facing routes, auth, business APIs, request validation, and persistence.
- `workers` owns agent runtime execution and async agent workflows.
- `mcp_gateway` owns MCP tool transport, capability verification, and tool access enforcement.
- `executor` owns untrusted code execution and stays isolated from the application network.

## Container Responsibilities

### `db` / `educode_db`

**Purpose:** Persistent MySQL database for the main application.

**Responsibilities:**

- Stores users, auth state, problems, submissions, conversations, agent task records, and other relational app data.
- Initializes schema seed SQL from `docker/init.sql` when the MySQL volume is first created.
- Provides the database backend used by `web`, `workers`, and `mcp_gateway`.

**Compose details:**

- Image: `mysql:8.0`
- Volume: `mysql_data:/var/lib/mysql`
- Init mount: `./docker/init.sql:/docker-entrypoint-initdb.d/init.sql:ro`
- Network: `educode_network`
- Health check: `mysqladmin ping`

**Repository modules connected to it:**

- `app/models/`
- `app/services/`
- `workers/`
- `mcp_gateway/`

### `redis` / `educode_redis`

**Purpose:** Shared Redis service for runtime coordination.

**Responsibilities:**

- Provides cache and coordination storage for app and worker paths.
- Supplies `REDIS_URL=redis://redis:6379/0` to `web`, `workers`, and `mcp_gateway`.

**Compose details:**

- Image: `redis:7-alpine`
- Volume: `redis_data:/data`
- Network: `educode_network`
- Health check: `redis-cli ping`

**Repository modules connected to it:**

- `app/`
- `workers/`
- `mcp_gateway/`

### `executor` / `educode_executor`

**Purpose:** Isolated sandbox service for running submitted code.

**Responsibilities:**

- Runs code execution requests over HTTP at `http://executor:8300/run`.
- Enforces resource limits such as memory, timeout, stdout/stderr caps, PID limit, read-only root filesystem, dropped Linux capabilities, and `no-new-privileges`.
- Keeps untrusted code execution outside the main Flask container.

**Compose details:**

- Build file: `docker/Dockerfile.executor`
- Source copied into image:
  - `app/core/executor.py`
  - `docker/executor_server.py`
- Internal service port: `8300`
- Network: `executor_network`
- `executor_network` is marked `internal: true`.
- Used by `web` through `EXECUTOR_REMOTE_URL=http://executor:8300/run`.

**Repository modules connected to it:**

- `app/core/executor.py`
- `app/services/executor_service.py`
- `docker/executor_server.py`

### `chroma` / `educode_chroma`

**Purpose:** Shared Chroma 1.x vector database for RAG collections.

`web`, `workers`, and `mcp_gateway` connect to it over the internal Docker
network (`CHROMA_MODE=http`, `CHROMA_HOST=chroma`, `CHROMA_PORT=8000`) instead of
each writing local Chroma files directly. This gives a single persistent
boundary and keeps all app services on the same KB state.

**Compose details:**

- Image: `chromadb/chroma:1.5.9`
- Internal service port: `8000` (not published to the host by default)
- Network: `educode_network`
- Persistent state: `chroma_data` volume mounted at `/chroma/chroma`
- Health check: socket connect to `localhost:8000`

### `web` / `educode_web`

**Purpose:** Main Flask application and user-facing backend.

**Responsibilities:**

- Serves the main application and public/user-facing API routes.
- Handles auth, RBAC, sessions, problem APIs, submission APIs, AI API endpoints, and health checks.
- Performs Flask-side validation before proxying agent requests when `USE_AGENT_HOST_PROXY=true`.
- Calls the executor service for code execution.
- Calls the Agent Host at `http://workers:8100` for async/agent workflows.
- Loads the knowledge base health probe and reads/writes vector data through the `chroma` HTTP service.

**Compose details:**

- Build file: `docker/Dockerfile`
- Internal app port: `9900`
- Local host port: `${WEB_PORT:-9900}`. On this machine prefer `WEB_PORT=19900`.
- Health endpoint: `http://localhost:<WEB_PORT>/health`
- Networks:
  - `educode_network`
  - `executor_network`
- Depends on healthy:
  - `db`
  - `redis`
  - `executor`
  - `chroma`

**Bind-mounted source modules:**

The `web` service bind-mounts these paths read-only, so many code-only changes
can be picked up by recreating or restarting `web` without rebuilding the image:

- `app/`
- `core/`
- `tools/`
- `agents/`
- `graph/`
- `memory/`
- `knowledge/`
- `models/`
- `workers/`
- `mcp_gateway/`
- `scripts/`

**Writable/runtime mounts:**

- `./uploads:/app/uploads`
- `./logs:/app/logs`
- `executor_tmp:/tmp/executor`
- `hf_cache:/app/.hf_cache`

**Repository modules owned or served here:**

- `app/`
- `core/`
- `tools/`
- `agents/`
- `graph/`
- `knowledge/`
- `memory/`
- `models/`

### `workers` / `educode_workers`

**Purpose:** FastAPI Agent Host and async agent runtime.

**Responsibilities:**

- Runs the agent worker API at port `8100`.
- Executes async AI chat/task workflows requested by `web`.
- Loads agent runtime modules and talks back to the Flask app through `FLASK_BASE_URL=http://web:9900`.
- Calls tools through MCP transport when `MCP_AGENT_TRANSPORT=streamable-http`.
- Signs short-lived internal MCP capability tokens with `MCP_INTERNAL_SIGNING_KEY`.
- Calls `mcp_gateway` at `http://mcp_gateway:8200/mcp`.

**Compose details:**

- Build file: `docker/Dockerfile.workers`
- Internal and default local port: `${AGENT_HOST_PORT:-8100}:8100`
- Health endpoint: `http://localhost:<AGENT_HOST_PORT>/api/health`
- Network: `educode_network`
- Depends on healthy:
  - `db`
  - `redis`
  - `web`
  - `mcp_gateway`
  - `chroma`

**Source copied into image by `docker/Dockerfile.workers`:**

- `app/`
- `core/`
- `tools/`
- `agents/`
- `graph/`
- `memory/`
- `knowledge/`
- `models/`
- `workers/`
- `mcp_gateway/`

Because these paths are copied into the `workers` image, changes under
`agents/`, `workers/`, `tools/`, `graph/`, `core/`, or `mcp_gateway/` normally
require rebuilding or recreating this service unless a development override adds
bind mounts.

**Repository modules owned or executed here:**

- `workers/`
- `agents/`
- `graph/`
- `core/`
- `tools/`
- `knowledge/`
- `memory/`

### `mcp_gateway` / `educode_mcp_gateway`

**Purpose:** MCP gateway service for agent tool calls.

**Responsibilities:**

- Runs `python -m mcp_gateway --transport streamable-http --host 0.0.0.0 --port 8200`.
- Exposes the MCP HTTP endpoint used by the Agent Host.
- Verifies internal capability tokens with `MCP_INTERNAL_VERIFY_KEY`.
- Connects tool calls to database, Redis, knowledge-base storage, and tool runtime modules.
- Provides the runtime boundary where tool permissions, scopes, risk policy, and auditability should be enforced.

**Compose details:**

- Build file: `docker/Dockerfile.workers`
- Entry point overrides the normal worker command.
- Internal and default local port: `${MCP_PORT:-8200}:8200`
- Network: `educode_network`
- Depends on healthy:
  - `db`
  - `redis`
  - `chroma`
- Health check: socket connect to `localhost:8200`

**Volumes:**

- `hf_cache:/app/.hf_cache`

**Repository modules owned or executed here:**

- `mcp_gateway/`
- `tools/`
- `core/`
- `knowledge/`
- `models/`

## Data Volumes

| Volume | Used By | Purpose |
|---|---|---|
| `mysql_data` | `db` | Persistent MySQL data |
| `redis_data` | `redis` | Persistent Redis data |
| `executor_tmp` | `web` | Temporary executor working files mounted at `/tmp/executor` |
| `chroma_data` | `chroma` | Chroma 1.x vector-store persistence (mounted at `/chroma/chroma`) |
| `hf_cache` | `web`, `workers`, `mcp_gateway` | HuggingFace / model cache |

Do not remove `mysql_data` unless you intentionally want to reset the database.
Removing `chroma_data` resets the vector index only, not the MySQL source data;
rebuild it with `scripts.migrate_kb` (and re-import manual collections).

## Common Local Commands

Start or recreate the full stack:

```powershell
docker compose up -d
docker compose ps
```

Recreate only the user-facing app after changing host port settings:

```powershell
docker compose up -d --force-recreate web
docker compose ps web
docker port educode_web
```

Rebuild services affected by agent/runtime code copied into images:

```powershell
docker compose up -d --build workers mcp_gateway
```

Restart services when code is bind-mounted and no image rebuild is needed:

```powershell
docker compose restart web
```

View logs:

```powershell
docker compose logs -f web
docker compose logs -f workers
docker compose logs -f mcp_gateway
```

Check health:

```powershell
Invoke-RestMethod http://localhost:19900/health
Invoke-RestMethod http://localhost:8100/api/health
```

## Local Troubleshooting Notes

- If Docker reports `ports are not available` for `0.0.0.0:9900` on Windows,
  check excluded port ranges:

  ```powershell
  netsh interface ipv4 show excludedportrange protocol=tcp
  ```

  If `9900` is inside an excluded range, set `WEB_PORT=19900` in local `.env`
  and recreate `web`.

- `docker compose restart web` only restarts the existing container. It does
  not apply changed port mappings. Use `docker compose up -d --force-recreate web`
  after changing `.env` port values.

- A health response like `knowledge_base: degraded: '_type'` came from the old
  embedded ChromaDB reading legacy on-disk collection config. The stack now runs
  Chroma in server mode (`chroma` service) with a fresh `chroma_data` volume, so
  this error should no longer occur. If KB health is `degraded`, check that the
  `chroma` container is healthy and reachable at `chroma:8000` from app services.

- After a Chroma dependency or schema change, export manual KB collections first,
  then recreate Chroma and rebuild:

  ```powershell
  docker compose exec -T web python -m scripts.migrate_kb
  docker compose exec -T web python -m scripts.import_kb_collections --input /tmp/kb-manual-export.json
  ```
