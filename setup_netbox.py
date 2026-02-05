#!/usr/bin/env python3
"""
NetBox Setup Script for Device Onboarding

This script configures NetBox with:
1. Custom fields for device onboarding
2. Manufacturers (CTC Union, Edgecore, Exaware)
3. Device types (CPE, Switch, Router models)
4. Device roles (CPE, Access Switch, Router)
5. Webhook for telemetry notifications
6. Event rule to trigger webhook on device create/update

Run this script after NetBox is up and running.

Usage:
    python setup_netbox.py [--netbox-url URL] [--token TOKEN] [--telemetry-url URL]
"""

import requests
import argparse
import time
import sys

# Default configuration
DEFAULT_NETBOX_URL = "http://localhost:8000"
DEFAULT_API_TOKEN = "0123456789abcdef0123456789abcdef01234567"
DEFAULT_TELEMETRY_URL = "http://172.27.1.67:5000/endpoint"


class NetBoxSetup:
    def __init__(self, netbox_url, api_token, telemetry_url):
        self.base_url = netbox_url.rstrip('/')
        self.api_url = f"{self.base_url}/api"
        self.headers = {
            'Authorization': f'Token {api_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        self.telemetry_url = telemetry_url

    def wait_for_netbox(self, max_retries=30, delay=10):
        """Wait for NetBox to be ready"""
        print(f"Waiting for NetBox at {self.base_url}...")
        for i in range(max_retries):
            try:
                response = requests.get(f"{self.api_url}/", headers=self.headers, timeout=5)
                if response.status_code == 200:
                    print("NetBox is ready!")
                    return True
            except requests.exceptions.RequestException:
                pass
            print(f"  Attempt {i+1}/{max_retries} - NetBox not ready yet...")
            time.sleep(delay)
        print("ERROR: NetBox did not become ready in time")
        return False

    def create_custom_fields(self):
        """Create custom fields for device onboarding"""
        print("\n--- Creating Custom Fields ---")

        # Get device content type
        response = requests.get(
            f"{self.api_url}/extras/content-types/",
            headers=self.headers,
            params={'app_label': 'dcim', 'model': 'device'}
        )
        if response.status_code != 200:
            print(f"ERROR: Failed to get content types: {response.text}")
            return False

        content_types = response.json()['results']
        if not content_types:
            print("ERROR: Device content type not found")
            return False

        device_ct_id = content_types[0]['id']
        print(f"  Device content type ID: {device_ct_id}")

        # Define custom fields
        custom_fields = [
            {
                'name': 'onboarding_username',
                'type': 'text',
                'label': 'Onboarding Username',
                'description': 'Username for device access (SNMP community or SSH user)',
                'weight': 100,
                'object_types': [f'dcim.device']
            },
            {
                'name': 'onboarding_password',
                'type': 'text',
                'label': 'Onboarding Password (Encrypted)',
                'description': 'Encrypted password for device access',
                'weight': 110,
                'ui_visible': 'hidden',
                'object_types': [f'dcim.device']
            },
            {
                'name': 'reachable_state',
                'type': 'boolean',
                'label': 'Reachable State',
                'description': 'Whether the device is reachable (set by telemetry)',
                'weight': 120,
                'object_types': [f'dcim.device']
            },
            {
                'name': 'last_onboarded',
                'type': 'datetime',
                'label': 'Last Onboarded',
                'description': 'Timestamp of last onboarding',
                'weight': 130,
                'object_types': [f'dcim.device']
            },
            {
                'name': 'onboarding_status',
                'type': 'select',
                'label': 'Onboarding Status',
                'description': 'Status of device onboarding',
                'weight': 140,
                'choice_set': None,
                'object_types': [f'dcim.device']
            },
            {
                'name': 'device_source',
                'type': 'select',
                'label': 'Device Source',
                'description': 'How the device was added to NetBox',
                'weight': 150,
                'choice_set': None,
                'object_types': [f'dcim.device']
            },
            {
                'name': 'last_reachability_check',
                'type': 'datetime',
                'label': 'Last Reachability Check',
                'description': 'Timestamp of last ping check by monitor',
                'weight': 160,
                'object_types': [f'dcim.device']
            },
            {
                'name': 'last_latency_ms',
                'type': 'decimal',
                'label': 'Last Latency (ms)',
                'description': 'Last measured ping latency in milliseconds',
                'weight': 170,
                'object_types': [f'dcim.device']
            }
        ]

        for cf in custom_fields:
            # Check if already exists
            response = requests.get(
                f"{self.api_url}/extras/custom-fields/",
                headers=self.headers,
                params={'name': cf['name']}
            )
            if response.json()['count'] > 0:
                print(f"  Custom field '{cf['name']}' already exists")
                continue

            response = requests.post(
                f"{self.api_url}/extras/custom-fields/",
                headers=self.headers,
                json=cf
            )
            if response.status_code in [200, 201]:
                print(f"  Created custom field: {cf['name']}")
            else:
                print(f"  WARNING: Failed to create {cf['name']}: {response.text}")

        return True

    def create_manufacturers(self):
        """Create device manufacturers"""
        print("\n--- Creating Manufacturers ---")

        manufacturers = [
            {'name': 'CTC Union', 'slug': 'ctc-union', 'description': 'CTC Union Technologies'},
            {'name': 'Edgecore', 'slug': 'edgecore', 'description': 'Edgecore Networks'},
            {'name': 'Exaware', 'slug': 'exaware', 'description': 'Exaware ExaNOS'}
        ]

        created = {}
        for mfg in manufacturers:
            response = requests.get(
                f"{self.api_url}/dcim/manufacturers/",
                headers=self.headers,
                params={'slug': mfg['slug']}
            )
            if response.json()['count'] > 0:
                created[mfg['slug']] = response.json()['results'][0]['id']
                print(f"  Manufacturer '{mfg['name']}' already exists (ID: {created[mfg['slug']]})")
                continue

            response = requests.post(
                f"{self.api_url}/dcim/manufacturers/",
                headers=self.headers,
                json=mfg
            )
            if response.status_code in [200, 201]:
                created[mfg['slug']] = response.json()['id']
                print(f"  Created manufacturer: {mfg['name']} (ID: {created[mfg['slug']]})")
            else:
                print(f"  WARNING: Failed to create {mfg['name']}: {response.text}")

        return created

    def create_device_types(self, manufacturers):
        """Create device types"""
        print("\n--- Creating Device Types ---")

        device_types = [
            {
                'manufacturer': manufacturers.get('ctc-union'),
                'model': 'MaxLinear 10GE CPE',
                'slug': 'maxlinear-10ge-cpe',
                'u_height': 1,
                'is_full_depth': False,
                'description': 'CTC Union MaxLinear 10GE Customer Premises Equipment'
            },
            {
                'manufacturer': manufacturers.get('edgecore'),
                'model': 'ECS4120-28Fv2-I',
                'slug': 'ecs4120-28fv2-i',
                'u_height': 1,
                'is_full_depth': True,
                'description': 'Edgecore 28-port Fiber Gigabit Switch'
            },
            {
                'manufacturer': manufacturers.get('exaware'),
                'model': 'AS5916-54XL',
                'slug': 'as5916-54xl',
                'u_height': 1,
                'is_full_depth': True,
                'description': 'ExaNOS 54-port 25GE Switch'
            },
            {
                'manufacturer': manufacturers.get('exaware'),
                'model': 'AS7315-27X',
                'slug': 'as7315-27x',
                'u_height': 1,
                'is_full_depth': True,
                'description': 'ExaNOS 27-port 100GE Switch'
            }
        ]

        created = {}
        for dt in device_types:
            if not dt['manufacturer']:
                print(f"  WARNING: Skipping {dt['model']} - manufacturer not found")
                continue

            response = requests.get(
                f"{self.api_url}/dcim/device-types/",
                headers=self.headers,
                params={'slug': dt['slug']}
            )
            if response.json()['count'] > 0:
                created[dt['slug']] = response.json()['results'][0]['id']
                print(f"  Device type '{dt['model']}' already exists (ID: {created[dt['slug']]})")
                continue

            response = requests.post(
                f"{self.api_url}/dcim/device-types/",
                headers=self.headers,
                json=dt
            )
            if response.status_code in [200, 201]:
                created[dt['slug']] = response.json()['id']
                print(f"  Created device type: {dt['model']} (ID: {created[dt['slug']]})")
            else:
                print(f"  WARNING: Failed to create {dt['model']}: {response.text}")

        return created

    def create_device_roles(self):
        """Create device roles"""
        print("\n--- Creating Device Roles ---")

        device_roles = [
            {
                'name': 'CPE',
                'slug': 'cpe',
                'color': '9c27b0',
                'description': 'Customer Premises Equipment'
            },
            {
                'name': 'Access Switch',
                'slug': 'access-switch',
                'color': '2196f3',
                'description': 'Access Layer Switch'
            },
            {
                'name': 'Router',
                'slug': 'router',
                'color': 'ff9800',
                'description': 'Network Router'
            }
        ]

        created = {}
        for role in device_roles:
            response = requests.get(
                f"{self.api_url}/dcim/device-roles/",
                headers=self.headers,
                params={'slug': role['slug']}
            )
            if response.json()['count'] > 0:
                created[role['slug']] = response.json()['results'][0]['id']
                print(f"  Device role '{role['name']}' already exists (ID: {created[role['slug']]})")
                continue

            response = requests.post(
                f"{self.api_url}/dcim/device-roles/",
                headers=self.headers,
                json=role
            )
            if response.status_code in [200, 201]:
                created[role['slug']] = response.json()['id']
                print(f"  Created device role: {role['name']} (ID: {created[role['slug']]})")
            else:
                print(f"  WARNING: Failed to create {role['name']}: {response.text}")

        return created

    def create_site(self):
        """Create default site"""
        print("\n--- Creating Default Site ---")

        site_data = {
            'name': 'Default Site',
            'slug': 'default-site',
            'status': 'active',
            'description': 'Default site for onboarded devices'
        }

        response = requests.get(
            f"{self.api_url}/dcim/sites/",
            headers=self.headers,
            params={'slug': site_data['slug']}
        )
        if response.json()['count'] > 0:
            site_id = response.json()['results'][0]['id']
            print(f"  Site 'Default Site' already exists (ID: {site_id})")
            return site_id

        response = requests.post(
            f"{self.api_url}/dcim/sites/",
            headers=self.headers,
            json=site_data
        )
        if response.status_code in [200, 201]:
            site_id = response.json()['id']
            print(f"  Created site: Default Site (ID: {site_id})")
            return site_id
        else:
            print(f"  WARNING: Failed to create site: {response.text}")
            return None

    def create_webhook(self):
        """Create webhook for device onboarding"""
        print("\n--- Creating Webhook ---")

        webhook_data = {
            'name': 'Device Onboarding Webhook',
            'payload_url': self.telemetry_url,
            'http_method': 'POST',
            'http_content_type': 'application/json',
            'ssl_verification': False,  # For testing with mock service
            'body_template': '''{
  "event": "device.{% if snapshots.prechange %}updated{% else %}onboarded{% endif %}",
  "timestamp": "{{ timestamp }}",
  "data": {
    "device_id": {{ data.id }},
    "device_name": "{{ data.name }}",
    "ip_address": "{% if data.primary_ip4 %}{{ data.primary_ip4.address.ip }}{% else %}null{% endif %}",
    "username": "{{ data.custom_field_data.onboarding_username }}",
    "password": "{{ data.custom_field_data.onboarding_password }}",
    "device_role": "{{ data.role.name }}",
    "device_type": "{{ data.device_type.manufacturer.name }} {{ data.device_type.model }}",
    "manufacturer": "{{ data.device_type.manufacturer.name }}",
    "model": "{{ data.device_type.model }}",
    "site": "{{ data.site.name }}",
    "status": "{{ data.status }}",
    "reachable_state": {% if data.custom_field_data.reachable_state is not none %}{{ data.custom_field_data.reachable_state|lower }}{% else %}null{% endif %},
    "device_source": "{{ data.custom_field_data.device_source }}",
    "last_onboarded": "{{ data.custom_field_data.last_onboarded }}",
    "onboarding_status": "{{ data.custom_field_data.onboarding_status }}",
    "last_reachability_check": "{{ data.custom_field_data.last_reachability_check }}",
    "last_latency_ms": {% if data.custom_field_data.last_latency_ms is not none %}{{ data.custom_field_data.last_latency_ms }}{% else %}null{% endif %}
  }
}'''
        }

        # Check if webhook exists
        response = requests.get(
            f"{self.api_url}/extras/webhooks/",
            headers=self.headers,
            params={'name': webhook_data['name']}
        )
        if response.json()['count'] > 0:
            webhook_id = response.json()['results'][0]['id']
            print(f"  Webhook '{webhook_data['name']}' already exists (ID: {webhook_id})")
            return webhook_id

        response = requests.post(
            f"{self.api_url}/extras/webhooks/",
            headers=self.headers,
            json=webhook_data
        )
        if response.status_code in [200, 201]:
            webhook_id = response.json()['id']
            print(f"  Created webhook: {webhook_data['name']} (ID: {webhook_id})")
            return webhook_id
        else:
            print(f"  WARNING: Failed to create webhook: {response.text}")
            return None

    def create_event_rule(self, webhook_id):
        """Create event rules to trigger webhook"""
        print("\n--- Creating Event Rules ---")

        if not webhook_id:
            print("  WARNING: Skipping event rules - no webhook ID")
            return None

        # Event rule 1: Device Onboarding (new devices with onboarding_status = success)
        onboarding_rule = {
            'name': 'Device Onboarding Event',
            'enabled': True,
            'object_types': ['dcim.device'],
            'event_types': ['object_created'],
            'action_type': 'webhook',
            'action_object_type': 'extras.webhook',
            'action_object_id': webhook_id,
            'conditions': {
                'and': [
                    {'attr': 'custom_field_data.onboarding_status', 'value': 'success'}
                ]
            }
        }

        # Event rule 2: Device Reachability Update (any device update with reachable_state set)
        reachability_rule = {
            'name': 'Device Reachability Update',
            'enabled': True,
            'object_types': ['dcim.device'],
            'event_types': ['object_updated'],
            'action_type': 'webhook',
            'action_object_type': 'extras.webhook',
            'action_object_id': webhook_id,
            'conditions': {
                'and': [
                    {'attr': 'custom_field_data.last_reachability_check', 'negate': True, 'value': ''}
                ]
            }
        }

        rules = [onboarding_rule, reachability_rule]
        created_ids = []

        for rule_data in rules:
            # Check if event rule exists
            response = requests.get(
                f"{self.api_url}/extras/event-rules/",
                headers=self.headers,
                params={'name': rule_data['name']}
            )
            if response.json()['count'] > 0:
                rule_id = response.json()['results'][0]['id']
                print(f"  Event rule '{rule_data['name']}' already exists (ID: {rule_id})")
                created_ids.append(rule_id)
                continue

            response = requests.post(
                f"{self.api_url}/extras/event-rules/",
                headers=self.headers,
                json=rule_data
            )
            if response.status_code in [200, 201]:
                rule_id = response.json()['id']
                print(f"  Created event rule: {rule_data['name']} (ID: {rule_id})")
                created_ids.append(rule_id)
            else:
                print(f"  WARNING: Failed to create event rule '{rule_data['name']}': {response.text}")

        return created_ids

    def run_setup(self):
        """Run complete setup"""
        print("="*70)
        print("NetBox Device Onboarding Setup")
        print("="*70)

        if not self.wait_for_netbox():
            return False

        # Create all components
        self.create_custom_fields()
        manufacturers = self.create_manufacturers()
        self.create_device_types(manufacturers)
        self.create_device_roles()
        self.create_site()
        webhook_id = self.create_webhook()
        self.create_event_rule(webhook_id)

        print("\n" + "="*70)
        print("Setup Complete!")
        print("="*70)
        print(f"\nNetBox URL: {self.base_url}")
        print(f"Admin credentials: admin / admin123")
        print(f"API Token: {self.headers['Authorization'].split()[1]}")
        print(f"\nTelemetry webhook URL: {self.telemetry_url}")
        print("\nYou can now:")
        print("  1. Login to NetBox at http://localhost:8000")
        print("  2. Go to Customization > Scripts")
        print("  3. Run 'Simple Device Onboarding' script")
        print("  4. Check webhook delivery in Operations > Webhooks")
        print("  5. View received webhooks at http://localhost:5000/api/v1/webhooks")
        print("="*70)

        return True


def main():
    parser = argparse.ArgumentParser(description='Setup NetBox for device onboarding')
    parser.add_argument('--netbox-url', default=DEFAULT_NETBOX_URL, help='NetBox URL')
    parser.add_argument('--token', default=DEFAULT_API_TOKEN, help='NetBox API token')
    parser.add_argument('--telemetry-url', default=DEFAULT_TELEMETRY_URL, help='Telemetry service webhook URL')

    args = parser.parse_args()

    setup = NetBoxSetup(args.netbox_url, args.token, args.telemetry_url)
    success = setup.run_setup()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
