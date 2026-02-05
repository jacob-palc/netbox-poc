# NMS Integration for Sequential Webhook Processing

## Problem
When a device is onboarded:
1. NetBox triggers webhooks to both NMS (Server2) and Telemetry
2. If NMS validation fails, Telemetry has already started generating configs (WRONG!)

## Solution
Telemetry service acts as a **gateway**:
1. Receives webhook from NetBox
2. **FIRST** validates device with NMS Server2 (POST /device)
3. **ONLY IF** NMS returns success (200), proceed with telemetry config generation
4. If NMS fails, DO NOT generate telemetry config

## Architecture

```
NetBox → Webhook → Telemetry Service → NMS Server2 (validate)
                           ↓
                  [If NMS OK] → Generate Config
                  [If NMS FAIL] → Stop (no config)
```

## Environment Variables

Add these to your telemetry service:

```bash
# Enable NMS validation (required)
NMS_VALIDATION_ENABLED=true

# Server2 (NMS) configuration
SERVER2_BASE_URL=http://10.4.160.240:8081
SERVER2_AUTH_ENDPOINT=/api/auth/signin
SERVER2_DEVICE_ENDPOINT=/device
SERVER2_USERNAME=admin
SERVER2_PASSWORD=admin
```

## Docker Compose Example

```yaml
telemetry-webhook:
  build:
    context: ./telemetry-webhook
    dockerfile: Dockerfile
  environment:
    # Telemetry settings
    WEBHOOK_PORT: "5000"
    TELEGRAF_CONFIG_DIR: "/telegraf-configs"

    # NMS Integration (Server2)
    NMS_VALIDATION_ENABLED: "true"
    SERVER2_BASE_URL: "http://10.4.160.240:8081"
    SERVER2_AUTH_ENDPOINT: "/api/auth/signin"
    SERVER2_DEVICE_ENDPOINT: "/device"
    SERVER2_USERNAME: "admin"
    SERVER2_PASSWORD: "admin"

    # Database
    POSTGRES_HOST: "postgres"
    POSTGRES_DB: "netpulse"
    POSTGRES_USER: "netpulse"
    POSTGRES_PASSWORD: "netpulse123"
  ports:
    - "5000:5000"
```

## Workflow

### For NEW Devices (event: "created")

1. Telemetry receives webhook from NetBox
2. Extract device info (IP, username, password from custom fields)
3. Call NMS Server2:
   - POST to `/api/auth/signin` with admin credentials
   - POST to `/device` with device payload:
     ```json
     {
       "ipAddress": "10.4.160.240",
       "username": "rootadmin",
       "password": "Root@123",
       "licenseKey": ""
     }
     ```
4. If NMS returns 200:
   - Proceed with telemetry config generation
   - Log: "NMS validation SUCCEEDED - proceeding with telemetry config"
5. If NMS fails:
   - STOP processing
   - Log: "NMS validation FAILED - NOT processing telemetry config"

### For UPDATED Devices (event: "updated")

- Process directly (device already validated on creation)
- No NMS validation needed

### For DELETED Devices (event: "deleted")

- Delete config directly
- No NMS validation needed

## Testing

```bash
# Test with NMS validation enabled
curl -X POST http://localhost:5000/endpoint \
  -H "Content-Type: application/json" \
  -d '{
    "event": "created",
    "model": "dcim.device",
    "timestamp": "2026-02-05T10:00:00+00:00",
    "data": {
      "id": 1,
      "name": "test-router",
      "primary_ip4": {"address": "10.4.160.240/32"},
      "device_type": {"model": "Router", "manufacturer": {"name": "Cisco"}},
      "site": {"name": "Default"},
      "role": {"name": "Router"},
      "custom_fields": {
        "username": "rootadmin",
        "password": "Root@123"
      }
    }
  }'
```

## Logs

Success:
```
level=info msg="Validating new device with NMS Server2" device=test-router ip=10.4.160.240
level=info msg="Validating device with NMS Server2" url=http://10.4.160.240:8081/device
level=info msg="Device validated successfully by NMS Server2" device=test-router message="Given device is added successfully"
level=info msg="NMS validation SUCCEEDED - proceeding with telemetry config"
level=info msg="Device telemetry config created successfully" device=test-router
```

Failure:
```
level=info msg="Validating new device with NMS Server2" device=test-router ip=10.4.160.240
level=error msg="NMS validation FAILED - NOT processing telemetry config" device=test-router error="SSH validation failed"
```

## Disable NMS Validation

To disable NMS validation and process all webhooks directly:

```bash
NMS_VALIDATION_ENABLED=false
```

Or simply don't set the variable (defaults to disabled).
