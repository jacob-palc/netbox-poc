# NetBox Device Onboarding & Telemetry Platform

## Project Plan & Technical Overview

**Prepared by:** Network Platform Engineering Team
**Date:** February 2026
**Version:** 1.0

---

## 1. Executive Summary

This project delivers an automated device lifecycle management platform built on top of NetBox (open-source network source of truth). The platform enables network engineers to onboard network devices (CPEs, switches, routers) via a REST API, continuously monitor their reachability, validate SSH credentials, and push real-time telemetry notifications to an external telemetry system.

**Key outcomes:**
- Automated device onboarding replacing manual NetBox data entry
- Real-time webhook notifications to telemetry on every device event
- Continuous reachability monitoring at scale (20,000+ devices)
- SSH credential validation before telemetry notification
- Single API call to onboard one device or bulk onboard up to 1,000 devices

---

## 2. Business Problem

| Problem | Impact |
|---------|--------|
| Manual device registration in NetBox is slow and error-prone | Onboarding 100+ devices takes hours of manual work |
| No automated telemetry integration | Telemetry team has no visibility into newly onboarded devices |
| No reachability monitoring | Network team discovers unreachable devices only when users report issues |
| No credential validation | Devices with bad SSH credentials get onboarded silently, causing downstream failures |
| No bulk provisioning | Large-scale deployments require one-by-one device entry |

---

## 3. Solution Architecture

```
                         ┌──────────────────┐
                         │  Network Engineer │
                         │   / Automation    │
                         └────────┬─────────┘
                                  │  REST API
                                  ▼
                    ┌─────────────────────────┐
                    │   Onboarding API (5001) │
                    │   - Manual onboarding   │
                    │   - DHCP onboarding     │
                    │   - Bulk onboarding     │
                    │   - IP/MAC validation   │
                    └────────────┬────────────┘
                                 │  NetBox REST API
                                 ▼
┌────────────┐     ┌─────────────────────────┐     ┌──────────────────┐
│ PostgreSQL │◄────│       NetBox (8000)      │────►│   Redis (6379)   │
│  Database  │     │   - Device management   │     │   Job Queue      │
└────────────┘     │   - IP address mgmt     │     └────────┬─────────┘
                   │   - Custom fields       │              │
                   │   - Webhook config      │              │
                   └──────────┬──────────────┘              │
                              │                             │
                   ┌──────────▼──────────┐       ┌──────────▼──────────┐
                   │   Device Monitor    │       │   NetBox Worker     │
                   │   - Bulk ping       │       │   - Process jobs    │
                   │   - fping (batch)   │       │   - Send webhooks   │
                   │   - State tracking  │       │   - SSH validation  │
                   │   - 20K+ devices    │       └──────────┬──────────┘
                   └─────────────────────┘                  │
                                                            │  HTTP POST
                                                            ▼
                                                 ┌─────────────────────┐
                                                 │  Telemetry Service  │
                                                 │  (172.27.1.70:5000) │
                                                 └─────────────────────┘
```

### Component Overview

| Component | Technology | Port | Purpose |
|-----------|-----------|------|---------|
| NetBox | Django / Python 3.12 | 8000 | Network source of truth — UI, REST API, device database |
| NetBox Worker | RQ (Redis Queue) | — | Background job processor — sends webhooks to telemetry |
| Onboarding API | Flask / Python 3.11 | 5001 | REST API for device onboarding (manual, DHCP, bulk) |
| Device Monitor | Python / fping | — | Continuous ICMP reachability monitoring |
| SSH Validator | Paramiko (inside NetBox) | — | SSH credential validation before telemetry push |
| PostgreSQL | PostgreSQL 15 | 5432 | Device data persistence |
| Redis | Redis 7 | 6379 | Job queue for async webhook processing |

---

## 4. Key Workflows

### 4.1 Device Onboarding Flow

```
API Request (IP, credentials, device type, role)
    │
    ├─► Validate input (IP format, duplicates)
    ├─► Encrypt password (Fernet AES-128)
    ├─► Create device in NetBox
    ├─► Create management interface (mgmt0)
    ├─► Create IP address (/32 CIDR)
    ├─► Set primary IP on device
    │
    └─► NetBox Event Rule triggers
            │
            ├─► Job queued in Redis
            ├─► Worker picks up job
            ├─► [Optional] SSH validation via Paramiko
            └─► HTTP POST to Telemetry Service
```

### 4.2 Reachability Monitoring Flow

```
Every 60 seconds:
    │
    ├─► Fetch all devices with primary IP from NetBox
    ├─► Batch ping with fping (500 devices per batch)
    ├─► Compare current status with previous status
    ├─► Update only changed devices in NetBox
    │       │
    │       └─► Device update triggers webhook
    │               └─► Telemetry notified of status change
    └─► Repeat
```

### 4.3 Webhook → Telemetry Flow

```
Device created/updated in NetBox
    │
    ├─► Django signal fires
    ├─► Event Rule matches (dcim.device)
    ├─► Job queued in Redis (RQ)
    ├─► NetBox Worker picks up job
    ├─► send_webhook() executes
    └─► HTTP POST to telemetry endpoint
            │
            └─► Full device JSON payload:
                  - Device ID, name, status
                  - IP address
                  - Credentials (encrypted)
                  - Device type, role, site
                  - Reachability status
                  - SSH authentication status
```

---

## 5. Data Model

### Custom Fields on Device

| Field | Type | Visibility | Purpose |
|-------|------|-----------|---------|
| `username` | Text | Visible | SSH username for device access |
| `password` | Text | Hidden | Fernet-encrypted SSH password |
| `reachable` | Boolean | Visible | ICMP ping reachability status |
| `authentication` | Boolean | Visible | SSH credential validation result |
| `management` | Boolean | Visible | Whether device is under active management |

### Device Taxonomy

| Category | Items |
|----------|-------|
| Manufacturers | CTC Union, Edgecore, Exaware |
| Device Types | MaxLinear 10GE CPE, ECS4120-28Fv2-I, AS5916-54XL, AS7315-27X |
| Device Roles | CPE, Access Switch, Router |
| Sites | Default Site (expandable) |

---

## 6. API Specification

### Onboarding API (Port 5001)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/onboard` | Onboard single device (IP-based) |
| `POST` | `/api/onboard/dhcp` | Onboard device via MAC (DHCP) |
| `POST` | `/api/onboard/bulk` | Bulk onboard up to 1,000 devices |
| `POST` | `/api/validate/ip` | Check if IP already exists |
| `POST` | `/api/validate/mac` | Check if MAC already exists |
| `GET` | `/api/device-types` | List available device types |
| `GET` | `/api/device-roles` | List available device roles |
| `GET` | `/api/sites` | List available sites |
| `GET` | `/health` | Health check |

### Example: Onboard a device

**Request:**
```json
POST /api/onboard
{
    "ip": "192.168.1.100",
    "device_type": 1,
    "role": 1,
    "username": "admin",
    "password": "admin123",
    "name": "cpe-site-a-001"
}
```

**Response:**
```json
{
    "success": true,
    "device_id": 42,
    "message": "Device cpe-site-a-001 onboarded successfully"
}
```

### Example: Bulk onboard

**Request:**
```json
POST /api/onboard/bulk
{
    "devices": [
        {"ip": "192.168.1.101", "device_type": 1, "role": 1, "username": "admin", "password": "pass1"},
        {"ip": "192.168.1.102", "device_type": 1, "role": 1, "username": "admin", "password": "pass2"},
        {"ip": "192.168.1.103", "device_type": 2, "role": 2, "username": "admin", "password": "pass3"}
    ]
}
```

**Response:**
```json
{
    "total": 3,
    "successful": 3,
    "failed": 0,
    "results": [
        {"device": "192.168.1.101", "success": true, "device_id": 43},
        {"device": "192.168.1.102", "success": true, "device_id": 44},
        {"device": "192.168.1.103", "success": true, "device_id": 45}
    ]
}
```

---

## 7. Security

| Concern | Mitigation |
|---------|-----------|
| Password storage | Fernet symmetric encryption (AES-128-CBC) — passwords never stored in plaintext |
| API authentication | Token-based authentication for all NetBox API calls |
| SSH validation | Paramiko with `AutoAddPolicy` — validates credentials before telemetry push |
| Network isolation | All internal services communicate via Docker network — only ports 8000 (NetBox) and 5001 (API) exposed |
| SSL | Configurable SSL verification on webhook delivery (disabled for testing) |

**Production hardening required:**
- Replace default API token with unique generated token
- Replace default superuser credentials
- Enable SSL verification on webhooks
- Use Docker secrets for encryption keys and passwords
- Restrict exposed ports via firewall rules

---

## 8. Performance & Scalability

### Device Monitor Performance

| Scale | Ping Time | Update Time | Total Cycle |
|-------|-----------|-------------|-------------|
| 500 devices | ~5s | ~2s | ~7s |
| 5,000 devices | ~30s | ~10s | ~40s |
| 20,000 devices | ~2min | ~30s | ~2.5min |

**Key optimizations:**
- `fping` for batch ICMP (1000x faster than sequential ping)
- State-change-only updates (reduces API calls by 90%+)
- `asyncio + aiohttp` for concurrent NetBox API calls (50 max concurrent)
- Batch processing (500 devices per batch)

### Onboarding API Performance

| Operation | Throughput |
|-----------|-----------|
| Single device onboard | ~1-2 seconds |
| Bulk onboard (100 devices) | ~15-20 seconds (15 parallel workers) |
| Bulk onboard (1,000 devices) | ~2-3 minutes (15 parallel workers) |

---

## 9. Implementation Phases

### Phase 1: Infrastructure (Week 1)
- Set up Docker Compose with PostgreSQL, Redis, NetBox, NetBox Worker
- Create custom NetBox Docker image with Paramiko
- Verify NetBox UI and API accessible

### Phase 2: NetBox Configuration (Week 1)
- Create setup script for custom fields, device taxonomy, webhook, event rules
- Verify webhook triggers on device creation via NetBox UI

### Phase 3: Onboarding API (Week 2)
- Build Flask API with manual, DHCP, and bulk onboarding
- Dockerize and integrate into Docker Compose stack
- Test end-to-end: API → NetBox → webhook → telemetry

### Phase 4: Device Monitor (Week 2-3)
- Build reachability monitor with fping and async updates
- Dockerize and integrate into Docker Compose stack
- Verify reachability status changes trigger webhooks

### Phase 5: SSH Validation (Week 3)
- Create SSH validator module using Paramiko
- Integrate into webhook pipeline (gated on device creation)
- Test: valid credentials → telemetry notified; invalid → blocked

### Phase 6: Integration Testing & Hardening (Week 4)
- End-to-end testing with real telemetry service
- Performance testing at scale
- Security hardening for production

---

## 10. Deployment

### Prerequisites
- Docker and Docker Compose installed on target VM
- Network connectivity to telemetry service (172.27.1.70:5000)
- Network connectivity to target devices (for ICMP and SSH)

### Deployment Steps
```bash
# 1. Clone repository
git clone <repo-url> && cd netbox-poc

# 2. Start all services
docker-compose up -d

# 3. Wait for NetBox to be healthy (~60s)
docker-compose logs -f netbox  # Watch for "ready" message

# 4. Configure NetBox
python3 setup_netbox.py --telemetry-url http://172.27.1.70:5000/endpoint

# 5. Verify all services running
docker-compose ps

# 6. Test device onboarding
curl -X POST http://localhost:5001/api/onboard \
  -H "Content-Type: application/json" \
  -d '{"ip":"192.168.1.100","device_type":1,"role":1,"username":"admin","password":"admin123"}'

# 7. Verify webhook delivery
docker compose logs -f netbox-worker
# Should show: "Request succeeded; response status 200"
```

---

## 11. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Telemetry service unavailable | Medium | Webhooks fail, events lost | RQ retries failed jobs; add dead-letter queue for persistent failures |
| NetBox Worker crashes | Low | Webhooks queued but not sent | Docker restart policy (`unless-stopped`); monitoring on worker container |
| fping not available on host | Low | Monitor falls back to slow sequential ping | Dockerfile installs fping; fallback logic implemented |
| SSH validation timeout on slow devices | Medium | Webhook delivery delayed | Configurable timeout (default 30s); validation is optional |
| Database corruption on unclean shutdown | Low | Data loss | PostgreSQL WAL logging; recommend regular backups |

---

## 12. Success Criteria

- [ ] Device onboarded via API appears in NetBox within 2 seconds
- [ ] Webhook arrives at telemetry service within 5 seconds of device creation
- [ ] Device reachability status updates within 60 seconds of state change
- [ ] Bulk onboarding of 100 devices completes in under 30 seconds
- [ ] System handles 20,000+ monitored devices without degradation
- [ ] All passwords stored encrypted, never exposed in plaintext

---

## 13. Dependencies

| Dependency | Owner | Status |
|-----------|-------|--------|
| Telemetry service endpoint (172.27.1.70:5000) | Telemetry Team | Available |
| Docker host VM | Infrastructure Team | Provisioned |
| Network access to managed devices | Network Team | Required |
| NetBox v4.2 Docker image | Open Source (netboxcommunity) | Available |

---

## 14. Future Enhancements

- **SNMP Discovery:** Auto-discover device type and model via SNMP during onboarding
- **Config Backup:** Periodic SSH-based configuration backup after onboarding
- **Dashboard:** Web UI for onboarding status, monitoring, and telemetry health
- **RBAC:** Role-based access control for onboarding API (per-site permissions)
- **HA Deployment:** Multi-node NetBox with load balancer for high availability
- **Alerting:** Integration with PagerDuty/Slack for reachability alerts
