#!/usr/bin/env python3
"""
High-Performance Device Reachability Monitor Service

Optimized for 20,000+ devices using:
- fping for bulk ICMP (1000x faster than individual pings)
- asyncio + aiohttp for concurrent NetBox API calls
- Batch updates to reduce API overhead
- Connection pooling for efficiency
- Only updates on state change

Usage:
    python device_monitor.py

Environment Variables:
    NETBOX_URL: NetBox API URL (default: http://localhost:8000)
    NETBOX_TOKEN: API token for authentication
    PING_INTERVAL: Seconds between ping cycles (default: 60)
    PING_COUNT: Number of ping packets (default: 3)
    PING_TIMEOUT: Ping timeout in ms (default: 2000)
    BATCH_SIZE: Devices per fping batch (default: 500)
    MAX_CONCURRENT_UPDATES: Max parallel NetBox updates (default: 50)
"""

import os
import time
import asyncio
import aiohttp
import subprocess
import re
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
NETBOX_URL = os.environ.get('NETBOX_URL', 'http://localhost:8000')
NETBOX_TOKEN = os.environ.get('NETBOX_TOKEN', '0123456789abcdef0123456789abcdef01234567')
PING_INTERVAL = int(os.environ.get('PING_INTERVAL', '60'))
PING_COUNT = int(os.environ.get('PING_COUNT', '3'))
PING_TIMEOUT = int(os.environ.get('PING_TIMEOUT', '2000'))  # milliseconds
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', '500'))
MAX_CONCURRENT_UPDATES = int(os.environ.get('MAX_CONCURRENT_UPDATES', '50'))

HEADERS = {
    'Authorization': f'Token {NETBOX_TOKEN}',
    'Content-Type': 'application/json'
}


@dataclass
class DeviceInfo:
    """Device information for monitoring"""
    id: int
    name: str
    ip_address: str
    current_reachable: Optional[bool] = None


@dataclass
class PingResult:
    """Result of pinging a device"""
    ip_address: str
    is_reachable: bool
    latency_ms: Optional[float] = None


def check_fping_available() -> bool:
    """Check if fping is available on the system"""
    try:
        subprocess.run(['fping', '-v'], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def fping_batch(ip_addresses: List[str]) -> Dict[str, PingResult]:
    """
    Use fping to ping multiple IP addresses at once.
    fping is 100-1000x faster than individual ping commands.

    Returns dict mapping IP -> PingResult
    """
    if not ip_addresses:
        return {}

    results = {}

    try:
        # fping options:
        # -c N: ping count
        # -t N: timeout in ms
        # -q: quiet (summary only)
        cmd = [
            'fping',
            '-c', str(PING_COUNT),
            '-t', str(PING_TIMEOUT),
            '-q',  # quiet mode - just stats
        ] + ip_addresses

        logger.debug(f"Running fping for {len(ip_addresses)} hosts")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=PING_COUNT * (PING_TIMEOUT / 1000) + 30  # Extra buffer
        )

        # Parse fping output (comes on stderr in quiet mode)
        # Format: "IP : xmt/rcv/%loss = 3/3/0%, min/avg/max = 0.12/0.15/0.18"
        # Or:     "IP : xmt/rcv/%loss = 3/0/100%"
        output = result.stderr

        for line in output.strip().split('\n'):
            if not line or ':' not in line:
                continue

            try:
                # Parse IP
                ip = line.split(':')[0].strip()

                # Check if reachable (loss < 100%)
                loss_match = re.search(r'(\d+)%', line)
                if loss_match:
                    loss_pct = int(loss_match.group(1))
                    is_reachable = loss_pct < 100
                else:
                    is_reachable = False

                # Parse latency if available
                latency_ms = None
                latency_match = re.search(r'min/avg/max\s*=\s*[\d.]+/([\d.]+)/', line)
                if latency_match:
                    latency_ms = float(latency_match.group(1))

                results[ip] = PingResult(
                    ip_address=ip,
                    is_reachable=is_reachable,
                    latency_ms=latency_ms
                )
            except Exception as e:
                logger.debug(f"Failed to parse fping line: {line} - {e}")

        # Mark any IPs not in output as unreachable
        for ip in ip_addresses:
            if ip not in results:
                results[ip] = PingResult(ip_address=ip, is_reachable=False)

    except subprocess.TimeoutExpired:
        logger.error(f"fping timed out for batch of {len(ip_addresses)} hosts")
        for ip in ip_addresses:
            results[ip] = PingResult(ip_address=ip, is_reachable=False)
    except Exception as e:
        logger.error(f"fping failed: {e}")
        for ip in ip_addresses:
            results[ip] = PingResult(ip_address=ip, is_reachable=False)

    return results


def fallback_ping(ip_address: str) -> PingResult:
    """Fallback to individual ping if fping not available"""
    try:
        cmd = ['ping', '-c', str(PING_COUNT), '-W', str(PING_TIMEOUT // 1000 or 1), ip_address]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        is_reachable = result.returncode == 0
        latency_ms = None

        if is_reachable:
            match = re.search(r'min/avg/max.*?=\s*[\d.]+/([\d.]+)/', result.stdout)
            if match:
                latency_ms = float(match.group(1))

        return PingResult(ip_address=ip_address, is_reachable=is_reachable, latency_ms=latency_ms)
    except Exception as e:
        logger.error(f"Ping failed for {ip_address}: {e}")
        return PingResult(ip_address=ip_address, is_reachable=False)


async def fetch_all_devices(session: aiohttp.ClientSession) -> List[DeviceInfo]:
    """Fetch ALL devices from NetBox with pagination"""
    devices = []
    url = f"{NETBOX_URL}/api/dcim/devices/"
    offset = 0
    limit = 1000

    while True:
        params = {'has_primary_ip': 'true', 'limit': limit, 'offset': offset}

        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get('results', [])

                    for device in results:
                        primary_ip = device.get('primary_ip4') or device.get('primary_ip6')
                        if primary_ip:
                            ip_address = primary_ip['address'].split('/')[0]
                            current_reachable = device.get('custom_fields', {}).get('reachable')

                            devices.append(DeviceInfo(
                                id=device['id'],
                                name=device['name'],
                                ip_address=ip_address,
                                current_reachable=current_reachable
                            ))

                    # Check if there are more pages
                    if len(results) < limit:
                        break
                    offset += limit
                else:
                    logger.error(f"Failed to fetch devices: {response.status}")
                    break
        except Exception as e:
            logger.error(f"Error fetching devices: {e}")
            break

    logger.info(f"Fetched {len(devices)} devices with primary IP")
    return devices


async def update_device_batch(
    session: aiohttp.ClientSession,
    updates: List[Tuple[DeviceInfo, PingResult]],
    semaphore: asyncio.Semaphore
) -> int:
    """Update multiple devices concurrently with rate limiting"""

    async def update_single(device: DeviceInfo, ping_result: PingResult) -> bool:
        async with semaphore:
            url = f"{NETBOX_URL}/api/dcim/devices/{device.id}/"

            payload = {
                'custom_fields': {
                    'reachable': ping_result.is_reachable
                }
            }

            try:
                async with session.patch(url, json=payload) as response:
                    if response.status == 200:
                        status = "UP" if ping_result.is_reachable else "DOWN"
                        latency_str = f" ({ping_result.latency_ms:.1f}ms)" if ping_result.latency_ms else ""
                        logger.info(f"  Updated {device.name} ({device.ip_address}): {status}{latency_str}")
                        return True
                    else:
                        text = await response.text()
                        logger.error(f"Failed to update {device.name}: {response.status} - {text}")
                        return False
            except Exception as e:
                logger.error(f"Error updating {device.name}: {e}")
                return False

    tasks = [update_single(device, result) for device, result in updates]
    results = await asyncio.gather(*tasks)
    return sum(1 for r in results if r)


async def monitor_cycle_async(use_fping: bool):
    """Run one monitoring cycle using async operations"""
    logger.info("=" * 60)
    logger.info("Starting monitoring cycle...")
    cycle_start = time.time()

    # Create aiohttp session with connection pooling
    connector = aiohttp.TCPConnector(limit=100, limit_per_host=50)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:

        # 1. Fetch all devices
        fetch_start = time.time()
        devices = await fetch_all_devices(session)
        fetch_time = time.time() - fetch_start
        logger.info(f"Fetched {len(devices)} devices in {fetch_time:.2f}s")

        if not devices:
            return

        # 2. Group devices by IP for pinging
        ip_to_devices: Dict[str, List[DeviceInfo]] = {}
        for device in devices:
            if device.ip_address not in ip_to_devices:
                ip_to_devices[device.ip_address] = []
            ip_to_devices[device.ip_address].append(device)

        unique_ips = list(ip_to_devices.keys())
        logger.info(f"Pinging {len(unique_ips)} unique IP addresses...")

        # 3. Ping in batches
        ping_start = time.time()
        all_ping_results: Dict[str, PingResult] = {}

        if use_fping:
            # Process in batches using fping
            for i in range(0, len(unique_ips), BATCH_SIZE):
                batch = unique_ips[i:i + BATCH_SIZE]
                batch_results = fping_batch(batch)
                all_ping_results.update(batch_results)

                # Log progress
                done = min(i + BATCH_SIZE, len(unique_ips))
                logger.info(f"  Pinged {done}/{len(unique_ips)} IPs...")
        else:
            # Use thread pool for parallel pinging (fallback)
            with ThreadPoolExecutor(max_workers=100) as executor:
                results = list(executor.map(fallback_ping, unique_ips))
                for result in results:
                    all_ping_results[result.ip_address] = result

        ping_time = time.time() - ping_start

        # Count reachable/unreachable
        reachable_count = sum(1 for r in all_ping_results.values() if r.is_reachable)
        unreachable_count = len(all_ping_results) - reachable_count
        logger.info(f"Ping complete in {ping_time:.2f}s: {reachable_count} UP, {unreachable_count} DOWN")

        # 4. Determine which devices need updates (state changed)
        updates_needed: List[Tuple[DeviceInfo, PingResult]] = []

        for ip, ping_result in all_ping_results.items():
            for device in ip_to_devices.get(ip, []):
                # Only update if state changed
                if device.current_reachable != ping_result.is_reachable:
                    updates_needed.append((device, ping_result))
                    old_state = "UP" if device.current_reachable else "DOWN" if device.current_reachable is not None else "UNKNOWN"
                    new_state = "UP" if ping_result.is_reachable else "DOWN"
                    logger.info(f"State change: {device.name} ({ip}): {old_state} -> {new_state}")

        logger.info(f"State changes detected: {len(updates_needed)} devices")

        # 5. Update NetBox (only changed devices)
        if updates_needed:
            update_start = time.time()
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPDATES)
            updated = await update_device_batch(session, updates_needed, semaphore)
            update_time = time.time() - update_start
            logger.info(f"Updated {updated}/{len(updates_needed)} devices in {update_time:.2f}s")

    cycle_time = time.time() - cycle_start
    logger.info(f"Monitoring cycle completed in {cycle_time:.2f}s")
    logger.info("=" * 60)


def run_monitor():
    """Main monitoring loop"""
    # Check fping availability once at startup
    use_fping = check_fping_available()

    logger.info(f"""
================================================================================
High-Performance Device Reachability Monitor
================================================================================
NetBox URL: {NETBOX_URL}
Ping Interval: {PING_INTERVAL} seconds
Ping Count: {PING_COUNT}
Ping Timeout: {PING_TIMEOUT} ms
Batch Size: {BATCH_SIZE} devices
Max Concurrent Updates: {MAX_CONCURRENT_UPDATES}

Optimized for 20,000+ devices:
  - fping for bulk ICMP pinging: {"ENABLED" if use_fping else "NOT AVAILABLE (install: apt-get install fping)"}
  - asyncio + aiohttp for concurrent API calls
  - Only updates on state change (reduces API load)
  - Connection pooling

Monitoring started...
================================================================================
""")

    if not use_fping:
        logger.warning("fping NOT found - using fallback mode (much slower)")
        logger.warning("Install fping for best performance: apt-get install fping")

    while True:
        try:
            asyncio.run(monitor_cycle_async(use_fping))
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}")
            import traceback
            traceback.print_exc()

        logger.info(f"Next cycle in {PING_INTERVAL} seconds...")
        time.sleep(PING_INTERVAL)


if __name__ == '__main__':
    run_monitor()
