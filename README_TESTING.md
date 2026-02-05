# NetBox Device Onboarding - Testing Guide

This guide explains how to run and test the complete device onboarding flow with webhook integration.

## Architecture Overview

```
┌──────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   NMS UI     │     │       NetBox        │     │  Telemetry Service  │
│  (or Script) │────▶│  - Creates Device   │────▶│  - Receives Webhook │
│              │     │  - Triggers Event   │     │  - Decrypts Password│
│              │     │  - Sends Webhook    │     │  - Starts Monitoring│
└──────────────┘     └─────────────────────┘     └─────────────────────┘
```

## Prerequisites

- Docker and Docker Compose installed
- Python 3.8+ (for running setup/test scripts)
- `requests` and `cryptography` Python packages

## Quick Start

### Step 1: Start the Services

```bash
cd c:\Users\jacob.rajan\Downloads\netbox-main

# Start all services (NetBox, PostgreSQL, Redis, Telemetry Mock)
docker-compose up -d

# Wait for NetBox to be ready (this can take 2-3 minutes on first run)
docker-compose logs -f netbox
# Wait until you see "Listening at: http://0.0.0.0:8080"
```

### Step 2: Run Setup Script

```bash
# Install required Python packages
pip install requests cryptography

# Run the setup script to create custom fields, device types, webhook, etc.
python setup_netbox.py
```

### Step 3: Test the Flow

```bash
# Run the automated test
python test_onboarding.py
```

### Step 4: Access the Services

| Service | URL | Credentials |
|---------|-----|-------------|
| NetBox UI | http://localhost:8000 | admin / admin123 |
| NetBox API | http://localhost:8000/api/ | Token: 0123456789abcdef0123456789abcdef01234567 |
| Telemetry Service | http://172.27.1.67:5000/endpoint | Your telemetry API |
| Telemetry Mock (optional) | http://localhost:5000 | For local testing |

## Manual Testing via NetBox UI

### Option 1: Use the Onboarding Script

1. Login to NetBox at http://localhost:8000 (admin / admin123)
2. Navigate to **Customization → Scripts**
3. Find and run **"Simple Device Onboarding"**
4. Fill in the form:
   - Device IP: `192.168.1.100`
   - Username: `admin`
   - Password: `secret123`
   - Device Type: Select "CTC Union MaxLinear 10GE CPE"
   - Device Role: Select "CPE"
5. Click **Run Script**
6. Check the script output for success

### Option 2: Create Device Manually

1. Navigate to **Devices → Devices → Add**
2. Fill in device details:
   - Name: `TEST-DEVICE-001`
   - Device Type: Select any configured type
   - Device Role: Select any configured role
   - Site: "Default Site"
   - Status: Active
3. Scroll to **Custom Fields**:
   - Onboarding Username: `admin`
   - Onboarding Password: `your-encrypted-password`
   - Onboarding Status: `success`
   - Device Source: `manual`
4. Save the device

### Verify Webhook Delivery

1. Navigate to **Operations → Webhooks**
2. Click on "Device Onboarding Webhook"
3. Scroll to **Recent Deliveries**
4. Check for successful delivery (HTTP 200)

Or check the telemetry mock service:

```bash
# View received webhooks
curl http://localhost:5000/api/v1/webhooks
```

## Testing via REST API

### Create Device via API

```bash
# Create a device with onboarding custom fields
curl -X POST http://localhost:8000/api/dcim/devices/ \
  -H "Authorization: Token 0123456789abcdef0123456789abcdef01234567" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "API-TEST-DEVICE",
    "device_type": 1,
    "role": 1,
    "site": 1,
    "status": "active",
    "custom_fields": {
      "onboarding_username": "admin",
      "onboarding_password": "encrypted-password-here",
      "onboarding_status": "success",
      "device_source": "manual"
    }
  }'
```

### Check Webhook Delivery

```bash
# View all received webhooks
curl http://localhost:5000/api/v1/webhooks

# Clear webhooks for fresh testing
curl -X POST http://localhost:5000/api/v1/webhooks/clear
```

## Expected Webhook Payload

When a device is created/updated with `onboarding_status: success`, the telemetry service receives:

```json
{
  "event": "device.onboarded",
  "timestamp": "2026-02-05T12:00:00+00:00",
  "data": {
    "device_id": 1,
    "device_name": "CPE-1-100",
    "ip_address": "192.168.1.100",
    "username": "admin",
    "password": "gAAAAABl...(encrypted)",
    "device_role": "CPE",
    "device_type": "CTC Union MaxLinear 10GE CPE",
    "manufacturer": "CTC Union",
    "model": "MaxLinear 10GE CPE",
    "site": "Default Site",
    "status": "active",
    "reachable": null,
    "device_source": "manual",
    "last_onboarded": "2026-02-05T12:00:00+00:00",
    "onboarding_status": "success"
  }
}
```

## Troubleshooting

### NetBox Not Starting

```bash
# Check container logs
docker-compose logs netbox

# Restart the stack
docker-compose down
docker-compose up -d
```

### Webhook Not Being Delivered

1. **Check Event Rule is enabled:**
   - Go to Operations → Event Rules
   - Verify "Device Onboarding Event" is enabled

2. **Check Webhook is enabled:**
   - Go to Operations → Webhooks
   - Verify "Device Onboarding Webhook" is enabled

3. **Check NetBox Worker is running:**
   ```bash
   docker-compose logs netbox-worker
   ```

4. **Check conditions match:**
   - Event rule has condition: `custom_field_data.onboarding_status = success`
   - Make sure device has this custom field set

### Password Encryption

The password is encrypted using Fernet symmetric encryption. Both NetBox and the telemetry service must use the same key.

**Encryption Key:** `XPmjtY0wwxQbD0ezEMDhGlAo2_JGXb6yB4yp5I-MnGA=`

To decrypt on the telemetry side:

```python
from cryptography.fernet import Fernet

key = "XPmjtY0wwxQbD0ezEMDhGlAo2_JGXb6yB4yp5I-MnGA="
cipher = Fernet(key.encode())
decrypted = cipher.decrypt(encrypted_password.encode()).decode()
```

## Cleanup

```bash
# Stop all services
docker-compose down

# Stop and remove all data
docker-compose down -v
```

## File Structure

```
netbox-main/
├── docker-compose.yml              # Docker setup for testing
├── Dockerfile.telemetry-mock       # Dockerfile for mock telemetry service
├── telemetry_mock_service.py       # Mock telemetry service code
├── setup_netbox.py                 # Setup script (custom fields, device types, webhook)
├── test_onboarding.py              # Automated test script
├── README_TESTING.md               # This file
└── netbox/
    └── scripts/
        ├── simple_device_onboarding.py   # NetBox onboarding script
        ├── api_views.py                  # REST API endpoints
        └── *.md                          # Documentation files
```
