#!/usr/bin/env python3
"""
Test Script for Device Onboarding Flow

This script tests the complete device onboarding flow:
1. Calls the NetBox API to create a device with onboarding custom fields
2. Verifies the device was created
3. Checks if the webhook was received by the telemetry service

Usage:
    python test_onboarding.py [--netbox-url URL] [--telemetry-url URL]
"""

import requests
import argparse
import time
import json
from datetime import datetime
from cryptography.fernet import Fernet

# Default configuration
DEFAULT_NETBOX_URL = "http://localhost:8000"
DEFAULT_TELEMETRY_URL = "http://172.27.1.67:5000"
DEFAULT_API_TOKEN = "0123456789abcdef0123456789abcdef01234567"
ENCRYPTION_KEY = "XPmjtY0wwxQbD0ezEMDhGlAo2_JGXb6yB4yp5I-MnGA="


def encrypt_password(password, key=ENCRYPTION_KEY):
    """Encrypt password using Fernet"""
    if isinstance(key, str):
        key = key.encode()
    cipher = Fernet(key)
    return cipher.encrypt(password.encode()).decode()


def test_onboarding(netbox_url, telemetry_url, api_token):
    """Test the complete onboarding flow"""
    print("="*70)
    print("DEVICE ONBOARDING TEST")
    print("="*70)
    print(f"NetBox URL: {netbox_url}")
    print(f"Telemetry URL: {telemetry_url}")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*70)

    headers = {
        'Authorization': f'Token {api_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    # Step 1: Clear any previous test webhooks
    print("\n--- Step 1: Clear Previous Test Webhooks ---")
    try:
        response = requests.post(f"{telemetry_url}/api/v1/webhooks/clear")
        if response.status_code == 200:
            print("  Webhooks cleared")
        else:
            print(f"  Warning: Could not clear webhooks: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"  Warning: Telemetry service not reachable: {e}")

    # Step 2: Get device type and role IDs
    print("\n--- Step 2: Get Device Type and Role IDs ---")

    # Get device type
    response = requests.get(
        f"{netbox_url}/api/dcim/device-types/",
        headers=headers,
        params={'slug': 'maxlinear-10ge-cpe'}
    )
    if response.status_code != 200 or response.json()['count'] == 0:
        print("  ERROR: MaxLinear 10GE CPE device type not found. Run setup_netbox.py first.")
        return False
    device_type_id = response.json()['results'][0]['id']
    print(f"  Device Type ID: {device_type_id}")

    # Get device role
    response = requests.get(
        f"{netbox_url}/api/dcim/device-roles/",
        headers=headers,
        params={'slug': 'cpe'}
    )
    if response.status_code != 200 or response.json()['count'] == 0:
        print("  ERROR: CPE device role not found. Run setup_netbox.py first.")
        return False
    device_role_id = response.json()['results'][0]['id']
    print(f"  Device Role ID: {device_role_id}")

    # Get site
    response = requests.get(
        f"{netbox_url}/api/dcim/sites/",
        headers=headers,
        params={'slug': 'default-site'}
    )
    if response.status_code != 200 or response.json()['count'] == 0:
        print("  ERROR: Default site not found. Run setup_netbox.py first.")
        return False
    site_id = response.json()['results'][0]['id']
    print(f"  Site ID: {site_id}")

    # Step 3: Create test device
    print("\n--- Step 3: Create Test Device ---")

    test_ip = f"192.168.1.{int(time.time()) % 254 + 1}"
    test_password = "testpassword123"
    encrypted_password = encrypt_password(test_password)

    device_data = {
        'name': f'TEST-CPE-{int(time.time())}',
        'device_type': device_type_id,
        'role': device_role_id,
        'site': site_id,
        'status': 'active',
        'custom_fields': {
            'onboarding_username': 'admin',
            'onboarding_password': encrypted_password,
            'reachable_state': None,
            'last_onboarded': datetime.now().isoformat(),
            'onboarding_status': 'success',
            'device_source': 'manual'
        }
    }

    print(f"  Creating device: {device_data['name']}")
    print(f"  IP: {test_ip}")
    print(f"  Username: admin")
    print(f"  Password: {test_password[:3]}*** (encrypted)")

    response = requests.post(
        f"{netbox_url}/api/dcim/devices/",
        headers=headers,
        json=device_data
    )

    if response.status_code not in [200, 201]:
        print(f"  ERROR: Failed to create device: {response.text}")
        return False

    device_id = response.json()['id']
    device_name = response.json()['name']
    print(f"  SUCCESS: Device created (ID: {device_id})")

    # Step 4: Create IP address and assign to device
    print("\n--- Step 4: Create and Assign IP Address ---")

    ip_data = {
        'address': f'{test_ip}/32',
        'status': 'active',
        'dns_name': device_name,
        'description': f'Management IP for {device_name}'
    }

    response = requests.post(
        f"{netbox_url}/api/ipam/ip-addresses/",
        headers=headers,
        json=ip_data
    )

    if response.status_code in [200, 201]:
        ip_id = response.json()['id']
        print(f"  Created IP address: {test_ip} (ID: {ip_id})")

        # Assign as primary IP
        response = requests.patch(
            f"{netbox_url}/api/dcim/devices/{device_id}/",
            headers=headers,
            json={'primary_ip4': ip_id}
        )
        if response.status_code == 200:
            print(f"  Assigned as primary IP to device")
        else:
            print(f"  Warning: Could not assign primary IP: {response.text}")
    else:
        print(f"  Warning: Could not create IP: {response.text}")

    # Step 5: Wait for webhook to be processed
    print("\n--- Step 5: Wait for Webhook Processing ---")
    print("  Waiting 5 seconds for webhook to be sent...")
    time.sleep(5)

    # Step 6: Check telemetry service for received webhook
    print("\n--- Step 6: Check Telemetry Service ---")

    try:
        response = requests.get(f"{telemetry_url}/api/v1/webhooks")
        if response.status_code == 200:
            webhooks = response.json()
            if webhooks['count'] > 0:
                print(f"  SUCCESS: {webhooks['count']} webhook(s) received!")
                print("\n  Latest webhook payload:")
                latest = webhooks['webhooks'][-1]
                print(json.dumps(latest['payload'], indent=4))
            else:
                print("  WARNING: No webhooks received yet")
                print("  This could be normal if:")
                print("    - Event rule conditions don't match")
                print("    - Webhook is still being processed")
                print("    - NetBox worker is not running")
        else:
            print(f"  ERROR: Failed to get webhooks: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"  ERROR: Could not connect to telemetry service: {e}")

    # Step 7: Verify device in NetBox
    print("\n--- Step 7: Verify Device in NetBox ---")

    response = requests.get(
        f"{netbox_url}/api/dcim/devices/{device_id}/",
        headers=headers
    )

    if response.status_code == 200:
        device = response.json()
        print(f"  Device Name: {device['name']}")
        print(f"  Device Status: {device['status']['value']}")
        print(f"  Device Type: {device['device_type']['display']}")
        print(f"  Device Role: {device['role']['display']}")
        print(f"  Site: {device['site']['display']}")
        if device.get('primary_ip4'):
            print(f"  Primary IP: {device['primary_ip4']['address']}")
        print(f"  Custom Fields:")
        cf = device.get('custom_fields', {})
        print(f"    - onboarding_username: {cf.get('onboarding_username')}")
        print(f"    - onboarding_status: {cf.get('onboarding_status')}")
        print(f"    - device_source: {cf.get('device_source')}")
        print(f"    - last_onboarded: {cf.get('last_onboarded')}")
    else:
        print(f"  ERROR: Could not retrieve device: {response.text}")

    print("\n" + "="*70)
    print("TEST COMPLETE")
    print("="*70)
    print(f"\nDevice URL: {netbox_url}/dcim/devices/{device_id}/")
    print(f"Telemetry webhooks: {telemetry_url}/api/v1/webhooks")
    print("="*70)

    return True


def main():
    parser = argparse.ArgumentParser(description='Test device onboarding flow')
    parser.add_argument('--netbox-url', default=DEFAULT_NETBOX_URL, help='NetBox URL')
    parser.add_argument('--telemetry-url', default=DEFAULT_TELEMETRY_URL, help='Telemetry service URL')
    parser.add_argument('--token', default=DEFAULT_API_TOKEN, help='NetBox API token')

    args = parser.parse_args()

    success = test_onboarding(args.netbox_url, args.telemetry_url, args.token)
    exit(0 if success else 1)


if __name__ == '__main__':
    main()
