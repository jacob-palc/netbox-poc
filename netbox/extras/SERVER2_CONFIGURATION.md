# Server2 NMS Integration Configuration

## Overview

NetBox now validates device SSH credentials with Server2 NMS **before** triggering the telemetry webhook. This prevents generating telemetry configurations for devices with invalid SSH credentials.

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    OPTIMIZED FLOW (20k+ Devices)                │
└─────────────────────────────────────────────────────────────────┘

Device Created in NetBox
    │
    ├─> NetBox Webhook Handler
    │       │
    │       ├─> Step 1: Authenticate with Server2
    │       │   POST /api/auth/signin
    │       │   {username: "admin", password: "admin"}
    │       │   → Get JWT token
    │       │
    │       ├─> Step 2: Validate Device SSH
    │       │   POST /device
    │       │   {ipAddress, username, password, licenseKey}
    │       │   
    │       ├─> If SUCCESS (200 OK):
    │       │   │
    │       │   └─> Send Webhook to Telemetry
    │       │       → Telemetry generates config immediately
    │       │
    │       └─> If FAIL (4xx/5xx):
    │           │
    │           └─> STOP - No webhook sent
    │               → No telemetry config generated
    │               → Logged in NetBox
```

## Configuration

### NetBox Configuration

Add the following to your NetBox `configuration.py`:

```python
#########################
# Server2 NMS Settings  #
#########################

# Enable/disable Server2 validation
SERVER2_VALIDATION_ENABLED = True

# Server2 connection details
SERVER2_BASE_URL = 'http://10.4.160.240:8081'
SERVER2_AUTH_ENDPOINT = '/api/auth/signin'
SERVER2_DEVICE_ENDPOINT = '/device'

# Server2 credentials
SERVER2_USERNAME = 'admin'
SERVER2_PASSWORD = 'admin'
```

### Environment Variables (Alternative)

You can also configure via environment variables:

```bash
export SERVER2_VALIDATION_ENABLED=true
export SERVER2_BASE_URL=http://10.4.160.240:8081
export SERVER2_AUTH_ENDPOINT=/api/auth/signin
export SERVER2_DEVICE_ENDPOINT=/device
export SERVER2_USERNAME=admin
export SERVER2_PASSWORD=admin
```

## Event Handling

The webhook handler now behaves differently based on event type:

| Event Type | Server2 Validation | Telemetry Webhook |
|------------|-------------------|-------------------|
| `created`  | ✅ **YES** - Validates SSH before webhook | Sent only if validation succeeds |
| `updated`  | ❌ No (already validated) | Sent immediately |
| `deleted`  | ❌ No | Sent immediately |

## Device Requirements

For Server2 validation to work, devices must have:

1. **Primary IP Address** - Device must have a primary IPv4 address set
2. **SSH Credentials** - Custom fields must contain:
   - `username` or `ssh_username` (defaults to "admin")
   - `password` or `ssh_password` (defaults to "admin")

## Validation Response Handling

### Success Response (200 OK)

```json
{
    "message": "Given device is added successfully",
    "statusCode": 200
}
```

**Result**: Webhook sent to telemetry, config generated

### Failure Response (4xx/5xx)

```json
{
    "message": "SSH connection failed",
    "statusCode": 401
}
```

**Result**: Webhook **NOT** sent, error logged in NetBox

## Logging

Check NetBox logs for validation status:

```bash
# Successful validation
INFO netbox.webhooks.server2: Authenticating with Server2 at http://10.4.160.240:8081/api/auth/signin
INFO netbox.webhooks.server2: Server2 authentication successful
INFO netbox.webhooks.server2: Validating device 10.4.160.240 with Server2
INFO netbox.webhooks.server2: Device 10.4.160.240 validation successful: Given device is added successfully
INFO netbox.webhooks: Server2 validation successful for device 10.4.160.240: Given device is added successfully

# Failed validation
WARNING netbox.webhooks.server2: Device 10.4.160.240 validation failed: 401 - SSH authentication failed
WARNING netbox.webhooks: Server2 validation failed for device 10.4.160.240: SSH authentication failed (status: 401)
```

## Disabling Validation

To disable Server2 validation (e.g., for testing):

```python
# In configuration.py
SERVER2_VALIDATION_ENABLED = False
```

Or:

```bash
export SERVER2_VALIDATION_ENABLED=false
```

When disabled, all webhooks are sent immediately without validation.

## Telemetry Service Changes

> [!IMPORTANT]
> After deploying this change, the telemetry service no longer needs to perform NMS validation.

### Remove from Telemetry Service

1. **Delete files**:
   - `nms_client.go`
   - `handler_updated.go`
   - `README_NMS_INTEGRATION.md`

2. **Revert handler**:
   - Use original `handler.go` without NMS validation logic

3. **Remove environment variables**:
   ```bash
   # No longer needed in telemetry service
   # NMS_VALIDATION_ENABLED
   # SERVER2_BASE_URL
   # SERVER2_AUTH_ENDPOINT
   # SERVER2_DEVICE_ENDPOINT
   # SERVER2_USERNAME
   # SERVER2_PASSWORD
   ```

## Performance Considerations

### Why This Approach?

With 20,000+ devices:

- ❌ **Old approach**: Telemetry validates each device → 20k HTTP calls from telemetry
- ✅ **New approach**: NetBox validates once → Only valid devices reach telemetry

### Benefits

1. **Reduced load on telemetry service** - Only processes pre-validated devices
2. **Centralized validation** - All validation logic in one place (NetBox)
3. **Faster telemetry processing** - No HTTP calls, just config generation
4. **Better error handling** - Validation failures logged in NetBox where device was created

## Troubleshooting

### Webhook not sent to telemetry

**Check**:
1. Device has primary IP address
2. Device has SSH credentials in custom fields
3. Server2 is reachable from NetBox
4. Server2 credentials are correct
5. NetBox logs for validation errors

### Server2 authentication fails

**Check**:
1. `SERVER2_BASE_URL` is correct
2. `SERVER2_USERNAME` and `SERVER2_PASSWORD` are correct
3. Server2 `/api/auth/signin` endpoint is accessible

### Device validation fails

**Check**:
1. Device IP is reachable from Server2
2. SSH credentials are correct
3. SSH port (22) is open on device
4. Server2 logs for detailed error messages
