# ForgeFlow ⚡

**ForgeFlow** is a production-grade, distributed job processing and workflow orchestration platform built with Python, Django REST Framework, and PostgreSQL. It provides robust multi-tenant organization isolation, granular Role-Based Access Control (RBAC), JWT authentication, comprehensive execution attempt history, and interactive OpenAPI 3 (Swagger) documentation.

---

## 🏛️ Architecture & Domain Hierarchy

```text
User (JWT Identity)
 └── Organization (Tenant Boundary)
       ├── Memberships (Roles: OWNER, ADMIN, DEVELOPER, VIEWER)
       ├── Teams (Departmental grouping)
       ├── API Keys (Machine identity)
       └── Jobs (Execution lifecycle)
             └── Job Attempts (Full execution audit trail)
                   ├── Attempt #1 → FAILED (timeout / error captured)
                   ├── Attempt #2 → FAILED (retry recorded)
                   └── Attempt #3 → SUCCESS (result stored)
```

---

## 🚀 Key Features

- **Multi-Tenant Architecture**: Strict tenant isolation guaranteeing users can only view and manage jobs and members within their authorized organizations.
- **Hierarchical RBAC**: Four-tier permission system (`OWNER > ADMIN > DEVELOPER > VIEWER`) enforcing object-level permissions across all endpoints.
- **JWT Authentication with Token Rotation**: Secure 15-minute access tokens with 7-day rotating and blacklisted refresh tokens.
- **Job Lifecycle & Observability**: State machine tracking (`PENDING`, `QUEUED`, `RUNNING`, `SUCCESS`, `FAILED`, `RETRYING`, `CANCELLED`) with persistent attempt history.
- **Interactive OpenAPI 3 / Swagger Docs**: Live API documentation and testing powered by `drf-spectacular`.
- **Comprehensive Test Suite**: 100% automated test coverage across models, authentication lifecycle, failure modes, RBAC matrices, and tenant isolation.

---

## 🛡️ Role-Based Access Control (RBAC) Matrix

| Action | Endpoint | OWNER | ADMIN | DEVELOPER | VIEWER |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **View Jobs** | `GET /api/v1/jobs/` | ✅ `200` | ✅ `200` | ✅ `200` | ✅ `200` |
| **Create Jobs** | `POST /api/v1/jobs/` | ✅ `201` | ✅ `201` | ✅ `201` | ❌ `403` |
| **Enqueue Jobs** | `POST /api/v1/jobs/{id}/enqueue/` | ✅ `200` | ✅ `200` | ✅ `200` | ❌ `403` |
| **Cancel Jobs** | `POST /api/v1/jobs/{id}/cancel/` | ✅ `200` | ✅ `200` | ✅ `200` | ❌ `403` |
| **Manage Members** | `POST /api/v1/organizations/{id}/members/` | ✅ `201` | ✅ `201` | ❌ `403` | ❌ `403` |
| **Delete Org** | `DELETE /api/v1/organizations/{id}/` | ✅ `204` | ❌ `403` | ❌ `403` | ❌ `403` |

---

## ⚙️ Distributed Architecture Flow (Phase 6 & 7)

```text
Client (REST HTTP)
       │  POST /api/v1/jobs/ (status: PENDING)
       │  POST /api/v1/jobs/{id}/enqueue/
       ▼
  Django API
       │
       ├── 1. Write state to PostgreSQL (status: QUEUED, queued_at: now)
       │
       └── 2. LPUSH jobs:<queue> <job_id>
               │
               ▼
          Redis Queue
               │
               │  3. BRPOP jobs:<queue> (Blocking FIFO Pop)
               ▼
        Custom Worker (Python Engine - No Celery)
               │
               ├── 4. Update PostgreSQL: status = RUNNING, record JobAttempt #N
               ├── 5. Execute task logic (echo, math_compute, sleep_task, etc.)
               └── 6. Update PostgreSQL: status = SUCCESS / FAILED, save result / error
```

---

## 🛠️ Technology Stack

- **Backend Framework**: Django 5.1 & Django REST Framework 3.15
- **Database**: PostgreSQL 16 (running via Docker on host port `5434`)
- **Queue / In-Memory Store**: Redis 7 (running via Docker on host port `6379`)
- **Worker Engine**: Custom asynchronous worker with signal trapping, attempt auditing, and FIFO queues
- **Authentication**: `djangorestframework-simplejwt` with token blacklist
- **API Documentation**: `drf-spectacular` (OpenAPI 3.0 / Swagger UI / Redoc)
- **Testing**: `pytest` & `pytest-django`

---

## 📂 Project Structure

```text
ForgeFlow/
├── backend/                      # Django backend application
│   ├── apps/
│   │   ├── accounts/             # User model, JWT registration, login, refresh, logout
│   │   ├── core/                 # Health checks (DB + Redis) & Redis Lab command
│   │   │   ├── redis_client.py   # Redis connection pool & health verification
│   │   │   └── management/commands/redis_lab.py  # Interactive Redis Fundamentals Lab
│   │   ├── jobs/                 # Job submission, status state machine, attempt history
│   │   │   ├── queue.py          # RedisJobQueue (LPUSH / BRPOP primitives)
│   │   │   ├── tasks.py          # Extensible Task Handler Registry (echo, math, etc.)
│   │   │   ├── worker.py         # CustomWorker distributed execution engine
│   │   │   └── management/commands/run_worker.py # Custom Worker CLI runner
│   │   └── organizations/        # Multi-tenancy, memberships, teams, API keys, RBAC
│   ├── config/                   # Django settings, URLs, ASGI/WSGI configuration
│   ├── manage.py
│   ├── pytest.ini
│   ├── requirements.txt          # Python dependencies
│   └── .env                      # Local environment configuration
├── docker-compose.yml            # PostgreSQL 16 & Redis 7 service definitions
├── LICENSE
└── README.md
```

---

## ⚡ Quick Start Guide

### 1. Prerequisites
- Docker & Docker Compose
- Python 3.12+

### 2. Start PostgreSQL & Redis Services
```bash
docker compose up -d
```

### 3. Setup Virtual Environment
```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt
```

### 4. Configure Environment Variables
Verify or create `backend/.env`:
```ini
DEBUG=True
SECRET_KEY=forgeflow-local-dev-secret-key-change-in-production-12345
DB_NAME=forgeflow
DB_USER=postgres
DB_PASSWORD=postgrespassword
DB_HOST=127.0.0.1
DB_PORT=5434
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_URL=redis://127.0.0.1:6379/0
```

### 5. Run Migrations
```bash
cd backend
python manage.py migrate
```

### 6. Interactive Redis Fundamentals Lab (Phase 6)
Run the interactive lab to explore Redis data structures, expiration, atomic transactions, pub/sub, and queuing:
```bash
python manage.py redis_lab
```

### 7. Run the Custom Worker (Phase 7)
Launch the distributed custom worker to consume and process jobs:
```bash
python manage.py run_worker --queues default,high
```
Or run in **burst mode** (process all pending queue items and exit):
```bash
python manage.py run_worker --burst
```

### 8. Start the Development API Server
```bash
python manage.py runserver
```
The API is now live at `http://127.0.0.1:8000/`.

---

## 📖 Interactive API Documentation

Once the server is running, explore and test the endpoints directly in your browser:

- **Swagger UI**: [http://127.0.0.1:8000/api/docs/](http://127.0.0.1:8000/api/docs/)
- **Redoc UI**: [http://127.0.0.1:8000/api/redoc/](http://127.0.0.1:8000/api/redoc/)
- **OpenAPI 3 Schema**: [http://127.0.0.1:8000/api/schema/](http://127.0.0.1:8000/api/schema/)

---

## 🧪 Running the Test Suite

Run the full automated test suite using `pytest`:

```bash
source .venv/bin/activate && cd backend
pytest -v
```

All 52 test cases across authentication, multi-tenant isolation, RBAC matrices, Redis queue primitives, enqueue REST API, and Custom Worker execution lifecycle will execute.

---

## 🛣️ Roadmap & Engineering Phases

- [x] **Phase 1**: Django + PostgreSQL + Docker Compose foundation with health check verification.
- [x] **Phase 2**: Domain models for Users, Organizations, Memberships, Teams, Jobs, and JobAttempts.
- [x] **Phase 3**: JWT authentication (Register, Login, Token Refresh Rotation, Logout Blacklist).
- [x] **Phase 4**: Multi-tenancy & 4-tier RBAC permission hierarchy.
- [x] **Phase 5**: Top-level Job REST API (`POST`, `GET`, `GET by ID`, `POST cancel`) and Swagger docs.
- [x] **Phase 6**: Redis Fundamentals Lab & Manual Queue Integration (`LPUSH` / `BRPOP`).
- [x] **Phase 7**: First Custom Distributed Worker Engine (No Celery) with database state machine & attempt audit trails.
- [ ] **Phase 8**: Celery Integration & Multi-Worker Fleet Orchestration.
- [ ] **Phase 9**: Worker timeout detection, heartbeats, and exponential backoff retries.
- [ ] **Phase 10**: Scoped API Keys for machine-to-machine worker authentication.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
