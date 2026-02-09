# NetBox Device Management System

A comprehensive device onboarding, monitoring, and webhook orchestration system for NetBox v4.2.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Services](#services)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

---

## Overview

This system provides:

1. **Device Onboarding API** (Port 5001) - REST API for device provisioning
   - Manual onboarding using IP address as unique identifier
   - DHCP onboarding using MAC address as unique identifier
   - IPv4 and IPv6 support

2. **Webhook Handler** (Port 5002) - Orchestrates webhook flow
   - Server2 SSH validation before telemetry
   - Server1 telemetry forwarding

3. **Device Monitor** - High-performance reachability monitoring
   - Scales to 20,000+ devices using fping
   - Only updates NetBox on state change (reduces API load by 90%+)

---

## Architecture

```
                                 +------------------+
                                 |     NetBox       |
                                 |   (Port 8000)    |
                                 +--------+---------+
                                          |
           +------------------------------+------------------------------+
           |                              |                              |
           v                              v                              v
+------------------+          +-------------------+          +-------------------+
| Onboarding API   |          | Webhook Handler   |          | Device Monitor    |
|   (Port 5001)    |          |   (Port 5002)     |          |  (Background)     |
+--------+---------+          +---------+---------+          +---------+---------+
         |                              |                              |
         |                    +---------+---------+                    |
         |                    |                   |                    |
         v                    v                   v                    |
   Creates devices     +-----------+       +-----------+              |
   in NetBox          | Server2    |       | Server1    |              |
                      | (SSH Val)  |       | (Telemetry)|              |
                      | 10.4.160.  |       | 172.27.1.  |              |
                      | 240:5000   |       | 70:5000    |              |
                      +-----------+       +-----------+              |
                                                                      |
                                                                      v
                                                              Updates reachable
                                                              status via ping
```

---

## Services

### 1. Onboarding API (Port 5001)

Flask REST API for device provisioning in NetBox.

#### Features
- **Manual Onboarding**: IP address as unique identifier
- **DHCP Onboarding**: MAC address as unique identifier
- Password encryption using Fernet
- Duplicate validation for IP and MAC
- IPv4 and IPv6 support
- DHCP IP reassignment (only if device is down)

#### Files
- `onboarding_api.py` - Main API service
- `Dockerfile.onboarding-api` - Docker build file

---

### 2. Webhook Handler (Port 5002)

Orchestrates webhook flow between NetBox, Server2 (SSH validation), and Server1 (Telemetry).

#### Flow

| Event | Flow |
|-------|------|
| **Device Created** | NetBox -> Server2 (SSH validation) -> If success -> Server1 (Telemetry) |
| **Device Updated** | NetBox -> Server1 (Telemetry) directly |
| **Device Deleted** | NetBox -> Server1 (Telemetry) directly |

#### Features
- Token-based authentication with Server2
- Password decryption for SSH validation
- Detailed logging for debugging

#### Files
- `webhook_handler.py` - Main webhook service
- `Dockerfile.webhook-handler` - Docker build file

---

### 3. Device Monitor (Background Service)

High-performance device reachability monitor optimized for 20,000+ devices.

#### Features
- Uses `fping` for bulk ICMP pinging (1000x faster than individual pings)
- `asyncio + aiohttp` for concurrent NetBox API calls
- Only updates devices when state changes (reduces API load by 90%+)
- Connection pooling for efficiency
- Batch processing (500 devices per batch)

#### Performance Metrics
| Devices | Ping Time | Update Time |
|---------|-----------|-------------|
| 500 | ~5 seconds | ~2 seconds |
| 5,000 | ~30 seconds | ~10 seconds |
| 20,000 | ~2 minutes | ~30 seconds |

#### Files
- `device_monitor.py` - Main monitor service
- `Dockerfile.device-monitor` - Docker build file

---

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Network access to Server2 (10.4.160.240:5000) and Server1 (172.27.1.70:5000)

### Start All Services

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Check service status
docker-compose ps
```

### Service URLs

| Service | URL | Description |
|---------|-----|-------------|
| NetBox | http://localhost:8000 | NetBox UI |
| Onboarding API | http://localhost:5001 | Device onboarding |
| Webhook Handler | http://localhost:5002 | Webhook orchestration |
| Telemetry Mock | http://localhost:5000 | Mock telemetry (testing) |

---

## API Reference

### Onboarding API (Port 5001)

#### Manual Onboarding (IP Required)

```bash
POST /api/onboard
Content-Type: application/json

{
    "ip": "192.168.1.100",      # Required - IPv4 or IPv6
    "device_type": 1,            # Required
    "role": 1,                   # Required
    "site": 1,                   # Optional (default: 1)
    "username": "admin",         # Optional
    "password": "secret123"      # Optional (encrypted)
}
```

**Example:**
```bash
curl -X POST http://localhost:5001/api/onboard \
  -H "Content-Type: application/json" \
  -d '{"ip": "192.168.1.100", "device_type": 1, "role": 1}'
```

**Response:**
```json
{
    "status": "success",
    "message": "Device onboarded successfully",
    "data": {
        "device_id": 42,
        "device_name": "192.168.1.100",
        "ip_address": "192.168.1.100",
        "ip_version": "ipv4",
        "ip_id": 15,
        "primary_ip_assigned": true,
        "onboard_type": "manual"
    }
}
```

#### DHCP Onboarding (MAC Required)

```bash
POST /api/onboard/dhcp
Content-Type: application/json

{
    "mac": "AA:BB:CC:DD:EE:FF",  # Required
    "ip": "192.168.1.100",        # Optional (DHCP assigned)
    "device_type": 1,             # Required
    "role": 1,                    # Required
    "site": 1,                    # Optional
    "hostname": "device-001"      # Optional
}
```

**Example:**
```bash
curl -X POST http://localhost:5001/api/onboard/dhcp \
  -H "Content-Type: application/json" \
  -d '{"mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.1.100", "device_type": 1, "role": 1}'
```

**DHCP IP Reassignment Logic:**
- If IP is assigned to a device marked as **down** (reachable=false): IP is reassigned to new device
- If IP is assigned to a device marked as **up** (reachable=true): Request is rejected

#### Validation Endpoints

```bash
# Validate IP
POST /api/validate/ip
{"ip": "192.168.1.100"}

# Validate MAC
POST /api/validate/mac
{"mac": "AA:BB:CC:DD:EE:FF"}
```

#### Helper Endpoints

```bash
GET /api/device-types    # List device types
GET /api/device-roles    # List device roles
GET /api/sites           # List sites
GET /health              # Health check
```

---

### Webhook Handler API (Port 5002)

#### Webhook Endpoint

```bash
POST /webhook
Content-Type: application/json

# NetBox webhook payload (automatic)
{
    "event": "created",
    "model": "dcim.device",
    "timestamp": "2024-01-15T10:30:00Z",
    "data": {
        "id": 42,
        "name": "192.168.1.100",
        "primary_ip4": {"address": "192.168.1.100/32"},
        "custom_fields": {
            "username": "admin",
            "password": "encrypted_password"
        }
    }
}
```

#### Health Check

```bash
GET /health
```

---

## Configuration

### Environment Variables

#### Onboarding API

| Variable | Default | Description |
|----------|---------|-------------|
| `NETBOX_URL` | http://localhost:8000 | NetBox API URL |
| `NETBOX_TOKEN` | (see docker-compose) | NetBox API token |
| `NETBOX_DEVICE_ENCRYPTION_KEY` | (see docker-compose) | Fernet key for passwords |

#### Webhook Handler

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER2_BASE_URL` | http://10.4.160.240:5000 | Server2 SSH validation URL |
| `SERVER2_AUTH_ENDPOINT` | /api/auth/signin | Auth endpoint |
| `SERVER2_DEVICE_ENDPOINT` | /device | Device validation endpoint |
| `SERVER2_USERNAME` | admin | Server2 username |
| `SERVER2_PASSWORD` | admin | Server2 password |
| `SERVER1_WEBHOOK_URL` | http://172.27.1.70:5000/endpoint | Telemetry URL |
| `NETBOX_DEVICE_ENCRYPTION_KEY` | (see docker-compose) | Fernet key for passwords |

#### Device Monitor

| Variable | Default | Description |
|----------|---------|-------------|
| `NETBOX_URL` | http://localhost:8000 | NetBox API URL |
| `NETBOX_TOKEN` | (see docker-compose) | NetBox API token |
| `PING_INTERVAL` | 60 | Seconds between ping cycles |
| `PING_COUNT` | 3 | ICMP packets per host |
| `PING_TIMEOUT` | 2000 | Timeout in milliseconds |
| `BATCH_SIZE` | 500 | Devices per fping batch |
| `MAX_CONCURRENT_UPDATES` | 50 | Max parallel NetBox updates |

---

## Deployment

### NetBox Webhook Configuration

To enable automatic webhook flow, configure a webhook in NetBox:

1. Go to **NetBox UI** -> **Operations** -> **Webhooks**
2. Create new webhook:
   - **Name**: Device Events Handler
   - **Object Types**: dcim > device
   - **Events**: Create, Update, Delete
   - **URL**: `http://webhook-handler:5002/webhook`
   - **HTTP Method**: POST
   - **HTTP Content Type**: application/json

### Custom Fields Required

Create these custom fields in NetBox:

| Field Name | Type | Object Types | Description |
|------------|------|--------------|-------------|
| `username` | Text | dcim.device | Device SSH username |
| `password` | Text | dcim.device | Encrypted SSH password |
| `reachable` | Boolean | dcim.device | Device reachability status |

### Docker Compose Services

```yaml
services:
  netbox:           # Port 8000 - NetBox UI and API
  netbox-worker:    # Background task worker
  postgres:         # PostgreSQL database
  redis:            # Cache and task queue
  onboarding-api:   # Port 5001 - Device onboarding
  webhook-handler:  # Port 5002 - Webhook orchestration
  device-monitor:   # Background - Reachability monitor
  telemetry-mock:   # Port 5000 - Mock telemetry (testing)
```

---

## Troubleshooting

### Common Issues

#### 1. DHCP IP Creation Fails with Duplicate Error

**Problem**: IP already exists in NetBox.

**Solution**: The system automatically handles this by checking if the existing device is reachable:
- If device is **down**: IP is reassigned to new device
- If device is **up**: Request is rejected with error

#### 2. MAC Address Not Saved to Interface

**Problem**: Virtual interface type doesn't support MAC addresses.

**Solution**: Use interface type `other` instead of `virtual`:
```python
interface_response = session.post(
    f"{NETBOX_URL}/api/dcim/interfaces/",
    json={
        'device': device_id,
        'name': 'eth0',
        'type': 'other',  # Not 'virtual'
        'mac_address': mac_address
    }
)
```

#### 3. Webhook Not Triggering

**Problem**: NetBox webhook not configured.

**Solution**: Configure webhook in NetBox UI to point to `http://webhook-handler:5002/webhook`

#### 4. Server2 Connection Failed

**Problem**: Cannot connect to Server2 for SSH validation.

**Solution**: Check:
- Server2 is running on `10.4.160.240:5000`
- Network connectivity from Docker container to Server2
- Server2 credentials are correct

#### 5. Device Monitor Not Updating

**Problem**: Device states not updating in NetBox.

**Solution**: Ensure:
- `reachable` custom field exists in NetBox
- Device has a primary IP address assigned
- NetBox API token has write permissions

### Viewing Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f onboarding-api
docker-compose logs -f webhook-handler
docker-compose logs -f device-monitor
```

### Rebuilding Services

```bash
# Rebuild specific service
docker-compose build onboarding-api
docker-compose up -d onboarding-api

# Rebuild all
docker-compose build
docker-compose up -d
```

---

## Files Summary

| File | Description |
|------|-------------|
| `onboarding_api.py` | Device onboarding REST API |
| `webhook_handler.py` | Webhook orchestration service |
| `device_monitor.py` | High-performance ping monitor |
| `Dockerfile.onboarding-api` | Docker build for onboarding API |
| `Dockerfile.webhook-handler` | Docker build for webhook handler |
| `Dockerfile.device-monitor` | Docker build for device monitor |
| `docker-compose.yml` | Multi-service Docker configuration |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | 2024 | Added DHCP onboarding with MAC, IP reassignment logic, webhook handler |
| 1.0 | 2024 | Initial manual onboarding, device monitor |
