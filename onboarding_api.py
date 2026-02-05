#!/usr/bin/env python3
"""
Device Onboarding API Service

A simple Flask API that wraps NetBox API calls to allow single-call device onboarding.
Your NMS can call this endpoint with device details and IP address in one request.

Usage:
    python onboarding_api.py

Endpoint:
    POST /api/onboard
    {
        "name": "CPE-001",
        "ip": "192.168.1.100",
        "device_type": 1,
        "role": 1,
        "site": 1,
        "username": "admin",
        "password": "secret123"
    }
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import platform
import re
import os
from datetime import datetime
from cryptography.fernet import Fernet

app = Flask(__name__)
CORS(app)

# Configuration
NETBOX_URL = os.environ.get('NETBOX_URL', 'http://localhost:8000')
NETBOX_TOKEN = os.environ.get('NETBOX_TOKEN', '0123456789abcdef0123456789abcdef01234567')
ENCRYPTION_KEY = os.environ.get('NETBOX_DEVICE_ENCRYPTION_KEY', 'XPmjtY0wwxQbD0ezEMDhGlAo2_JGXb6yB4yp5I-MnGA=')

HEADERS = {
    'Authorization': f'Token {NETBOX_TOKEN}',
    'Content-Type': 'application/json'
}

# Create a session with connection pooling for faster requests
session = requests.Session()
session.headers.update(HEADERS)
adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10)
session.mount('http://', adapter)
session.mount('https://', adapter)


def encrypt_password(password):
    """Encrypt password using Fernet"""
    try:
        key = ENCRYPTION_KEY
        if isinstance(key, str):
            key = key.encode()
        cipher = Fernet(key)
        return cipher.encrypt(password.encode()).decode()
    except Exception as e:
        return password  # Return plain if encryption fails


def ping_device(ip_address, count=3, timeout=2):
    """Ping device to check reachability"""
    try:
        system = platform.system().lower()

        if system == 'windows':
            cmd = ['ping', '-n', str(count), '-w', str(timeout * 1000), ip_address]
        else:
            cmd = ['ping', '-c', str(count), '-W', str(timeout), ip_address]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=count * timeout + 5)
        is_reachable = result.returncode == 0

        # Parse latency
        output = result.stdout
        latency_ms = None

        if system == 'windows' and 'Average' in output:
            match = re.search(r'Average\s*=\s*(\d+)ms', output)
            if match:
                latency_ms = float(match.group(1))
        else:
            match = re.search(r'min/avg/max.*?=\s*[\d.]+/([\d.]+)/', output)
            if match:
                latency_ms = float(match.group(1))

        return is_reachable, latency_ms
    except Exception:
        return False, None


def generate_device_name(ip_address, role_slug='cpe'):
    """Generate device name from IP"""
    ip_parts = ip_address.split('.')
    return f"{role_slug.upper()}-{ip_parts[2]}-{ip_parts[3]}"


@app.route('/api/onboard', methods=['POST'])
def onboard_device():
    """
    Single endpoint to onboard a device with IP assignment

    Request Body:
    {
        "name": "CPE-001",           # Optional - auto-generated if not provided
        "ip": "192.168.1.100",        # Required
        "device_type": 1,             # Required - NetBox device type ID
        "role": 1,                    # Required - NetBox role ID
        "site": 1,                    # Optional - defaults to 1
        "username": "admin",          # Optional - for custom fields
        "password": "secret123",      # Optional - will be encrypted
        "turbo_mode": true            # Optional - fastest mode, 3 API calls only (default: true)
    }
    """
    try:
        data = request.get_json()

        # Validate required fields
        if not data.get('ip'):
            return jsonify({'error': 'IP address is required'}), 400
        if not data.get('device_type'):
            return jsonify({'error': 'device_type is required'}), 400
        if not data.get('role'):
            return jsonify({'error': 'role is required'}), 400

        ip_address = data['ip']
        device_type_id = data['device_type']
        role_id = data['role']
        site_id = data.get('site', 1)
        username = data.get('username', '')
        password = data.get('password', '')
        turbo_mode = data.get('turbo_mode', True)  # Fastest mode by default

        # Use IP address as device name if not provided
        device_name = data.get('name') or ip_address

        # Encrypt password (fast operation)
        encrypted_password = encrypt_password(password) if password else ''

        # Prepare custom fields
        custom_fields = {
            'onboarding_status': 'success',
            'device_source': 'manual',
            'last_onboarded': datetime.now().isoformat()
        }
        if username:
            custom_fields['onboarding_username'] = username
        if encrypted_password:
            custom_fields['onboarding_password'] = encrypted_password

        # TURBO MODE: 4 API calls with connection pooling, no validation
        if turbo_mode:
            # Step 1: Create device with custom fields (saves 1 API call)
            device_response = session.post(
                f"{NETBOX_URL}/api/dcim/devices/",
                json={
                    'name': device_name,
                    'device_type': device_type_id,
                    'role': role_id,
                    'site': site_id,
                    'status': 'active',
                    'custom_fields': custom_fields
                }
            )

            if device_response.status_code not in [200, 201]:
                return jsonify({
                    'error': 'Failed to create device',
                    'details': device_response.text
                }), 500

            device_id = device_response.json()['id']

            # Step 2: Create interface
            interface_response = session.post(
                f"{NETBOX_URL}/api/dcim/interfaces/",
                json={
                    'device': device_id,
                    'name': 'mgmt0',
                    'type': 'virtual'
                }
            )

            interface_id = None
            if interface_response.status_code in [200, 201]:
                interface_id = interface_response.json()['id']

            # Step 3: Create IP assigned to interface
            ip_payload = {
                'address': f"{ip_address}/32",
                'status': 'active'
            }
            if interface_id:
                ip_payload['assigned_object_type'] = 'dcim.interface'
                ip_payload['assigned_object_id'] = interface_id

            ip_response = session.post(
                f"{NETBOX_URL}/api/ipam/ip-addresses/",
                json=ip_payload
            )

            ip_id = None
            if ip_response.status_code in [200, 201]:
                ip_id = ip_response.json()['id']

            # Step 4: Set primary IP (custom fields already set in step 1)
            ip_assigned = False
            if ip_id:
                assign_response = session.patch(
                    f"{NETBOX_URL}/api/dcim/devices/{device_id}/",
                    json={'primary_ip4': ip_id}
                )
                ip_assigned = assign_response.status_code == 200

        else:
            # NORMAL MODE: With validation (slower but safer)
            # Check for duplicates in parallel
            def check_ip():
                return session.get(
                    f"{NETBOX_URL}/api/ipam/ip-addresses/",
                    params={'address': ip_address}
                )

            def check_device():
                return session.get(
                    f"{NETBOX_URL}/api/dcim/devices/",
                    params={'name': device_name}
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                ip_future = executor.submit(check_ip)
                device_future = executor.submit(check_device)

                existing_ip = ip_future.result()
                if existing_ip.status_code == 200 and existing_ip.json()['count'] > 0:
                    ip_data = existing_ip.json()['results'][0]
                    if ip_data.get('assigned_object'):
                        return jsonify({
                            'error': 'IP address already in use',
                            'existing_ip_id': ip_data['id']
                        }), 409

                check_response = device_future.result()
                if check_response.status_code == 200 and check_response.json()['count'] > 0:
                    device_name = f"{device_name}-{check_response.json()['count'] + 1}"

            # Create device
            device_response = session.post(
                f"{NETBOX_URL}/api/dcim/devices/",
                json={
                    'name': device_name,
                    'device_type': device_type_id,
                    'role': role_id,
                    'site': site_id,
                    'status': 'active',
                    'custom_fields': custom_fields
                }
            )

            if device_response.status_code not in [200, 201]:
                return jsonify({
                    'error': 'Failed to create device',
                    'details': device_response.text
                }), 500

            device_id = device_response.json()['id']

            # Create interface
            interface_response = session.post(
                f"{NETBOX_URL}/api/dcim/interfaces/",
                json={
                    'device': device_id,
                    'name': 'mgmt0',
                    'type': 'virtual'
                }
            )

            interface_id = None
            if interface_response.status_code in [200, 201]:
                interface_id = interface_response.json()['id']

            # Create IP
            ip_payload = {
                'address': f"{ip_address}/32",
                'status': 'active'
            }
            if interface_id:
                ip_payload['assigned_object_type'] = 'dcim.interface'
                ip_payload['assigned_object_id'] = interface_id

            ip_response = session.post(
                f"{NETBOX_URL}/api/ipam/ip-addresses/",
                json=ip_payload
            )

            ip_id = None
            if ip_response.status_code in [200, 201]:
                ip_id = ip_response.json()['id']

            # Set primary IP
            ip_assigned = False
            if ip_id:
                assign_response = session.patch(
                    f"{NETBOX_URL}/api/dcim/devices/{device_id}/",
                    json={'primary_ip4': ip_id}
                )
                ip_assigned = assign_response.status_code == 200

        # Return success response
        return jsonify({
            'status': 'success',
            'message': 'Device onboarded successfully',
            'data': {
                'device_id': device_id,
                'device_name': device_name,
                'ip_address': ip_address,
                'ip_id': ip_id,
                'ip_assigned': ip_assigned,
                'device_type': device_type_id,
                'role': role_id,
                'site': site_id
            }
        }), 201

    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500


@app.route('/api/device-types', methods=['GET'])
def get_device_types():
    """Get list of available device types"""
    response = session.get(f"{NETBOX_URL}/api/dcim/device-types/")
    if response.status_code == 200:
        types = [{'id': dt['id'], 'name': dt['display']} for dt in response.json()['results']]
        return jsonify(types)
    return jsonify([]), response.status_code


@app.route('/api/device-roles', methods=['GET'])
def get_device_roles():
    """Get list of available device roles"""
    response = session.get(f"{NETBOX_URL}/api/dcim/device-roles/")
    if response.status_code == 200:
        roles = [{'id': r['id'], 'name': r['name']} for r in response.json()['results']]
        return jsonify(roles)
    return jsonify([]), response.status_code


@app.route('/api/sites', methods=['GET'])
def get_sites():
    """Get list of available sites"""
    response = session.get(f"{NETBOX_URL}/api/dcim/sites/")
    if response.status_code == 200:
        sites = [{'id': s['id'], 'name': s['name']} for s in response.json()['results']]
        return jsonify(sites)
    return jsonify([]), response.status_code


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'netbox_url': NETBOX_URL, 'fast_mode': 'enabled'})


@app.route('/', methods=['GET'])
def index():
    """API documentation"""
    return jsonify({
        'service': 'Device Onboarding API (Optimized)',
        'endpoints': {
            'POST /api/onboard': 'Onboard a device with IP assignment (~1s with fast_mode)',
            'GET /api/device-types': 'List available device types',
            'GET /api/device-roles': 'List available device roles',
            'GET /api/sites': 'List available sites',
            'GET /health': 'Health check'
        },
        'example_request': {
            'url': 'POST /api/onboard',
            'body': {
                'name': 'CPE-001',
                'ip': '192.168.1.100',
                'device_type': 1,
                'role': 1,
                'site': 1,
                'username': 'admin',
                'password': 'secret123',
                'fast_mode': True
            },
            'note': 'fast_mode=true (default) skips validation for ~1s response. Set to false for duplicate checking.'
        }
    })


if __name__ == '__main__':
    print(f"""
================================================================================
Device Onboarding API Service (Optimized for Speed)
================================================================================
NetBox URL: {NETBOX_URL}
Mode: Fast mode enabled (skips validation, ~1s response)

Endpoints:
  POST /api/onboard      - Onboard device with IP (~1s with fast_mode)
  GET  /api/device-types - List device types
  GET  /api/device-roles - List device roles
  GET  /api/sites        - List sites
  GET  /health           - Health check

Example (fast mode - default):
  curl -X POST http://localhost:5001/api/onboard \\
    -H "Content-Type: application/json" \\
    -d '{{"ip": "192.168.1.100", "device_type": 1, "role": 1}}'

Example (with validation):
  curl -X POST http://localhost:5001/api/onboard \\
    -H "Content-Type: application/json" \\
    -d '{{"ip": "192.168.1.100", "device_type": 1, "role": 1, "fast_mode": false}}'
================================================================================
""")
    app.run(host='0.0.0.0', port=5001, debug=True)
