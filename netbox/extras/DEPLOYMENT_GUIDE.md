# Server2 NMS Integration - Deployment Guide

## Prerequisites

- NetBox running in Docker (as shown in your setup)
- Access to NetBox server via SSH
- Git repository with NetBox configuration
- Server2 NMS running at `http://10.4.160.240:8081`

## Deployment Steps

### Step 1: Upload Files to Server

Transfer the new files to your NetBox server:

```bash
# From your local machine, copy files to server
scp c:\Users\jacob.rajan\Downloads\netbox-main\netbox\extras\server2_client.py np-dev@<server-ip>:~/User/jacob/netbox-poc/netbox/extras/
scp c:\Users\jacob.rajan\Downloads\netbox-main\netbox\extras\webhooks.py np-dev@<server-ip>:~/User/jacob/netbox-poc/netbox/extras/
```

Or if using Git:

```bash
# On your local machine
cd c:\Users\jacob.rajan\Downloads\netbox-main
git add netbox/extras/server2_client.py
git add netbox/extras/webhooks.py
git commit -m "Add Server2 NMS validation to webhook handler"
git push

# On the server
cd ~/User/jacob/netbox-poc
git pull
```

### Step 2: Configure NetBox

Add Server2 configuration to NetBox. You have two options:

#### Option A: Environment Variables (Recommended for Docker)

Edit your `docker-compose.yml` or `.env` file:

```yaml
# In docker-compose.yml under netbox service environment:
services:
  netbox:
    environment:
      # ... existing environment variables ...
      
      # Server2 NMS Configuration
      SERVER2_VALIDATION_ENABLED: "true"
      SERVER2_BASE_URL: "http://10.4.160.240:8081"
      SERVER2_AUTH_ENDPOINT: "/api/auth/signin"
      SERVER2_DEVICE_ENDPOINT: "/device"
      SERVER2_USERNAME: "admin"
      SERVER2_PASSWORD: "admin"
```

Or in `.env` file:

```bash
# Server2 NMS Configuration
SERVER2_VALIDATION_ENABLED=true
SERVER2_BASE_URL=http://10.4.160.240:8081
SERVER2_AUTH_ENDPOINT=/api/auth/signin
SERVER2_DEVICE_ENDPOINT=/device
SERVER2_USERNAME=admin
SERVER2_PASSWORD=admin
```

#### Option B: NetBox Configuration File

Edit `configuration/configuration.py`:

```python
# Server2 NMS Configuration
SERVER2_VALIDATION_ENABLED = True
SERVER2_BASE_URL = 'http://10.4.160.240:8081'
SERVER2_AUTH_ENDPOINT = '/api/auth/signin'
SERVER2_DEVICE_ENDPOINT = '/device'
SERVER2_USERNAME = 'admin'
SERVER2_PASSWORD = 'admin'
```

### Step 3: Rebuild and Restart NetBox

```bash
# Navigate to NetBox directory
cd ~/User/jacob/netbox-poc

# Rebuild NetBox container (if files changed)
docker compose build netbox

# Restart NetBox services
docker compose restart netbox netbox-worker netbox-housekeeping

# Or restart all services
docker compose down
docker compose up -d
```

### Step 4: Verify Deployment

Check that NetBox started successfully:

```bash
# Check container status
docker compose ps

# Check NetBox logs
docker compose logs -f netbox

# Look for any errors related to server2_client import
# Should see normal startup logs without import errors
```

### Step 5: Test the Integration

#### Test 1: Check Server2 Connectivity

```bash
# From NetBox container, test Server2 connectivity
docker compose exec netbox bash

# Inside container
curl -X POST http://10.4.160.240:8081/api/auth/signin \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'

# Should return JWT token
exit
```

#### Test 2: Create Test Device

Create a device via NetBox UI or API:

```bash
# Using NetBox API
curl -X POST http://<your-netbox-ip>:8000/api/dcim/devices/ \
  -H "Authorization: Token <your-netbox-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-device-001",
    "device_type": 1,
    "role": 1,
    "site": 1,
    "custom_fields": {
      "username": "rootadmin",
      "password": "Root@123"
    }
  }'

# Then assign IP address
curl -X POST http://<your-netbox-ip>:8000/api/ipam/ip-addresses/ \
  -H "Authorization: Token <your-netbox-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "address": "10.4.160.240/32",
    "assigned_object_type": "dcim.device",
    "assigned_object_id": <device-id>
  }'
```

#### Test 3: Monitor Logs

Watch NetBox logs for validation messages:

```bash
# Watch NetBox logs
docker compose logs -f netbox | grep -i "server2\|validation"

# Expected successful validation:
# INFO netbox.webhooks.server2: Authenticating with Server2...
# INFO netbox.webhooks.server2: Server2 authentication successful
# INFO netbox.webhooks.server2: Validating device 10.4.160.240 with Server2
# INFO netbox.webhooks.server2: Device 10.4.160.240 validation successful

# Expected failed validation:
# WARNING netbox.webhooks: Server2 validation failed for device...
```

#### Test 4: Verify Telemetry Webhook

Check telemetry service logs to confirm webhook was sent (or not sent):

```bash
# Watch telemetry logs
docker compose logs -f telemetry-webhook

# If validation succeeded, should see:
# INFO: Received webhook payload

# If validation failed, should NOT see webhook
```

## Troubleshooting

### Issue: Import Error for server2_client

**Error**: `ModuleNotFoundError: No module named 'extras.server2_client'`

**Solution**:
```bash
# Ensure file is in correct location
docker compose exec netbox ls -la /opt/netbox/netbox/extras/server2_client.py

# If missing, copy it:
docker cp netbox/extras/server2_client.py netbox:/opt/netbox/netbox/extras/

# Restart NetBox
docker compose restart netbox
```

### Issue: Server2 Connection Timeout

**Error**: `Server2 request failed: Connection timeout`

**Solution**:
```bash
# Test connectivity from NetBox container
docker compose exec netbox bash
ping 10.4.160.240
curl http://10.4.160.240:8081/api/auth/signin

# Check if Server2 is running
# Check firewall rules
# Verify SERVER2_BASE_URL is correct
```

### Issue: Authentication Failed

**Error**: `Server2 authentication failed: 401`

**Solution**:
- Verify `SERVER2_USERNAME` and `SERVER2_PASSWORD` are correct
- Check Server2 logs for authentication errors
- Test credentials manually with curl

### Issue: Webhook Still Sent Despite Failed Validation

**Problem**: Telemetry receives webhook even when SSH validation fails

**Solution**:
```bash
# Check if validation is enabled
docker compose exec netbox python manage.py shell
>>> from django.conf import settings
>>> print(settings.SERVER2_VALIDATION_ENABLED)
True

# Check webhook code is updated
docker compose exec netbox grep -A 5 "Server2 Validation" /opt/netbox/netbox/extras/webhooks.py

# Should see the validation code block
```

### Issue: No Logs from server2_client

**Problem**: No validation logs appearing

**Solution**:
```bash
# Check log level
docker compose exec netbox python manage.py shell
>>> import logging
>>> logger = logging.getLogger('netbox.webhooks.server2')
>>> logger.setLevel(logging.DEBUG)

# Or set in configuration.py:
LOGGING = {
    'loggers': {
        'netbox.webhooks.server2': {
            'level': 'DEBUG',
        },
    },
}
```

## Rollback Procedure

If you need to rollback the changes:

### Step 1: Disable Validation

```bash
# Set environment variable
export SERVER2_VALIDATION_ENABLED=false

# Or in docker-compose.yml
SERVER2_VALIDATION_ENABLED: "false"

# Restart NetBox
docker compose restart netbox
```

### Step 2: Revert Code Changes (Optional)

```bash
cd ~/User/jacob/netbox-poc

# Revert to previous commit
git log --oneline  # Find commit hash before changes
git revert <commit-hash>

# Rebuild and restart
docker compose build netbox
docker compose restart netbox
```

## Monitoring

### Key Metrics to Monitor

1. **Validation Success Rate**:
   ```bash
   # Count successful validations
   docker compose logs netbox | grep "validation successful" | wc -l
   
   # Count failed validations
   docker compose logs netbox | grep "validation failed" | wc -l
   ```

2. **Server2 Response Time**:
   - Monitor Server2 logs for slow responses
   - Check NetBox webhook processing time

3. **Webhook Queue**:
   ```bash
   # Check RQ queue status
   docker compose exec netbox python manage.py rqstats
   ```

### Health Check

Create a simple health check script:

```bash
#!/bin/bash
# health_check.sh

echo "Checking NetBox..."
docker compose ps netbox | grep "Up" || echo "NetBox is down!"

echo "Checking Server2 connectivity..."
docker compose exec -T netbox curl -s http://10.4.160.240:8081/api/auth/signin || echo "Server2 unreachable!"

echo "Checking recent validations..."
docker compose logs --tail=50 netbox | grep -i "server2"
```

## Performance Tuning

### For High Volume (20k+ Devices)

1. **Increase Timeout Values**:
   ```python
   # In server2_client.py, adjust timeouts:
   response = self.session.post(auth_url, json=payload, timeout=30)  # Increase from 10
   response = self.session.post(device_url, json=payload, timeout=60)  # Increase from 30
   ```

2. **Connection Pooling**:
   - Already implemented via `requests.Session()`
   - Consider increasing pool size if needed

3. **Async Processing**:
   - Webhook already runs in RQ worker (async)
   - Monitor RQ worker count: `docker compose up -d --scale netbox-worker=4`

## Next Steps After Deployment

1. **Monitor for 24 hours**: Watch logs for any errors
2. **Test with production devices**: Create a few real devices
3. **Clean up telemetry service**: Remove NMS validation code from telemetry
4. **Update documentation**: Document any environment-specific changes

## Quick Reference Commands

```bash
# View NetBox logs
docker compose logs -f netbox

# View telemetry logs
docker compose logs -f telemetry-webhook

# Restart NetBox
docker compose restart netbox netbox-worker

# Check RQ queue
docker compose exec netbox python manage.py rqstats

# Access NetBox shell
docker compose exec netbox python manage.py shell

# Test Server2 from NetBox container
docker compose exec netbox curl http://10.4.160.240:8081/api/auth/signin
```
