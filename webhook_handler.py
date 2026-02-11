#!/usr/bin/env python3
"""
Webhook Handler Service

Receives webhooks from NetBox and orchestrates the flow:
  1. Has IP + credentials → Server2 (SSH validation) → Update NetBox fields → Telemetry
  2. Has IP, no credentials → Telemetry directly
  3. No IP → Skip (device data incomplete)

After Server2 validation, updates NetBox custom fields:
  - reachable: true/false (was device reachable?)
  - authentication: true/false (did SSH credentials work?)

Environment Variables:
    SERVER2_BASE_URL, SERVER2_AUTH_ENDPOINT, SERVER2_DEVICE_ENDPOINT
    SERVER2_USERNAME, SERVER2_PASSWORD
    SERVER1_WEBHOOK_URL
    NETBOX_URL, NETBOX_TOKEN
    NETBOX_DEVICE_ENCRYPTION_KEY
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from cryptography.fernet import Fernet

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Thread pool for concurrent Server2 validations (bulk webhook processing)
# 15 workers = up to 15 parallel SSH validations via Server2
MAX_WORKERS = int(os.environ.get('WEBHOOK_MAX_WORKERS', '15'))
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Deduplication: prevent infinite webhook loops
# When we update NetBox (reachable/authentication), it fires another "updated" webhook.
# We skip processing if the same device was already handled within DEDUP_WINDOW seconds.
DEDUP_WINDOW = int(os.environ.get('WEBHOOK_DEDUP_WINDOW', '10'))
_recently_processed = {}  # device_id -> timestamp

# Server2 Configuration (SSH Validation)
SERVER2_BASE_URL = os.environ.get('SERVER2_BASE_URL', 'http://10.4.160.240:8081')
SERVER2_AUTH_ENDPOINT = os.environ.get('SERVER2_AUTH_ENDPOINT', '/api/auth/signin')
SERVER2_DEVICE_ENDPOINT = os.environ.get('SERVER2_DEVICE_ENDPOINT', '/device')
SERVER2_USERNAME = os.environ.get('SERVER2_USERNAME', 'admin')
SERVER2_PASSWORD = os.environ.get('SERVER2_PASSWORD', 'admin')

# Server1 Configuration (Telemetry)
SERVER1_WEBHOOK_URL = os.environ.get('SERVER1_WEBHOOK_URL', 'http://172.27.1.70:5000/endpoint')

# NetBox Configuration (to update custom fields after validation)
NETBOX_URL = os.environ.get('NETBOX_URL', 'http://netbox:8080')
NETBOX_TOKEN = os.environ.get('NETBOX_TOKEN', '0123456789abcdef0123456789abcdef01234567')

# Encryption key for device passwords
ENCRYPTION_KEY = os.environ.get('NETBOX_DEVICE_ENCRYPTION_KEY', 'XPmjtY0wwxQbD0ezEMDhGlAo2_JGXb6yB4yp5I-MnGA=')


def decrypt_password(encrypted_password):
    """Decrypt password using Fernet"""
    try:
        if not encrypted_password or encrypted_password == 'None':
            return None
        key = ENCRYPTION_KEY
        if isinstance(key, str):
            key = key.encode()
        cipher = Fernet(key)
        return cipher.decrypt(encrypted_password.encode()).decode()
    except Exception as e:
        logger.error(f"Failed to decrypt password: {e}")
        return None


def update_netbox_device(device_id, custom_fields):
    """Update device custom fields in NetBox"""
    try:
        url = f"{NETBOX_URL}/api/dcim/devices/{device_id}/"
        headers = {
            'Authorization': f'Token {NETBOX_TOKEN}',
            'Content-Type': 'application/json'
        }
        payload = {'custom_fields': custom_fields}

        logger.info(f"Updating NetBox device {device_id}: {custom_fields}")
        response = requests.patch(url, json=payload, headers=headers, timeout=10)

        if response.status_code == 200:
            logger.info(f"NetBox device {device_id} updated successfully")
            return True
        else:
            logger.warning(f"NetBox update failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"NetBox update error: {e}")
        return False


class Server2Client:
    """Client for Server2 SSH validation"""

    def __init__(self):
        self.base_url = SERVER2_BASE_URL
        self.token = None

    def authenticate(self):
        """Authenticate with Server2 and get token"""
        try:
            url = f"{self.base_url}{SERVER2_AUTH_ENDPOINT}"
            payload = {
                'username': SERVER2_USERNAME,
                'password': SERVER2_PASSWORD
            }

            logger.info(f"Authenticating with Server2: {url}")
            response = requests.post(url, json=payload, timeout=30)

            if response.status_code == 200:
                data = response.json()
                self.token = data.get('token') or data.get('access_token') or data.get('accessToken')
                logger.info("Server2 authentication successful")
                return True
            else:
                logger.error(f"Server2 auth failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Server2 auth error: {e}")
            return False

    def validate_device(self, ip_address, username, password, license_key=""):
        """
        Validate device SSH connectivity via Server2

        Returns dict with:
          - success: bool (HTTP 200 from Server2)
          - reachable: bool (device was reachable, not timed out)
          - authenticated: bool (SSH credentials worked)
          - message: str
        """
        try:
            if not self.token:
                if not self.authenticate():
                    return {
                        'success': False,
                        'reachable': None,
                        'authenticated': None,
                        'message': 'Failed to authenticate with Server2'
                    }

            url = f"{self.base_url}{SERVER2_DEVICE_ENDPOINT}"
            headers = {
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'application/json'
            }
            payload = {
                'ipAddress': ip_address,
                'username': username,
                'password': password,
                'licenseKey': license_key
            }

            logger.info(f"Validating device SSH via Server2: {ip_address}")
            response = requests.post(url, json=payload, headers=headers, timeout=60)

            if response.status_code == 200:
                data = response.json()
                message = data.get('message', '')
                logger.info(f"Server2 response for {ip_address}: {message}")

                # Parse Server2 response to determine reachable/authenticated
                msg_lower = message.lower()

                if 'unreachable' in msg_lower or 'time out' in msg_lower or 'timeout' in msg_lower:
                    # Device not reachable (SSH connection timed out)
                    return {
                        'success': True,
                        'reachable': False,
                        'authenticated': None,
                        'message': message
                    }
                elif 'auth' in msg_lower and 'fail' in msg_lower:
                    # Device reachable but SSH auth failed (bad credentials)
                    return {
                        'success': True,
                        'reachable': True,
                        'authenticated': False,
                        'message': message
                    }
                else:
                    # Device reachable and SSH succeeded
                    return {
                        'success': True,
                        'reachable': True,
                        'authenticated': True,
                        'message': message
                    }
            else:
                logger.warning(f"Server2 validation failed: {response.status_code} - {response.text}")
                return {
                    'success': False,
                    'reachable': None,
                    'authenticated': None,
                    'message': response.text
                }
        except Exception as e:
            logger.error(f"Server2 validation error: {e}")
            return {
                'success': False,
                'reachable': None,
                'authenticated': None,
                'message': str(e)
            }


def extract_device_info(webhook_data):
    """Extract all device information from webhook payload"""
    data = webhook_data.get('data', {})

    # Get IP address
    ip_address = None
    primary_ip = data.get('primary_ip4') or data.get('primary_ip')
    if primary_ip and primary_ip != 'None':
        if isinstance(primary_ip, dict):
            address = primary_ip.get('address', '')
            ip_address = address.split('/')[0] if '/' in address else address
        else:
            ip_address = str(primary_ip).split('/')[0]

    # If no primary IP, try to use device name (which might be IP)
    if not ip_address:
        name = data.get('name', '')
        if name and (name.count('.') == 3 or ':' in name):
            ip_address = name

    # Get custom fields
    custom_fields = data.get('custom_fields', {}) or {}
    username = custom_fields.get('username')
    password = custom_fields.get('password')
    reachable = custom_fields.get('reachable')
    authentication = custom_fields.get('authentication')
    management = custom_fields.get('management')

    # Clean up None strings
    if username == 'None' or not username:
        username = None
    if password == 'None' or not password:
        password = None

    # Try to decrypt password
    if password:
        decrypted = decrypt_password(password)
        if decrypted:
            password = decrypted

    # Get device type / manufacturer / role / site
    device_type = data.get('device_type', {}) or {}
    manufacturer = device_type.get('manufacturer', {}) or {}
    role = data.get('role', {}) or {}
    site = data.get('site', {}) or {}
    status = data.get('status', {})

    return {
        'id': data.get('id'),
        'name': data.get('name', ''),
        'ip_address': ip_address,
        'username': username,
        'password': password,
        'reachable': reachable,
        'authentication': authentication,
        'management': management,
        'status': status.get('value') if isinstance(status, dict) else status,
        'model': device_type.get('model', ''),
        'manufacturer': manufacturer.get('name', ''),
        'role': role.get('name', ''),
        'site': site.get('name', ''),
    }


def build_telemetry_payload(device_info, event, timestamp):
    """Build payload for the telemetry service (Go struct expects nested objects)"""
    return {
        'event': event,
        'timestamp': timestamp,
        'device_id': device_info['id'],
        'device_name': device_info['name'],
        'device_ip': device_info['ip_address'],
        'username': device_info['username'] or '',
        'password': device_info['password'] or '',
        'reachable': device_info['reachable'],
        'authentication': device_info['authentication'],
        'management': device_info['management'],
        'status': {'value': device_info['status'] or ''},
        'model': device_info['model'],
        'manufacturer': {'name': device_info['manufacturer']},
        'device_type': {'model': device_info['model'], 'manufacturer': {'name': device_info['manufacturer']}},
        'role': {'name': device_info['role'].lower() if device_info['role'] else ''},
        'site': {'name': device_info['site']},
    }


def send_to_telemetry(telemetry_payload):
    """Send clean payload to Server1 (Telemetry)"""
    try:
        logger.info(f"Sending to telemetry: {SERVER1_WEBHOOK_URL}")
        logger.info(f"Telemetry payload: {telemetry_payload}")

        response = requests.post(
            SERVER1_WEBHOOK_URL,
            json=telemetry_payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )

        if response.status_code in [200, 201, 202]:
            logger.info(f"Telemetry sent successfully: {response.status_code}")
            return True, response.status_code, response.text
        else:
            logger.warning(f"Telemetry failed: {response.status_code} - {response.text}")
            return False, response.status_code, response.text
    except Exception as e:
        logger.error(f"Telemetry error: {e}")
        return False, 500, str(e)


def process_device_validation(device_info, event, timestamp):
    """
    Background task: Server2 validation → Update NetBox → Send to Telemetry

    Runs in thread pool so the webhook endpoint can return immediately.
    With 30 workers, up to 30 devices are validated concurrently (~5s each).
    """
    device_id = device_info['id']
    ip_address = device_info['ip_address']

    try:
        # === Step 1: Server2 SSH validation (if credentials available) ===
        if device_info['username'] and device_info['password']:
            logger.info(f"[BG] Validating SSH via Server2 for {ip_address}")

            server2_client = Server2Client()
            server2_result = server2_client.validate_device(
                ip_address=ip_address,
                username=device_info['username'],
                password=device_info['password']
            )

            logger.info(f"[BG] Server2 result for {ip_address}: "
                         f"reachable={server2_result['reachable']}, "
                         f"authenticated={server2_result['authenticated']}, "
                         f"message={server2_result['message']}")

            # Update NetBox custom fields based on Server2 result
            netbox_update = {}
            if server2_result['reachable'] is not None:
                netbox_update['reachable'] = server2_result['reachable']
                device_info['reachable'] = server2_result['reachable']
            if server2_result['authenticated'] is not None:
                netbox_update['authentication'] = server2_result['authenticated']
                device_info['authentication'] = server2_result['authenticated']

            if netbox_update and device_id:
                update_netbox_device(device_id, netbox_update)

            # If Server2 API itself failed, don't send to telemetry
            if not server2_result['success']:
                logger.warning(f"[BG] Server2 API error for {ip_address} - NOT sending to telemetry")
                return
        else:
            logger.info(f"[BG] No credentials for {ip_address} - skipping Server2 validation")

        # === Step 2: Send to Telemetry (always, so frontend has latest state) ===
        telemetry_payload = build_telemetry_payload(device_info, event, timestamp)
        logger.info(f"[BG] Sending {event} event to telemetry for {ip_address}")
        success, status_code, response = send_to_telemetry(telemetry_payload)

        if success:
            logger.info(f"[BG] Telemetry sent for {ip_address}: {status_code}")
        else:
            logger.warning(f"[BG] Telemetry failed for {ip_address}: {status_code} - {response}")

    except Exception as e:
        logger.error(f"[BG] Processing error for device {device_id} ({ip_address}): {e}")
        import traceback
        traceback.print_exc()


@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """
    Main webhook endpoint - accepts webhook and returns immediately.

    Heavy processing (Server2 SSH validation ~5s per device) runs in background
    thread pool. This allows the NetBox RQ worker to quickly dispatch all webhooks
    during bulk operations (1000+ devices), with up to MAX_WORKERS concurrent
    Server2 validations happening in parallel.
    """
    try:
        webhook_data = request.get_json()

        event = webhook_data.get('event')
        timestamp = webhook_data.get('timestamp')

        logger.info(f"Received webhook: event={event}, timestamp={timestamp}")

        # Extract device info (lightweight - just parsing JSON)
        device_info = extract_device_info(webhook_data)
        logger.info(f"Device: id={device_info['id']}, name={device_info['name']}, "
                     f"ip={device_info['ip_address']}, model={device_info['model']}")

        # No IP = device data is incomplete, skip immediately
        if not device_info['ip_address']:
            logger.info(f"No IP address yet for device {device_info['name']} - skipping")
            return jsonify({
                'status': 'skipped',
                'reason': 'No IP address - device data incomplete',
                'device_id': device_info['id'],
                'device_name': device_info['name']
            }), 200

        # Dedup: skip if we already processed this device recently
        # (our own NetBox update of reachable/authentication triggers another webhook)
        device_id = device_info['id']
        now = time.time()
        last_processed = _recently_processed.get(device_id, 0)
        if now - last_processed < DEDUP_WINDOW:
            logger.info(f"Skipping device {device_id} - already processed {now - last_processed:.1f}s ago (dedup)")
            return jsonify({
                'status': 'skipped',
                'reason': 'recently processed (dedup)',
                'device_id': device_id
            }), 200

        # Mark as processing now (before queuing to thread pool)
        _recently_processed[device_id] = now

        # Submit to thread pool for background processing
        executor.submit(process_device_validation, device_info, event, timestamp)

        logger.info(f"Queued device {device_info['name']} ({device_info['ip_address']}) for background processing")

        return jsonify({
            'status': 'accepted',
            'device_id': device_info['id'],
            'device_name': device_info['name'],
            'ip_address': device_info['ip_address'],
            'event': event,
            'message': 'Queued for Server2 validation and telemetry'
        }), 202

    except Exception as e:
        logger.error(f"Webhook handler error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'webhook-handler',
        'server2_url': SERVER2_BASE_URL,
        'server1_url': SERVER1_WEBHOOK_URL,
        'netbox_url': NETBOX_URL
    })


@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'service': 'NetBox Webhook Handler',
        'version': '3.1',
        'mode': f'Async (ThreadPool: {MAX_WORKERS} workers)',
        'flow': {
            '1_no_ip': 'Skip (device data incomplete)',
            '2_has_creds': 'Server2 (SSH) → Update NetBox reachable/authentication → Telemetry',
            '3_no_creds': 'Telemetry directly'
        },
        'states': {
            'reachable=true, auth=true': 'Online, SSH valid',
            'reachable=true, auth=false': 'Online, bad credentials (user can retry)',
            'reachable=false': 'Device offline/unreachable',
            'null': 'Pending validation'
        }
    })


if __name__ == '__main__':
    logger.info(f"""
================================================================================
NetBox Webhook Handler Service v3.1 (Async)
================================================================================
Server2 (SSH Validation): {SERVER2_BASE_URL}
Server1 (Telemetry):      {SERVER1_WEBHOOK_URL}
NetBox:                    {NETBOX_URL}
Thread Pool Workers:       {MAX_WORKERS}

Flow (same for all events - processed in background):
  Has IP + creds → Server2 → Update reachable/authentication in NetBox → Telemetry
  Has IP, no creds → Telemetry directly
  No IP → Skip (returned immediately)

Bulk Mode:
  Webhook returns 202 Accepted immediately
  Up to {MAX_WORKERS} devices validated concurrently via Server2
  1000 devices @ 5s each = ~{1000 // MAX_WORKERS * 5 // 60} min (vs ~83 min sequential)

Device States:
  reachable=true,  authentication=true  → Online, SSH valid
  reachable=true,  authentication=false → Online, bad creds (user can update & retry)
  reachable=false, authentication=null  → Offline/unreachable
  null, null                            → Pending validation
================================================================================
""")
    app.run(host='0.0.0.0', port=5002, debug=True)
