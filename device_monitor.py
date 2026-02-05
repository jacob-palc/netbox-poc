#!/usr/bin/env python3
"""
Device Reachability Monitor Service

Continuously monitors device reachability by pinging devices and updating
their status in NetBox. When reachability changes, it triggers webhook events.

Usage:
    python device_monitor.py

Environment Variables:
    NETBOX_URL: NetBox API URL (default: http://localhost:8000)
    NETBOX_TOKEN: API token for authentication
    PING_INTERVAL: Seconds between ping cycles (default: 60)
    PING_COUNT: Number of ping packets (default: 3)
    PING_TIMEOUT: Ping timeout in seconds (default: 2)
"""

import os
import time
import subprocess
import platform
import re
import requests
from datetime import datetime
import threading
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
NETBOX_URL = os.environ.get('NETBOX_URL', 'http://localhost:8000')
NETBOX_TOKEN = os.environ.get('NETBOX_TOKEN', '0123456789abcdef0123456789abcdef01234567')
PING_INTERVAL = int(os.environ.get('PING_INTERVAL', '60'))  # seconds between cycles
PING_COUNT = int(os.environ.get('PING_COUNT', '3'))
PING_TIMEOUT = int(os.environ.get('PING_TIMEOUT', '2'))

HEADERS = {
    'Authorization': f'Token {NETBOX_TOKEN}',
    'Content-Type': 'application/json'
}


def ping_device(ip_address, count=PING_COUNT, timeout=PING_TIMEOUT):
    """Ping device and return reachability status and latency"""
    try:
        system = platform.system().lower()

        if system == 'windows':
            cmd = ['ping', '-n', str(count), '-w', str(timeout * 1000), ip_address]
        else:
            cmd = ['ping', '-c', str(count), '-W', str(timeout), ip_address]

        logger.debug(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=count * timeout + 5)
        is_reachable = result.returncode == 0
        logger.debug(f"  Result: returncode={result.returncode}")

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
    except Exception as e:
        logger.error(f"Ping failed for {ip_address}: {e}")
        return False, None


def get_all_devices():
    """Fetch all devices from NetBox that have a primary IP"""
    devices = []
    url = f"{NETBOX_URL}/api/dcim/devices/"
    params = {'has_primary_ip': 'true', 'limit': 1000}

    try:
        response = requests.get(url, headers=HEADERS, params=params)
        if response.status_code == 200:
            data = response.json()
            devices = data.get('results', [])
            logger.info(f"Found {len(devices)} devices with primary IP")
        else:
            logger.error(f"Failed to fetch devices: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching devices: {e}")

    return devices


def update_device_reachability(device_id, device_name, is_reachable, latency_ms=None):
    """Update device reachability status in NetBox"""
    url = f"{NETBOX_URL}/api/dcim/devices/{device_id}/"

    custom_fields = {
        'reachable_state': is_reachable,
        'last_reachability_check': datetime.now().isoformat()
    }

    if latency_ms is not None:
        custom_fields['last_latency_ms'] = latency_ms

    payload = {
        'custom_fields': custom_fields
    }

    try:
        response = requests.patch(url, headers=HEADERS, json=payload)
        if response.status_code == 200:
            status = "reachable" if is_reachable else "unreachable"
            logger.info(f"Updated {device_name}: {status}" +
                       (f" (latency: {latency_ms}ms)" if latency_ms else ""))
            return True
        else:
            logger.error(f"Failed to update {device_name}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error updating {device_name}: {e}")
        return False


def check_device(device):
    """Check a single device's reachability"""
    device_id = device['id']
    device_name = device['name']

    # Get primary IP address
    primary_ip = device.get('primary_ip4') or device.get('primary_ip6')
    if not primary_ip:
        logger.debug(f"Skipping {device_name}: no primary IP")
        return

    # Extract IP without CIDR notation
    ip_address = primary_ip['address'].split('/')[0]

    # Get current reachability state
    current_state = device.get('custom_field_data', {}).get('reachable_state')

    # Ping the device
    logger.info(f"PING {ip_address} ({device_name})...")
    is_reachable, latency_ms = ping_device(ip_address)

    # Log ping result
    if is_reachable:
        logger.info(f"  ✓ {ip_address} is REACHABLE (latency: {latency_ms}ms)")
    else:
        logger.info(f"  ✗ {ip_address} is UNREACHABLE")

    # Only update if state changed or if we want to always update
    if current_state != is_reachable:
        logger.info(f"Reachability changed for {device_name} ({ip_address}): {current_state} -> {is_reachable}")
        update_device_reachability(device_id, device_name, is_reachable, latency_ms)
    else:
        # Update anyway to refresh timestamp (optional - comment out to only update on change)
        update_device_reachability(device_id, device_name, is_reachable, latency_ms)


def monitor_cycle():
    """Run one monitoring cycle for all devices"""
    logger.info("Starting monitoring cycle...")
    start_time = time.time()

    devices = get_all_devices()

    # Use threading for parallel pings (faster for many devices)
    threads = []
    for device in devices:
        thread = threading.Thread(target=check_device, args=(device,))
        thread.start()
        threads.append(thread)

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    elapsed = time.time() - start_time
    logger.info(f"Monitoring cycle completed in {elapsed:.2f} seconds")


def run_monitor():
    """Main monitoring loop"""
    logger.info(f"""
================================================================================
Device Reachability Monitor
================================================================================
NetBox URL: {NETBOX_URL}
Ping Interval: {PING_INTERVAL} seconds
Ping Count: {PING_COUNT}
Ping Timeout: {PING_TIMEOUT} seconds

Monitoring started...
================================================================================
""")

    while True:
        try:
            monitor_cycle()
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}")

        logger.info(f"Sleeping for {PING_INTERVAL} seconds...")
        time.sleep(PING_INTERVAL)


if __name__ == '__main__':
    run_monitor()
