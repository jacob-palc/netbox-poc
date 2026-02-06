#!/usr/bin/env python3
"""
Webhook Handler Service

Receives webhooks from NetBox and orchestrates the flow:
1. Device Created → Server2 (SSH validation) → If success → Server1 (Telemetry)
2. Device Updated → Server1 (Telemetry) directly

Environment Variables:
    # Server2 (SSH Validation)
    SERVER2_BASE_URL: Server2 URL (default: http://10.4.160.240:8081)
    SERVER2_AUTH_ENDPOINT: Auth endpoint (default: /api/auth/signin)
    SERVER2_DEVICE_ENDPOINT: Device endpoint (default: /device)
    SERVER2_USERNAME: Username for auth (default: admin)
    SERVER2_PASSWORD: Password for auth (default: admin)

    # Server1 (Telemetry)
    SERVER1_WEBHOOK_URL: Telemetry URL (default: http://172.27.1.70:5000/endpoint)

    # Encryption
    NETBOX_DEVICE_ENCRYPTION_KEY: Key to decrypt device passwords
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import logging
from datetime import datetime
from cryptography.fernet import Fernet

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Server2 Configuration (SSH Validation)
SERVER2_BASE_URL = os.environ.get('SERVER2_BASE_URL', 'http://10.4.160.240:5000')
SERVER2_AUTH_ENDPOINT = os.environ.get('SERVER2_AUTH_ENDPOINT', '/api/auth/signin')
SERVER2_DEVICE_ENDPOINT = os.environ.get('SERVER2_DEVICE_ENDPOINT', '/device')
SERVER2_USERNAME = os.environ.get('SERVER2_USERNAME', 'admin')
SERVER2_PASSWORD = os.environ.get('SERVER2_PASSWORD', 'admin')

# Server1 Configuration (Telemetry)
SERVER1_WEBHOOK_URL = os.environ.get('SERVER1_WEBHOOK_URL', 'http://172.27.1.70:5000/endpoint')

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

        Returns: dict with success status and details
        """
        try:
            # Authenticate first
            if not self.token:
                if not self.authenticate():
                    return {
                        'success': False,
                        'status_code': 401,
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
                logger.info(f"Server2 validation success: {data.get('message')}")
                return {
                    'success': True,
                    'status_code': 200,
                    'message': data.get('message', 'Device validated successfully'),
                    'data': data
                }
            else:
                logger.warning(f"Server2 validation failed: {response.status_code} - {response.text}")
                return {
                    'success': False,
                    'status_code': response.status_code,
                    'message': response.text
                }
        except Exception as e:
            logger.error(f"Server2 validation error: {e}")
            return {
                'success': False,
                'status_code': 500,
                'message': str(e)
            }


def send_to_telemetry(webhook_payload):
    """Forward webhook payload to Server1 (Telemetry)"""
    try:
        logger.info(f"Sending webhook to Server1 (Telemetry): {SERVER1_WEBHOOK_URL}")

        response = requests.post(
            SERVER1_WEBHOOK_URL,
            json=webhook_payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )

        if response.status_code in [200, 201, 202]:
            logger.info(f"Telemetry webhook sent successfully: {response.status_code}")
            return True, response.status_code, response.text
        else:
            logger.warning(f"Telemetry webhook failed: {response.status_code} - {response.text}")
            return False, response.status_code, response.text
    except Exception as e:
        logger.error(f"Telemetry webhook error: {e}")
        return False, 500, str(e)


def extract_device_info(webhook_data):
    """Extract device information from webhook payload"""
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
        # Check if name looks like an IP
        if name and (name.count('.') == 3 or ':' in name):
            ip_address = name

    # Get custom fields (username/password)
    custom_fields = data.get('custom_fields', {})
    username = custom_fields.get('username')
    password = custom_fields.get('password')

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

    return {
        'id': data.get('id'),
        'name': data.get('name'),
        'ip_address': ip_address,
        'username': username,
        'password': password,
        'status': data.get('status', {}).get('value') if isinstance(data.get('status'), dict) else data.get('status')
    }


@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """
    Main webhook endpoint that receives NetBox webhooks

    Flow:
    - Device Created: Server2 (SSH) -> If success -> Server1 (Telemetry)
    - Device Updated: Server1 (Telemetry) directly
    """
    try:
        webhook_data = request.get_json()

        event = webhook_data.get('event')
        model = webhook_data.get('model')
        timestamp = webhook_data.get('timestamp')

        logger.info(f"Received webhook: event={event}, model={model}, timestamp={timestamp}")

        # Only process device events
        if model != 'dcim.device':
            logger.info(f"Ignoring non-device webhook: {model}")
            return jsonify({
                'status': 'ignored',
                'reason': f'Model {model} not handled'
            }), 200

        # Extract device info
        device_info = extract_device_info(webhook_data)
        logger.info(f"Device info: id={device_info['id']}, name={device_info['name']}, ip={device_info['ip_address']}")

        result = {
            'event': event,
            'device_id': device_info['id'],
            'device_name': device_info['name'],
            'ip_address': device_info['ip_address'],
            'timestamp': timestamp
        }

        # ==================== DEVICE CREATED ====================
        if event == 'created':
            logger.info("Processing CREATED event - validating SSH first")

            # Check if we have IP and credentials
            if not device_info['ip_address']:
                logger.warning("No IP address for SSH validation")
                result['server2_status'] = 'skipped'
                result['server2_reason'] = 'No IP address'
            elif not device_info['username'] or not device_info['password']:
                logger.warning("No credentials for SSH validation")
                result['server2_status'] = 'skipped'
                result['server2_reason'] = 'No credentials'
            else:
                # Call Server2 for SSH validation
                server2_client = Server2Client()
                server2_result = server2_client.validate_device(
                    ip_address=device_info['ip_address'],
                    username=device_info['username'],
                    password=device_info['password']
                )

                result['server2_status'] = 'success' if server2_result['success'] else 'failed'
                result['server2_message'] = server2_result['message']
                result['server2_status_code'] = server2_result['status_code']

                # Only proceed to telemetry if SSH validation succeeded
                if not server2_result['success']:
                    logger.warning(f"Server2 SSH validation failed - NOT sending to telemetry")
                    result['server1_status'] = 'skipped'
                    result['server1_reason'] = 'Server2 SSH validation failed'
                    return jsonify(result), 200

            # Send to Server1 (Telemetry) - only if Server2 succeeded or was skipped
            logger.info("Sending CREATED event to Server1 (Telemetry)")
            success, status_code, response = send_to_telemetry(webhook_data)
            result['server1_status'] = 'success' if success else 'failed'
            result['server1_status_code'] = status_code
            if not success:
                result['server1_error'] = response

            return jsonify(result), 200

        # ==================== DEVICE UPDATED ====================
        elif event == 'updated':
            logger.info("Processing UPDATED event - sending directly to telemetry")

            # Send directly to Server1 (Telemetry)
            success, status_code, response = send_to_telemetry(webhook_data)
            result['server1_status'] = 'success' if success else 'failed'
            result['server1_status_code'] = status_code
            if not success:
                result['server1_error'] = response

            return jsonify(result), 200

        # ==================== DEVICE DELETED ====================
        elif event == 'deleted':
            logger.info("Processing DELETED event - sending to telemetry")

            # Send to Server1 (Telemetry)
            success, status_code, response = send_to_telemetry(webhook_data)
            result['server1_status'] = 'success' if success else 'failed'
            result['server1_status_code'] = status_code
            if not success:
                result['server1_error'] = response

            return jsonify(result), 200

        else:
            logger.info(f"Unknown event type: {event}")
            return jsonify({
                'status': 'ignored',
                'event': event,
                'reason': 'Unknown event type'
            }), 200

    except Exception as e:
        logger.error(f"Webhook handler error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'webhook-handler',
        'server2_url': SERVER2_BASE_URL,
        'server1_url': SERVER1_WEBHOOK_URL
    })


@app.route('/', methods=['GET'])
def index():
    """API documentation"""
    return jsonify({
        'service': 'NetBox Webhook Handler',
        'version': '1.0',
        'description': 'Orchestrates webhook flow between NetBox, Server2 (SSH), and Server1 (Telemetry)',
        'flow': {
            'created': 'NetBox -> Server2 (SSH validation) -> If success -> Server1 (Telemetry)',
            'updated': 'NetBox -> Server1 (Telemetry) directly',
            'deleted': 'NetBox -> Server1 (Telemetry) directly'
        },
        'endpoints': {
            'POST /webhook': 'Receive NetBox webhooks',
            'GET /health': 'Health check'
        },
        'config': {
            'server2_url': SERVER2_BASE_URL,
            'server1_url': SERVER1_WEBHOOK_URL
        }
    })


if __name__ == '__main__':
    logger.info(f"""
================================================================================
NetBox Webhook Handler Service
================================================================================
Server2 (SSH Validation):
  URL: {SERVER2_BASE_URL}
  Auth Endpoint: {SERVER2_AUTH_ENDPOINT}
  Device Endpoint: {SERVER2_DEVICE_ENDPOINT}
  Username: {SERVER2_USERNAME}

Server1 (Telemetry):
  URL: {SERVER1_WEBHOOK_URL}

Flow:
  CREATED: NetBox -> Server2 (SSH) -> If success -> Server1 (Telemetry)
  UPDATED: NetBox -> Server1 (Telemetry) directly
  DELETED: NetBox -> Server1 (Telemetry) directly
================================================================================
""")
    app.run(host='0.0.0.0', port=5002, debug=True)
