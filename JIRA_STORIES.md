# NetBox Device Onboarding Platform — Jira Stories

## Epic: NetBox Device Onboarding & Telemetry Integration

**Epic Description:** Build a complete device lifecycle management platform using NetBox as the source of truth. The system enables device onboarding via REST API, continuous reachability monitoring, SSH credential validation, and real-time telemetry notifications via webhooks.

---

## Phase 1: Docker Infrastructure & NetBox Core

### Story 1.1 — Set up Docker Compose with PostgreSQL and Redis

**Type:** Story
**Priority:** Highest
**Story Points:** 2
**Labels:** infrastructure, backend

**Description:**
As a platform engineer, I need the foundational database and cache services running in Docker so that NetBox has its required dependencies.

**Acceptance Criteria:**
- [ ] `docker-compose.yml` created with PostgreSQL 15 service (internal port 5432)
- [ ] Redis 7-alpine service added (internal port 6379)
- [ ] Health checks configured for both services
- [ ] Environment variables defined for DB credentials (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`)
- [ ] Shared Docker network created for inter-service communication
- [ ] `docker-compose up -d` starts both services and they become healthy

---

### Story 1.2 — Create custom NetBox Docker image with Paramiko

**Type:** Story
**Priority:** Highest
**Story Points:** 2
**Labels:** infrastructure, backend

**Description:**
As a platform engineer, I need a custom NetBox Docker image that extends the official `netboxcommunity/netbox:v4.2` image with Paramiko installed, so that SSH validation can be performed directly inside NetBox in the future.

**Acceptance Criteria:**
- [ ] `Dockerfile.netbox-custom` created extending `netboxcommunity/netbox:v4.2`
- [ ] Paramiko installed inside the NetBox virtualenv via pip bootstrap
- [ ] `ssh_validator.py` copied to `/opt/netbox/netbox/extras/ssh_validator.py`
- [ ] File permissions set correctly (`chown unit:root`)
- [ ] Original `extras/webhooks.py` is NOT overwritten (breaks RQ worker imports)
- [ ] Image builds successfully: `docker-compose build netbox`

---

### Story 1.3 — Add NetBox and NetBox Worker services to Docker Compose

**Type:** Story
**Priority:** Highest
**Story Points:** 3
**Labels:** infrastructure, backend

**Description:**
As a platform engineer, I need the NetBox application server and its background worker running in Docker so that the web UI, REST API, and asynchronous job processing (webhooks) are available.

**Acceptance Criteria:**
- [ ] NetBox service added: port 8000, built from `Dockerfile.netbox-custom`
- [ ] NetBox Worker service added: same image, runs RQ worker (`high`, `default`, `low` queues)
- [ ] Both depend on PostgreSQL and Redis health checks
- [ ] Environment variables configured: `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `SECRET_KEY`, `REDIS_HOST`, `SUPERUSER_NAME`, `SUPERUSER_PASSWORD`, `SUPERUSER_API_TOKEN`, `SSH_VALIDATION_ENABLED=false`
- [ ] NetBox UI accessible at `http://localhost:8000`
- [ ] Admin login works with configured superuser credentials
- [ ] Worker container is running and listening on queues (verified via `docker compose logs netbox-worker`)

**Technical Notes:**
- The worker is critical for webhook delivery. Without it, webhooks are queued in Redis but never sent.
- `SSH_VALIDATION_ENABLED` set to `false` initially for testing.

---

## Phase 2: NetBox Configuration via Setup Script

### Story 2.1 — Create setup script with custom fields

**Type:** Story
**Priority:** High
**Story Points:** 3
**Labels:** backend, configuration

**Description:**
As a platform engineer, I need a Python script that configures NetBox with the required custom fields so that devices can store onboarding metadata (credentials, reachability status).

**Acceptance Criteria:**
- [ ] `setup_netbox.py` created with CLI arguments (`--netbox-url`, `--token`, `--telemetry-url`)
- [ ] Script waits for NetBox readiness (polls `/api/` with retries)
- [ ] 5 custom fields created on `dcim.device`:
  - `username` (text) — SSH username
  - `password` (text, hidden UI) — Encrypted SSH password
  - `reachable` (boolean) — Ping reachability status
  - `authentication` (boolean) — SSH auth result
  - `management` (boolean) — Under management flag
- [ ] Uses `object_types: ['dcim.device']` (NetBox v4.2 API format)
- [ ] Idempotent: checks if custom field exists before creating
- [ ] Script runs without errors on a fresh NetBox instance

---

### Story 2.2 — Add manufacturers, device types, device roles, and site

**Type:** Story
**Priority:** High
**Story Points:** 2
**Labels:** backend, configuration

**Description:**
As a network engineer, I need predefined manufacturers, device types, device roles, and a default site configured in NetBox so that devices can be onboarded with proper categorization.

**Acceptance Criteria:**
- [ ] 3 manufacturers created: CTC Union, Edgecore, Exaware
- [ ] 4 device types created:
  - MaxLinear 10GE CPE (CTC Union)
  - ECS4120-28Fv2-I (Edgecore)
  - AS5916-54XL (Exaware)
  - AS7315-27X (Exaware)
- [ ] 3 device roles created: CPE, Access Switch, Router (with distinct colors)
- [ ] 1 default site created: "Default Site" (status: active)
- [ ] All use slug-based existence checks (idempotent)
- [ ] Added to `setup_netbox.py` and runs as part of the setup flow

---

### Story 2.3 — Add webhook and event rules for telemetry

**Type:** Story
**Priority:** High
**Story Points:** 3
**Labels:** backend, configuration, webhook

**Description:**
As a platform engineer, I need a webhook and event rules configured in NetBox so that device create/update events are automatically forwarded to the telemetry service.

**Acceptance Criteria:**
- [ ] Webhook "Device Onboarding Webhook" created:
  - `payload_url`: configurable telemetry URL (default `http://172.27.1.70:5000/endpoint`)
  - `http_method`: POST
  - `http_content_type`: application/json
  - `body_template`: empty (NetBox sends full serialized device JSON)
  - `ssl_verification`: false (for testing)
- [ ] Event rule "Device Onboarding Event" created: triggers on `object_created` for `dcim.device`
- [ ] Event rule "Device Update Event" created: triggers on `object_updated` for `dcim.device`
- [ ] Both event rules use `action_type: webhook` and point to the webhook via `action_object_id`
- [ ] Uses `object_types` and `event_types` fields (NetBox v4.2 API — NOT `content_types`/`type_create`)
- [ ] If webhook already exists, script PATCHes it (ensures template/URL updates are applied)
- [ ] Verified: creating a device via NetBox UI triggers a webhook job in the worker logs

**Technical Notes:**
- `body_template` must be empty string. Custom Jinja2 templates can cause `Invalid JSON payload` errors if fields like `custom_field_data` (wrong key) are used instead of `custom_fields`.
- Event rules use `action_object_type: extras.webhook` to link to the webhook.

---

## Phase 3: Onboarding API Service

### Story 3.1 — Create Onboarding API with manual device onboarding

**Type:** Story
**Priority:** High
**Story Points:** 5
**Labels:** backend, api, onboarding

**Description:**
As a network engineer, I need a REST API to onboard devices into NetBox by providing an IP address and credentials, so that device provisioning can be automated.

**Acceptance Criteria:**
- [ ] `onboarding_api.py` created as a Flask application
- [ ] `POST /api/onboard` endpoint implemented with input fields:
  - Required: `ip`, `device_type`, `role`, `username`, `password`
  - Optional: `name` (defaults to IP), `site` (defaults to 1)
- [ ] IP format validation (IPv4 and IPv6)
- [ ] Duplicate IP check via NetBox API (`/api/ipam/ip-addresses/?address=X`)
- [ ] Duplicate device name check
- [ ] Password encrypted with Fernet before storing (`NETBOX_DEVICE_ENCRYPTION_KEY`)
- [ ] Device creation flow:
  1. Create device (`/api/dcim/devices/`) with `custom_fields: {username, password}`
  2. Create interface `mgmt0` (`/api/dcim/interfaces/`)
  3. Create IP address with `/32` CIDR (`/api/ipam/ip-addresses/`)
  4. Set primary IP on device via PATCH
- [ ] Returns JSON: `{success, device_id, message}`
- [ ] Error handling for all NetBox API failures
- [ ] `GET /health` endpoint returns service status

---

### Story 3.2 — Add DHCP onboarding endpoint

**Type:** Story
**Priority:** Medium
**Story Points:** 3
**Labels:** backend, api, onboarding

**Description:**
As a network engineer, I need to onboard devices via MAC address (DHCP scenario) where the IP is not yet known, so that devices discovered via DHCP can be registered.

**Acceptance Criteria:**
- [ ] `POST /api/onboard/dhcp` endpoint implemented
- [ ] Input: `mac_address`, `device_type`, `role`, `username`, `password`
- [ ] MAC address format validation
- [ ] Duplicate MAC check via NetBox API
- [ ] Creates `eth0` interface with MAC address assigned
- [ ] IP can be assigned/reassigned later via update
- [ ] Returns JSON: `{success, device_id, message}`

---

### Story 3.3 — Add bulk onboarding endpoint

**Type:** Story
**Priority:** Medium
**Story Points:** 3
**Labels:** backend, api, onboarding

**Description:**
As a network engineer, I need to onboard multiple devices in a single API call (JSON array or CSV) so that large-scale provisioning is efficient.

**Acceptance Criteria:**
- [ ] `POST /api/onboard/bulk` endpoint implemented
- [ ] Accepts JSON array of device objects
- [ ] Accepts CSV format (auto-detected)
- [ ] Maximum 1000 devices per request
- [ ] Parallel processing with `ThreadPoolExecutor(max_workers=15)`
- [ ] Returns per-device results: `{total, successful, failed, results: [{device, success, error}]}`
- [ ] Individual device failures do not block other devices

---

### Story 3.4 — Add helper and validation endpoints

**Type:** Story
**Priority:** Low
**Story Points:** 2
**Labels:** backend, api

**Description:**
As a frontend developer, I need helper endpoints to fetch available device types, roles, and sites, and validation endpoints to check for duplicates before onboarding.

**Acceptance Criteria:**
- [ ] `GET /api/device-types` — returns list from NetBox
- [ ] `GET /api/device-roles` — returns list from NetBox
- [ ] `GET /api/sites` — returns list from NetBox
- [ ] `POST /api/validate/ip` — checks if IP already exists
- [ ] `POST /api/validate/mac` — checks if MAC already exists
- [ ] All return clean JSON responses

---

### Story 3.5 — Dockerize Onboarding API and add to Docker Compose

**Type:** Story
**Priority:** High
**Story Points:** 2
**Labels:** infrastructure, backend

**Description:**
As a platform engineer, I need the Onboarding API containerized and added to the Docker Compose stack so that it runs alongside NetBox.

**Acceptance Criteria:**
- [ ] `Dockerfile.onboarding-api` created (Python 3.11 slim, Flask, requests, cryptography)
- [ ] Service added to `docker-compose.yml`: port 5001, depends on NetBox healthy
- [ ] Environment variables: `NETBOX_URL=http://netbox:8000`, `NETBOX_TOKEN`, `NETBOX_DEVICE_ENCRYPTION_KEY`
- [ ] Flask-CORS enabled for cross-origin requests
- [ ] `curl http://localhost:5001/health` returns 200

---

## Phase 4: Device Reachability Monitor

### Story 4.1 — Create device reachability monitor service

**Type:** Story
**Priority:** Medium
**Story Points:** 5
**Labels:** backend, monitoring

**Description:**
As a network operations engineer, I need continuous reachability monitoring of all onboarded devices so that the `reachable` custom field is automatically updated and telemetry is notified of status changes.

**Acceptance Criteria:**
- [ ] `device_monitor.py` created as a background loop service
- [ ] Fetches all devices with primary IP from NetBox (paginated)
- [ ] Uses `fping` for bulk ICMP ping (1000x faster than individual pings)
- [ ] Falls back to individual `ping` if `fping` unavailable
- [ ] Batches devices (500 per batch) for scalable processing
- [ ] Only updates NetBox when reachable status changes (reduces API load by 90%+)
- [ ] Uses `asyncio + aiohttp` for concurrent NetBox API updates (max 50 concurrent)
- [ ] Updates `custom_fields.reachable` on each device via PATCH
- [ ] Configurable via environment variables:
  - `PING_INTERVAL`: 60s default
  - `PING_COUNT`: 3 packets
  - `PING_TIMEOUT`: 2000ms
  - `BATCH_SIZE`: 500
  - `MAX_CONCURRENT_UPDATES`: 50
- [ ] Performance targets:
  - 500 devices: ~7s per cycle
  - 5,000 devices: ~40s per cycle
  - 20,000 devices: ~2.5min per cycle

---

### Story 4.2 — Dockerize Device Monitor and add to Docker Compose

**Type:** Story
**Priority:** Medium
**Story Points:** 2
**Labels:** infrastructure, backend

**Description:**
As a platform engineer, I need the device monitor containerized and running as a background service in the Docker stack.

**Acceptance Criteria:**
- [ ] `Dockerfile.device-monitor` created (Python 3.11 slim, fping, iputils-ping, requests, aiohttp)
- [ ] Service added to `docker-compose.yml`: no port exposed (background service)
- [ ] Depends on NetBox healthy
- [ ] Environment variables: `NETBOX_URL`, `NETBOX_TOKEN`, `PING_INTERVAL`, `PING_COUNT`, `PING_TIMEOUT`
- [ ] Monitor starts and logs device ping results to stdout

---

## Phase 5: SSH Credential Validator

### Story 5.1 — Create SSH validator module for NetBox

**Type:** Story
**Priority:** Medium
**Story Points:** 3
**Labels:** backend, security

**Description:**
As a platform engineer, I need an SSH validation module inside NetBox that can verify device credentials via direct Paramiko SSH connection, replacing the need for an external validation service.

**Acceptance Criteria:**
- [ ] `netbox/extras/ssh_validator.py` created with:
  - `SSHValidator` class: connects via Paramiko, runs test command
  - `validate_device(ip, username, password)` method
  - `validate_device_ssh(device_data)` convenience wrapper
- [ ] Extracts IP from `data.primary_ip4.address` (strips CIDR `/32` suffix)
- [ ] Extracts credentials from `data.custom_fields.username` and `data.custom_fields.password`
- [ ] Decrypts Fernet-encrypted password if `NETBOX_DEVICE_ENCRYPTION_KEY` is set
- [ ] Checks `SSH_VALIDATION_ENABLED` environment variable (skip if `false`)
- [ ] Paramiko imported lazily inside method (not top-level) to prevent module loading failures
- [ ] Returns `{success: bool, status_code: int, message: str}`
- [ ] Handles errors: `AuthenticationException` (401), `SSHException` (502), generic (500)
- [ ] Configurable: `SSH_VALIDATION_PORT`, `SSH_VALIDATION_TIMEOUT`, `SSH_VALIDATION_COMMAND`

---

## Phase 6: End-to-End Webhook → Telemetry Integration

### Story 6.1 — Verify end-to-end webhook delivery to telemetry

**Type:** Story
**Priority:** Highest
**Story Points:** 3
**Labels:** integration, webhook, telemetry

**Description:**
As a platform engineer, I need to verify that the complete flow works end-to-end: device onboarding triggers a webhook that reaches the external telemetry service.

**Acceptance Criteria:**
- [ ] All services started: `docker-compose up -d`
- [ ] NetBox configured: `python3 setup_netbox.py`
- [ ] Device onboarded via API:
  ```
  curl -X POST http://localhost:5001/api/onboard \
    -H "Content-Type: application/json" \
    -d '{"ip":"192.168.1.100","device_type":1,"role":1,"username":"admin","password":"admin123"}'
  ```
- [ ] Worker logs show: `Request succeeded; response status 200`
- [ ] Telemetry service receives the webhook payload with full device data
- [ ] Device update (e.g., reachable status change by monitor) also triggers webhook to telemetry

**Verification Commands:**
```bash
# Watch worker process webhooks
docker compose logs -f netbox-worker

# Verify webhook configuration
curl -s http://localhost:8000/api/extras/webhooks/ \
  -H "Authorization: Token <TOKEN>" | python3 -m json.tool

# Verify event rules
curl -s http://localhost:8000/api/extras/event-rules/ \
  -H "Authorization: Token <TOKEN>" | python3 -m json.tool
```

**Definition of Done:**
The webhook JSON payload arrives at the telemetry endpoint with all device fields including: id, name, primary_ip4, custom_fields (username, password, reachable, authentication, management), device_type, role, site, status.

---

### Story 6.2 — Enable SSH validation in webhook pipeline (Future)

**Type:** Story
**Priority:** Low
**Story Points:** 5
**Labels:** backend, security, webhook

**Description:**
As a platform engineer, I need SSH validation to gate webhook delivery so that only devices with valid SSH credentials trigger telemetry notifications.

**Acceptance Criteria:**
- [ ] `SSH_VALIDATION_ENABLED` set to `true` in docker-compose environment
- [ ] SSH validation integrated into the webhook pipeline without overwriting `extras/webhooks.py`
- [ ] On `device_created` event:
  - SSH credentials validated via Paramiko
  - If validation succeeds → webhook sent to telemetry
  - If validation fails → webhook NOT sent, failure logged
- [ ] `custom_fields.authentication` updated to `true`/`false` based on SSH result
- [ ] On `device_updated` event → webhook sent to telemetry directly (no SSH re-validation)

---

## Summary Table

| # | Story | Points | Priority | Phase |
|---|-------|--------|----------|-------|
| 1.1 | Docker Compose with PostgreSQL + Redis | 2 | Highest | 1 |
| 1.2 | Custom NetBox Docker image | 2 | Highest | 1 |
| 1.3 | NetBox + Worker services | 3 | Highest | 1 |
| 2.1 | Setup script with custom fields | 3 | High | 2 |
| 2.2 | Manufacturers, device types, roles, site | 2 | High | 2 |
| 2.3 | Webhook + event rules for telemetry | 3 | High | 2 |
| 3.1 | Manual device onboarding API | 5 | High | 3 |
| 3.2 | DHCP onboarding endpoint | 3 | Medium | 3 |
| 3.3 | Bulk onboarding endpoint | 3 | Medium | 3 |
| 3.4 | Helper + validation endpoints | 2 | Low | 3 |
| 3.5 | Dockerize Onboarding API | 2 | High | 3 |
| 4.1 | Device reachability monitor | 5 | Medium | 4 |
| 4.2 | Dockerize Device Monitor | 2 | Medium | 4 |
| 5.1 | SSH validator module | 3 | Medium | 5 |
| 6.1 | End-to-end webhook → telemetry verification | 3 | Highest | 6 |
| 6.2 | Enable SSH validation in pipeline | 5 | Low | 6 |

**Total Story Points:** 48
