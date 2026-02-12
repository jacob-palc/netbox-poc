# JIRA Stories - NetBox Device Onboarding & Telemetry Platform

## Epic: NB-100 - NetBox Device Onboarding with SSH Validation & Telemetry Pipeline

**Description:** Build an end-to-end device onboarding platform using NetBox as the source of truth. Devices are onboarded via API, validated through Server2 (SSH), and forwarded to the telemetry service for monitoring configuration generation.

**Target Flow:**
```
Device Onboarded → NetBox Event Rule → Webhook → Webhook Handler (5002)
    → Authenticate with Server2 (POST /api/auth/signin)
    → Validate SSH via Server2 (POST /device)
    → Update NetBox custom fields (reachable/authentication)
    → Forward to Telemetry (172.27.1.70:5000/endpoint)
    → Telemetry generates monitoring config based on device role
```

---

## Story 1: NB-101 - Infrastructure Setup (Docker Compose)

**As a** DevOps engineer,
**I want** a containerized NetBox environment with all supporting services,
**So that** the platform can be deployed consistently across environments.

**Acceptance Criteria:**
- All services start with `docker compose up -d`
- Services are health-checked and restart on failure
- Persistent volumes for database and media

### Subtasks

| ID | Subtask | Description | Status |
|----|---------|-------------|--------|
| NB-101-1 | PostgreSQL service | Configure PostgreSQL 15 with `netbox` database, user, password. Add health check (`pg_isready`). Persistent volume `netbox-postgres-data`. | Done |
| NB-101-2 | Redis service | Configure Redis 7 Alpine with AOF persistence. Add health check (`redis-cli ping`). Persistent volume `netbox-redis-data`. | Done |
| NB-101-3 | NetBox application service | Use `netboxcommunity/netbox:v4.2` base image. Map port 8000:8080. Configure DB, Redis, secret key, superuser credentials, API token. Health check on `/login/` with 120s start period. | Done |
| NB-101-4 | NetBox worker service | Run `rqworker` for background task processing (webhooks). Depends on NetBox healthy. Same DB/Redis/secret key config. | Done |
| NB-101-5 | Custom NetBox Dockerfile | Create `Dockerfile.netbox-custom` extending base image. Install `paramiko` into venv for SSH validation. Copy SSH validator script. | Done |
| NB-101-6 | Docker Compose volumes | Define named volumes: `netbox-postgres-data`, `netbox-redis-data`, `netbox-media-files`. Mount scripts directory read-only. | Done |

---

## Story 2: NB-102 - NetBox Configuration & Setup Script

**As a** platform administrator,
**I want** an automated setup script that configures NetBox with all required objects,
**So that** the platform is ready for device onboarding without manual configuration.

**Acceptance Criteria:**
- Single command `python setup_netbox.py` configures everything
- Idempotent: running multiple times doesn't create duplicates
- Cleans up stale webhooks/event rules from previous configurations

### Subtasks

| ID | Subtask | Description | Status |
|----|---------|-------------|--------|
| NB-102-1 | Custom fields creation | Create custom fields on `dcim.device`: `username` (text), `password` (text, encrypted), `reachable` (boolean), `authentication` (boolean), `management` (boolean). Idempotent - skip if exists. | Done |
| NB-102-2 | Manufacturer & device types | Create manufacturers (CTC Union, Generic). Create device types (MaxLinear 10GE CPE, Generic Device) linked to manufacturers. | Done |
| NB-102-3 | Device roles | Create device roles: Router, Switch, CPE with appropriate slugs (`router`, `switch`, `cpe`). | Done |
| NB-102-4 | Default site | Create default site for device assignment. | Done |
| NB-102-5 | Webhook configuration | Create webhook `Device Onboarding Webhook` pointing to `http://webhook-handler:5002/webhook`. Body template with Jinja2 rendering all device fields including `id`, `slug`, `model`, `manufacturer`, `role`, `site`, `status`, `custom_fields`, `primary_ip4`. | Done |
| NB-102-6 | Event rules | Create `Device Onboarding Event` (trigger on `object_created` for `dcim.device`) and `Device Update Event` (trigger on `object_updated`). Both fire the webhook. | Done |
| NB-102-7 | Stale webhook/rule cleanup | Remove any old webhooks not matching the current one (e.g., old direct-to-telemetry webhooks). Remove stale event rules not in managed set. | Done |
| NB-102-8 | Webhook body template with slugs | Include `id`, `name`, `slug` fields in role, site, device_type, manufacturer objects. Include `status.label`. Add `model: "dcim.device"` at top level. Required by telemetry Go service for role-based config generation. | Done |

---

## Story 3: NB-103 - Device Onboarding API

**As a** network engineer,
**I want** a REST API to onboard devices into NetBox with a single API call,
**So that** I can quickly add devices without navigating the NetBox UI.

**Acceptance Criteria:**
- POST `/api/onboard` creates device + interface + IP + assigns primary IP in one call
- Duplicate IP/device detection returns 409
- Passwords are encrypted before storage
- Immediate response includes validation status fields (pending)

### Subtasks

| ID | Subtask | Description | Status |
|----|---------|-------------|--------|
| NB-103-1 | Flask API service | Create `onboarding_api.py` Flask service on port 5001. Add CORS. Create `Dockerfile.onboarding-api`. Add to docker-compose. | Done |
| NB-103-2 | Manual onboarding endpoint | `POST /api/onboard` - accepts `ip`, `device_type`, `role`, `site`, `username`, `password`. Creates device, mgmt0 interface, IP address, assigns primary IP. Returns device_id. | Done |
| NB-103-3 | IP validation & duplicate check | Validate IP format (IPv4/IPv6 via `ipaddress` module). Check if IP or device name already exists in NetBox. Return 409 with existing device details if duplicate. | Done |
| NB-103-4 | Password encryption | Encrypt device passwords using Fernet symmetric encryption before storing in NetBox custom fields. Use `NETBOX_DEVICE_ENCRYPTION_KEY` environment variable. | Done |
| NB-103-5 | DHCP onboarding endpoint | `POST /api/onboard/dhcp` - accepts `mac`, optional `ip`, `device_type`, `role`. MAC-based device naming. IP reassignment if existing device is down (reachable=false). | Done |
| NB-103-6 | Validation endpoints | `POST /api/validate/ip` - check if IP exists. `POST /api/validate/mac` - check if MAC exists. Used by frontend for real-time form validation. | Done |
| NB-103-7 | Helper endpoints | `GET /api/device-types`, `GET /api/device-roles`, `GET /api/sites` - list available options for frontend dropdowns. | Done |
| NB-103-8 | Validation status in response | Include `reachable: null`, `authentication: null`, `management: null`, `validation_status: "pending"` in onboard response so frontend knows validation is in progress. | Done |
| NB-103-9 | Connection pooling | Use `requests.Session` with `HTTPAdapter` for connection pooling (20 connections) to handle concurrent requests to NetBox API. | Done |

---

## Story 4: NB-104 - Webhook Handler (Server2 SSH Validation → Telemetry)

**As a** platform operator,
**I want** device SSH credentials validated through Server2 before telemetry is notified,
**So that** only valid, reachable devices are monitored.

**Acceptance Criteria:**
- Webhook handler receives NetBox webhooks and orchestrates Server2 → NetBox update → Telemetry
- Server2 SSH validation determines reachable/authentication status
- NetBox custom fields updated with validation results
- Telemetry receives the original NetBox webhook structure (pass-through)
- No infinite webhook loops

### Subtasks

| ID | Subtask | Description | Status |
|----|---------|-------------|--------|
| NB-104-1 | Flask webhook service | Create `webhook_handler.py` Flask service on port 5002. Create `Dockerfile.webhook-handler`. Add to docker-compose with Server2, telemetry, NetBox environment variables. | Done |
| NB-104-2 | Server2 authentication | `Server2Client` class. Authenticate with Server2 via `POST /api/auth/signin` to get Bearer token. Handle token storage and refresh. | Done |
| NB-104-3 | Server2 device validation | `POST /device` to Server2 with `ipAddress`, `username`, `password`, `licenseKey`. Parse response message to determine: reachable (true/false), authenticated (true/false). Handle "unreachable", "timeout", "auth fail" messages. Note: Server2 returns HTTP 200 even for failures - must parse message text. | Done |
| NB-104-4 | Password decryption | Decrypt Fernet-encrypted passwords from webhook data before sending plain-text to Server2. | Done |
| NB-104-5 | NetBox custom field update | After Server2 validation, PATCH device in NetBox to update `reachable` and `authentication` custom fields. | Done |
| NB-104-6 | Telemetry forwarding | Forward webhook payload to telemetry service (`http://172.27.1.70:5000/endpoint`). Pass through original NetBox webhook `data` dict unchanged (preserves `slug`, `id`, nested objects). Only update `custom_fields` with validation results. Inject `primary_ip4` if missing (extracted from device name). Add `model: "dcim.device"` at top level. | Done |
| NB-104-7 | Device info extraction | Parse webhook payload to extract: IP address (from `primary_ip4` or device name), credentials, custom fields, device type, role, site. Preserve original `raw_data` for telemetry pass-through. | Done |
| NB-104-8 | Routing logic | Has IP + credentials → Server2 → NetBox update → Telemetry. Has IP, no credentials → Telemetry directly. No IP → Skip (device data incomplete). | Done |

---

## Story 5: NB-105 - Webhook Deduplication & Loop Prevention

**As a** platform operator,
**I want** the webhook handler to prevent infinite loops and redundant processing,
**So that** each device is validated exactly once per onboarding event.

**Acceptance Criteria:**
- No infinite webhook loops when handler updates NetBox
- Device-monitor ping updates (every 60s) don't trigger re-validation
- Dedup window prevents rapid-fire duplicate processing

### Subtasks

| ID | Subtask | Description | Status |
|----|---------|-------------|--------|
| NB-105-1 | Time-based deduplication | Track `_recently_processed` dict (device_id → timestamp). Skip processing if same device was handled within `DEDUP_WINDOW` (10 seconds). Prevents infinite loop: webhook handler updates NetBox → triggers "updated" webhook → caught by dedup. | Done |
| NB-105-2 | Already-validated skip | For `updated` events: if `reachable` and `authentication` are both already set (not null), skip processing. Prevents device-monitor ping updates (every 60s) from triggering full Server2 re-validation + telemetry. | Done |
| NB-105-3 | Re-validation support | To force re-validation, clear `reachable`/`authentication` fields in NetBox. Next webhook will see null values and re-process through Server2. | Done |

---

## Story 6: NB-106 - Concurrent Processing (Bulk Onboarding)

**As a** network engineer,
**I want** to onboard 1000+ devices in a single API call with parallel processing,
**So that** bulk deployments complete in minutes instead of hours.

**Acceptance Criteria:**
- Bulk endpoint accepts JSON array or CSV file
- 15 parallel workers for NetBox API calls
- 15 parallel workers for Server2 SSH validations
- Single manual onboard works during bulk operation
- Progress tracking via polling endpoint

### Subtasks

| ID | Subtask | Description | Status |
|----|---------|-------------|--------|
| NB-106-1 | Bulk onboarding endpoint | `POST /api/onboard/bulk` - accepts JSON `{"devices": [...]}`, CSV file upload, or CSV text body. Validates input, enforces max 1000 devices. Returns summary with per-device results. | Done |
| NB-106-2 | Parallel device creation | `ThreadPoolExecutor` with 15 workers in onboarding API. Each worker creates device + interface + IP independently. Thread-safe with connection pooling. | Done |
| NB-106-3 | CSV parsing | Parse CSV with headers: `ip,device_type,role,site,username,password,mac,hostname`. Auto-detect manual vs DHCP based on fields present. Convert numeric fields. | Done |
| NB-106-4 | Webhook handler thread pool | `ThreadPoolExecutor` with 15 workers (`WEBHOOK_MAX_WORKERS`). Webhook endpoint returns 202 immediately. Heavy processing (Server2 SSH ~5s/device) runs in background threads. 1000 devices @ 5s each = ~5 min (vs ~83 min sequential). | Done |
| NB-106-5 | Bulk lock | Only one bulk operation at a time. Return 429 if another bulk is in progress. Single manual onboards still work via the same webhook → thread pool flow. | Done |
| NB-106-6 | Device status polling endpoint | `POST /api/devices/status` - accepts `{"device_ids": [30, 31, 32]}`. Returns per-device validation status: `pending`, `validated`, `unreachable`, `auth_failed`. Includes summary counts. Frontend polls this after bulk onboard. | Done |

---

## Story 7: NB-107 - Device Reachability Monitor

**As a** network operator,
**I want** continuous ping monitoring of all onboarded devices,
**So that** I can see which devices are online/offline in real-time.

**Acceptance Criteria:**
- Pings all devices with primary IP every 60 seconds
- Updates NetBox `reachable` field based on ping result
- Configurable ping interval, count, and timeout

### Subtasks

| ID | Subtask | Description | Status |
|----|---------|-------------|--------|
| NB-107-1 | Device monitor service | Create `device_monitor.py` service. Create `Dockerfile.device-monitor`. Add to docker-compose with `PING_INTERVAL: 60`, `PING_COUNT: 3`, `PING_TIMEOUT: 2`. | Done |
| NB-107-2 | Device discovery | Query NetBox API for all devices with primary IP. Periodic refresh to pick up new devices. | Done |
| NB-107-3 | Ping monitoring | Ping each device IP. Update `reachable` custom field in NetBox based on result. | Done |
| NB-107-4 | Restart policy | `restart: unless-stopped` for continuous operation. Depends on NetBox healthy. | Done |

---

## Story 8: NB-108 - Telemetry Integration & Payload Compatibility

**As a** telemetry service consumer,
**I want** the webhook payload to match the exact NetBox webhook structure,
**So that** the Go telemetry service can parse device role, site, and generate monitoring configs.

**Acceptance Criteria:**
- Telemetry receives payload with `data` wrapper matching original NetBox webhook format
- Role, site, manufacturer include `id`, `name`, `slug` fields
- Status includes `value` and `label`
- `primary_ip4` is always populated (fallback to device name if not assigned yet)
- Telemetry returns 200 and generates config based on device role

### Subtasks

| ID | Subtask | Description | Status |
|----|---------|-------------|--------|
| NB-108-1 | Payload structure with data wrapper | Wrap device data in `{"event": "...", "timestamp": "...", "model": "dcim.device", "data": {...}}`. The Go service reads `data.role.slug`, `data.site.name`, etc. | Done |
| NB-108-2 | Pass-through original webhook data | Instead of reconstructing payload (losing fields), deep-copy the original `data` dict from webhook and pass through unchanged. Only update `custom_fields` with validation results. | Done |
| NB-108-3 | Slug fields in body template | Update webhook body template to include `id` and `slug` for role, site, device_type, manufacturer. Example: `"role": {"id": 1, "name": "CPE", "slug": "cpe"}`. Required by Go telemetry service for role-based config generation. | Done |
| NB-108-4 | IP address fallback | If `primary_ip4` is null in webhook data (IP not yet assigned when webhook fires), inject `{"address": "<ip>/32"}` using IP extracted from device name. Fixes `device IP address is required` error. | Done |
| NB-108-5 | Role validation compatibility | Telemetry Go service requires role to be one of: `router`, `switch`, `cpe`. Ensure role slug matches these values. NetBox role slugs are auto-generated from name (lowercase, hyphenated). | Done |

---

## Summary - Service Architecture

| Service | Port | Container | Purpose |
|---------|------|-----------|---------|
| PostgreSQL | - | netbox-postgres | Database |
| Redis | - | netbox-redis | Cache & task queue |
| NetBox | 8000 | netbox | Source of truth (UI + API) |
| NetBox Worker | - | netbox-worker | Background webhook dispatch |
| Onboarding API | 5001 | onboarding-api | Device creation REST API |
| Webhook Handler | 5002 | webhook-handler | SSH validation orchestration |
| Device Monitor | - | device-monitor | Continuous ping monitoring |

## End-to-End Flow

```
1. POST /api/onboard (port 5001)
   ├── Create device in NetBox
   ├── Create interface (mgmt0)
   ├── Create IP address
   ├── Assign primary IP
   └── Return 201 { device_id, validation_status: "pending" }

2. NetBox Event Rule fires webhook
   └── NetBox Worker sends POST to webhook-handler:5002/webhook

3. Webhook Handler (port 5002)
   ├── Extract device info from webhook payload
   ├── Dedup check (skip if processed <10s ago)
   ├── Already-validated check (skip if reachable & auth already set)
   ├── Queue to ThreadPool (return 202 immediately)
   └── Background thread:
       ├── Authenticate with Server2 (POST /api/auth/signin)
       ├── Validate SSH via Server2 (POST /device)
       ├── Update NetBox (PATCH reachable/authentication)
       └── Forward to Telemetry (POST /endpoint)

4. Telemetry Go Service (172.27.1.70:5000)
   ├── Parse device role (router/switch/cpe)
   ├── Generate monitoring config
   └── Reload Telegraf (SIGHUP)

5. Frontend polls POST /api/devices/status (port 5001)
   └── Returns { reachable, authentication, validation_status }
```

## Files Changed

| File | Purpose |
|------|---------|
| `docker-compose.yml` | All service definitions, ports, env vars, volumes |
| `Dockerfile.netbox-custom` | Custom NetBox image with paramiko |
| `Dockerfile.webhook-handler` | Webhook handler image |
| `Dockerfile.onboarding-api` | Onboarding API image |
| `Dockerfile.device-monitor` | Device monitor image |
| `setup_netbox.py` | Automated NetBox configuration (custom fields, roles, webhooks, event rules) |
| `onboarding_api.py` | Device onboarding REST API (manual, DHCP, bulk, status polling) |
| `webhook_handler.py` | Webhook orchestration (Server2 SSH → NetBox update → Telemetry) |
