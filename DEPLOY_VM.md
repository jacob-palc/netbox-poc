# NetBox Device Onboarding - VM Server Deployment Guide

This guide covers deploying the NetBox device onboarding system on a VM server.

## Prerequisites

- VM Server with Ubuntu 20.04/22.04 or CentOS 8+ (minimum 4GB RAM, 2 CPU cores)
- SSH access to the server
- Root or sudo privileges
- Network access to your telemetry service at `172.27.1.67:5000`

## Step 1: Install Docker on the VM Server

### Ubuntu/Debian:

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y apt-transport-https ca-certificates curl software-properties-common

# Add Docker GPG key
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Add Docker repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Start and enable Docker
sudo systemctl start docker
sudo systemctl enable docker

# Add your user to docker group (logout/login required)
sudo usermod -aG docker $USER
```

### CentOS/RHEL:

```bash
# Install dependencies
sudo yum install -y yum-utils

# Add Docker repository
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# Install Docker
sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Start and enable Docker
sudo systemctl start docker
sudo systemctl enable docker

# Add your user to docker group
sudo usermod -aG docker $USER
```

## Step 2: Copy Files to Server

### From your Windows machine:

```powershell
# Using SCP (from PowerShell)
scp -r "C:\Users\jacob.rajan\Downloads\netbox-main" user@YOUR_VM_IP:/home/user/

# Or using rsync if available
rsync -avz "C:\Users\jacob.rajan\Downloads\netbox-main" user@YOUR_VM_IP:/home/user/
```

### Or clone from Git (if you've pushed to a repo):

```bash
# On the VM server
git clone https://your-repo-url/netbox-main.git
cd netbox-main
```

## Step 3: Configure Server IP

On the VM server, update the configuration to use the server's IP:

```bash
cd /home/user/netbox-main

# Get the server's IP address
SERVER_IP=$(hostname -I | awk '{print $1}')
echo "Server IP: $SERVER_IP"

# Update docker-compose.yml ALLOWED_HOSTS (optional - * allows all)
# If you want to restrict, edit the file:
# nano docker-compose.yml
# Change ALLOWED_HOSTS: "*" to ALLOWED_HOSTS: "your-server-ip,localhost"
```

## Step 4: Start NetBox Services

```bash
cd /home/user/netbox-main

# Pull images and start services
docker compose up -d

# Check status
docker compose ps

# View logs (wait for NetBox to be ready - takes 2-3 minutes first time)
docker compose logs -f netbox
```

Wait until you see:
```
netbox  | [INFO] Listening at: http://0.0.0.0:8080
```

Press `Ctrl+C` to exit logs.

## Step 5: Install Python Dependencies on Server

```bash
# Install Python and pip if not present
sudo apt install -y python3 python3-pip   # Ubuntu
# OR
sudo yum install -y python3 python3-pip   # CentOS

# Install required packages
pip3 install requests cryptography
```

## Step 6: Run Setup Script

```bash
cd /home/user/netbox-main

# Run the setup script to configure NetBox
python3 setup_netbox.py

# If NetBox is on a different port or host:
# python3 setup_netbox.py --netbox-url http://localhost:8000 --telemetry-url http://172.27.1.67:5000/endpoint
```

Expected output:
```
======================================================================
NetBox Device Onboarding Setup
======================================================================
Waiting for NetBox at http://localhost:8000...
NetBox is ready!

--- Creating Custom Fields ---
  Created custom field: onboarding_username
  Created custom field: onboarding_password
  ...

--- Creating Manufacturers ---
  Created manufacturer: CTC Union
  ...

--- Creating Webhook ---
  Created webhook: Device Onboarding Webhook

Setup Complete!
======================================================================
```

## Step 7: Verify Services

```bash
# Check all containers are running
docker compose ps

# Expected output:
# NAME              STATUS          PORTS
# netbox            Up (healthy)    0.0.0.0:8000->8080/tcp
# netbox-postgres   Up (healthy)    5432/tcp
# netbox-redis      Up (healthy)    6379/tcp
# netbox-worker     Up
# telemetry-mock    Up              0.0.0.0:5000->5000/tcp
```

## Step 8: Access NetBox

Open in browser: `http://YOUR_VM_IP:8000`

- **Username:** `admin`
- **Password:** `admin123`

## Step 9: Test Device Onboarding

### Option A: Via NetBox UI

1. Go to `http://YOUR_VM_IP:8000`
2. Login with `admin / admin123`
3. Navigate to **Customization → Scripts**
4. Click **"Device Onboarding with Reachability Check"**
5. Fill in the form:
   - Device IP: `192.168.1.100` (or a real device IP)
   - Username: `admin`
   - Password: `secret123`
   - Device Type: Select one
   - Device Role: Select one
   - Skip Ping Check: ☐ (uncheck to test ping)
6. Click **Run Script**

### Option B: Via Test Script

```bash
cd /home/user/netbox-main

# Run automated test
python3 test_onboarding.py

# With custom parameters:
python3 test_onboarding.py --netbox-url http://localhost:8000 --telemetry-url http://172.27.1.67:5000
```

### Option C: Via REST API

```bash
# Get the server IP
SERVER_IP=$(hostname -I | awk '{print $1}')

# Create a device via API
curl -X POST "http://localhost:8000/api/dcim/devices/" \
  -H "Authorization: Token 0123456789abcdef0123456789abcdef01234567" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "TEST-CPE-001",
    "device_type": 1,
    "role": 1,
    "site": 1,
    "status": "active",
    "custom_fields": {
      "onboarding_username": "admin",
      "onboarding_password": "encrypted-password",
      "reachable_state": true,
      "onboarding_status": "success",
      "device_source": "manual"
    }
  }'
```

## Step 10: Verify Webhook Delivery

### Check NetBox webhook logs:

1. Go to **Operations → Webhooks**
2. Click **"Device Onboarding Webhook"**
3. Scroll to **"Recent Deliveries"**
4. Verify HTTP 200 response

### Check telemetry service received the webhook:

```bash
# If using the mock telemetry service
curl http://localhost:5000/api/v1/webhooks

# Check your actual telemetry service logs at 172.27.1.67:5000
```

## Firewall Configuration

If you need to access NetBox from outside the VM:

```bash
# Ubuntu (UFW)
sudo ufw allow 8000/tcp   # NetBox
sudo ufw allow 5000/tcp   # Telemetry mock (if needed)

# CentOS (firewalld)
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --permanent --add-port=5000/tcp
sudo firewall-cmd --reload
```

## Useful Commands

```bash
# View all logs
docker compose logs -f

# View specific service logs
docker compose logs -f netbox
docker compose logs -f netbox-worker

# Restart services
docker compose restart

# Stop all services
docker compose down

# Stop and remove all data (clean start)
docker compose down -v

# Check NetBox worker (processes webhooks)
docker compose logs netbox-worker

# Execute command in NetBox container
docker compose exec netbox /bin/bash

# Access NetBox shell
docker compose exec netbox python /opt/netbox/netbox/manage.py nbshell
```

## Troubleshooting

### NetBox not starting

```bash
# Check logs
docker compose logs netbox

# Check if ports are in use
sudo netstat -tlnp | grep 8000

# Restart with fresh state
docker compose down -v
docker compose up -d
```

### Webhook not firing

```bash
# Check worker is running
docker compose ps netbox-worker

# Check worker logs
docker compose logs -f netbox-worker

# Verify event rule is enabled
curl -s http://localhost:8000/api/extras/event-rules/ \
  -H "Authorization: Token 0123456789abcdef0123456789abcdef01234567" | python3 -m json.tool
```

### Cannot reach telemetry service

```bash
# Test connectivity from NetBox container
docker compose exec netbox curl -v http://172.27.1.67:5000/endpoint

# Check if telemetry is reachable from VM
curl -v http://172.27.1.67:5000/endpoint
```

### Ping not working in container

The NetBox container may not have ping installed. The script handles this gracefully and marks the device as `reachable_state: null` if ping fails.

## Production Considerations

1. **Change default passwords:**
   ```bash
   # Edit docker-compose.yml
   SUPERUSER_PASSWORD: "your-secure-password"
   DB_PASSWORD: "your-db-password"
   ```

2. **Generate new encryption key:**
   ```bash
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   # Update NETBOX_DEVICE_ENCRYPTION_KEY in docker-compose.yml
   ```

3. **Use HTTPS:**
   - Put a reverse proxy (nginx/traefik) in front of NetBox
   - Enable SSL verification in webhook

4. **Backup data:**
   ```bash
   # Backup PostgreSQL
   docker compose exec postgres pg_dump -U netbox netbox > backup.sql
   ```

## Architecture on VM

```
┌─────────────────────────────────────────────────────────────────┐
│                        VM Server                                 │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  PostgreSQL │  │    Redis    │  │   NetBox    │◄── Port 8000│
│  │   (5432)    │  │   (6379)    │  │   Worker    │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│         │                │                │                     │
│         └────────────────┴────────────────┘                     │
│                          │                                      │
│                    ┌─────┴─────┐                                │
│                    │  NetBox   │◄─────── Port 8000              │
│                    │   App     │                                │
│                    └───────────┘                                │
│                          │                                      │
│                          │ Webhook POST                         │
└──────────────────────────┼──────────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │   Telemetry Service    │
              │  172.27.1.67:5000      │
              │  /endpoint             │
              └────────────────────────┘
```
