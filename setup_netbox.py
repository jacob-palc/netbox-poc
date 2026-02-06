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

        # NetBox 4.x accepts object_types as strings directly (e.g., "dcim.device")
        # No need to look up content type IDs

        # Define custom fields
        custom_fields = [
            {
                'name': 'username',
                'type': 'text',
                'label': 'Username',
                'description': 'SSH username for device access',
                'weight': 100,
                'object_types': ['dcim.device']
            },
            {
                'name': 'password',
                'type': 'text',
                'label': 'Password (Encrypted)',
                'description': 'Encrypted SSH password for device access',
                'weight': 110,
                'ui_visible': 'hidden',
                'object_types': ['dcim.device']
            },
            {
                'name': 'reachable',
                'type': 'boolean',
                'label': 'Reachable',
                'description': 'Whether the device is reachable via ping',
                'weight': 120,
                'object_types': ['dcim.device']
            },
            {
                'name': 'authentication',
                'type': 'boolean',
                'label': 'Authentication',
                'description': 'Whether SSH authentication was successful',
                'weight': 130,
                'object_types': ['dcim.device']
            },
            {
                'name': 'management',
                'type': 'boolean',
                'label': 'Management',
                'description': 'Whether device is under management',
                'weight': 140,
                'object_types': ['dcim.device']
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
    "username": "{{ data.custom_field_data.username }}",
    "password": "{{ data.custom_field_data.password }}",
    "device_role": "{{ data.role.name }}",
    "device_type": "{{ data.device_type.manufacturer.name }} {{ data.device_type.model }}",
    "manufacturer": "{{ data.device_type.manufacturer.name }}",
    "model": "{{ data.device_type.model }}",
    "site": "{{ data.site.name }}",
    "status": "{{ data.status }}",
    "reachable": {% if data.custom_field_data.reachable is not none %}{{ data.custom_field_data.reachable|lower }}{% else %}null{% endif %},
    "authentication": {% if data.custom_field_data.authentication is not none %}{{ data.custom_field_data.authentication|lower }}{% else %}null{% endif %},
    "management": {% if data.custom_field_data.management is not none %}{{ data.custom_field_data.management|lower }}{% else %}null{% endif %}
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

        # Event rule 1: Device Onboarding (new devices created)
        onboarding_rule = {
            'name': 'Device Onboarding Event',
            'enabled': True,
            'object_types': ['dcim.device'],
            'event_types': ['object_created'],
            'action_type': 'webhook',
            'action_object_type': 'extras.webhook',
            'action_object_id': webhook_id
        }

        # Event rule 2: Device Update (any device update)
        update_rule = {
            'name': 'Device Update Event',
            'enabled': True,
            'object_types': ['dcim.device'],
            'event_types': ['object_updated'],
            'action_type': 'webhook',
            'action_object_type': 'extras.webhook',
            'action_object_id': webhook_id
        }

        rules = [onboarding_rule, update_rule]
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
