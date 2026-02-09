#!/usr/bin/env python3
"""
Setup NetBox Webhook + Event Rule via API.
Points to the telemetry agent at http://172.27.1.70:5000/endpoint.

Usage:
    python setup_webhook.py

Environment variables (optional):
    NETBOX_URL          - NetBox base URL (default: http://localhost:8000)
    NETBOX_TOKEN        - NetBox API token
    TELEMETRY_URL       - Telemetry endpoint (default: http://172.27.1.70:5000/endpoint)
"""

import os
import sys
import requests

NETBOX_URL = os.environ.get('NETBOX_URL', 'http://localhost:8000')
NETBOX_TOKEN = os.environ.get('NETBOX_TOKEN', '0123456789abcdef0123456789abcdef01234567')
TELEMETRY_URL = os.environ.get('TELEMETRY_URL', 'http://172.27.1.70:5000/endpoint')

HEADERS = {
    'Authorization': f'Token {NETBOX_TOKEN}',
    'Content-Type': 'application/json'
}

WEBHOOK_NAME = 'Device Telemetry Webhook'
EVENT_RULE_NAME = 'Device Telemetry Event'


def api_get(path):
    r = requests.get(f"{NETBOX_URL}{path}", headers=HEADERS)
    r.raise_for_status()
    return r.json()


def api_post(path, data):
    r = requests.post(f"{NETBOX_URL}{path}", headers=HEADERS, json=data)
    return r


def api_patch(path, data):
    r = requests.patch(f"{NETBOX_URL}{path}", headers=HEADERS, json=data)
    return r


def api_delete(path):
    r = requests.delete(f"{NETBOX_URL}{path}", headers=HEADERS)
    return r


def setup_webhook():
    """Create or update the webhook."""
    # Check if webhook already exists
    data = api_get(f"/api/extras/webhooks/?name={WEBHOOK_NAME}")
    existing = data.get('results', [])

    webhook_payload = {
        'name': WEBHOOK_NAME,
        'payload_url': TELEMETRY_URL,
        'http_method': 'POST',
        'http_content_type': 'application/json',
        'ssl_verification': False,
    }

    if existing:
        webhook_id = existing[0]['id']
        print(f"[UPDATE] Webhook '{WEBHOOK_NAME}' already exists (ID: {webhook_id}), updating...")
        r = api_patch(f"/api/extras/webhooks/{webhook_id}/", webhook_payload)
        if r.status_code == 200:
            print(f"  -> Updated URL to: {TELEMETRY_URL}")
            return webhook_id
        else:
            print(f"  -> Failed to update: {r.status_code} {r.text}")
            sys.exit(1)
    else:
        print(f"[CREATE] Creating webhook '{WEBHOOK_NAME}'...")
        r = api_post("/api/extras/webhooks/", webhook_payload)
        if r.status_code in [200, 201]:
            webhook_id = r.json()['id']
            print(f"  -> Created webhook ID: {webhook_id}")
            print(f"  -> URL: {TELEMETRY_URL}")
            return webhook_id
        else:
            print(f"  -> Failed to create: {r.status_code} {r.text}")
            sys.exit(1)


def setup_event_rule(webhook_id):
    """Create or update the event rule that triggers the webhook on device changes."""
    # Check if event rule already exists
    data = api_get(f"/api/extras/event-rules/?name={EVENT_RULE_NAME}")
    existing = data.get('results', [])

    # NetBox v4.2 accepts content_types as string list like ["dcim.device"]
    event_rule_payload = {
        'name': EVENT_RULE_NAME,
        'enabled': True,
        'content_types': ['dcim.device'],
        'type_create': True,
        'type_update': True,
        'type_delete': True,
        'action_type': 'webhook',
        'action_object_type': 'extras.webhook',
        'action_object_id': webhook_id,
    }

    if existing:
        rule_id = existing[0]['id']
        print(f"[UPDATE] Event rule '{EVENT_RULE_NAME}' already exists (ID: {rule_id}), updating...")
        r = api_patch(f"/api/extras/event-rules/{rule_id}/", event_rule_payload)
        if r.status_code == 200:
            print(f"  -> Updated event rule to use webhook ID: {webhook_id}")
            return rule_id
        else:
            print(f"  -> Failed to update: {r.status_code} {r.text}")
            print(f"  -> Trying without action_object_type...")
            # Some NetBox versions don't accept action_object_type on PATCH
            del event_rule_payload['action_object_type']
            r = api_patch(f"/api/extras/event-rules/{rule_id}/", event_rule_payload)
            if r.status_code == 200:
                print(f"  -> Updated event rule (retry succeeded)")
                return rule_id
            print(f"  -> Retry failed: {r.status_code} {r.text}")
            sys.exit(1)
    else:
        print(f"[CREATE] Creating event rule '{EVENT_RULE_NAME}'...")
        r = api_post("/api/extras/event-rules/", event_rule_payload)
        if r.status_code in [200, 201]:
            rule_id = r.json()['id']
            print(f"  -> Created event rule ID: {rule_id}")
            print(f"  -> Triggers on: create, update, delete")
            return rule_id
        else:
            print(f"  -> Failed to create: {r.status_code} {r.text}")
            sys.exit(1)


def verify_setup():
    """Verify the webhook and event rule are configured correctly."""
    print("\n[VERIFY] Checking configuration...")

    # Check webhook
    data = api_get(f"/api/extras/webhooks/?name={WEBHOOK_NAME}")
    webhooks = data.get('results', [])
    if webhooks:
        wh = webhooks[0]
        print(f"  Webhook: {wh['name']} (ID: {wh['id']})")
        print(f"    URL: {wh['payload_url']}")
        print(f"    Method: {wh['http_method']}")
    else:
        print("  [WARN] Webhook not found!")

    # Check event rule
    data = api_get(f"/api/extras/event-rules/?name={EVENT_RULE_NAME}")
    rules = data.get('results', [])
    if rules:
        er = rules[0]
        print(f"  Event Rule: {er['name']} (ID: {er['id']})")
        print(f"    Enabled: {er['enabled']}")
        print(f"    Create: {er['type_create']}, Update: {er['type_update']}, Delete: {er['type_delete']}")
        print(f"    Action: {er['action_type']} -> {er.get('action_object_type', 'N/A')}")
    else:
        print("  [WARN] Event rule not found!")


def main():
    print("=" * 60)
    print("NetBox Webhook Setup")
    print("=" * 60)
    print(f"NetBox:    {NETBOX_URL}")
    print(f"Telemetry: {TELEMETRY_URL}")
    print("=" * 60)

    # Test connectivity
    try:
        r = requests.get(f"{NETBOX_URL}/api/status/", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            version = r.json().get('netbox-version', 'unknown')
            print(f"NetBox connected (v{version})\n")
        else:
            print(f"[WARN] NetBox returned status {r.status_code}\n")
    except Exception as e:
        print(f"[ERROR] Cannot connect to NetBox: {e}")
        sys.exit(1)

    # Setup
    webhook_id = setup_webhook()
    setup_event_rule(webhook_id)
    verify_setup()

    print("\n" + "=" * 60)
    print("Setup complete! Webhooks will fire on device create/update/delete")
    print(f"Telemetry endpoint: {TELEMETRY_URL}")
    print("=" * 60)


if __name__ == '__main__':
    main()
