"""
Mock Telemetry Service for Testing NetBox Webhook Integration

This service receives webhook notifications from NetBox when devices are onboarded
and demonstrates how to handle the payload, including password decryption.

Endpoint: POST /api/v1/devices/onboard
"""

from flask import Flask, request, jsonify
from cryptography.fernet import Fernet
from datetime import datetime
import os
import json

app = Flask(__name__)

# Store received webhooks for display
received_webhooks = []


def decrypt_password(encrypted_password):
    """Decrypt the password using the shared encryption key"""
    try:
        key = os.environ.get('NETBOX_DEVICE_ENCRYPTION_KEY')
        if not key:
            return "[DECRYPTION FAILED: No key]"

        if isinstance(key, str):
            key = key.encode()

        cipher = Fernet(key)
        decrypted = cipher.decrypt(encrypted_password.encode()).decode()
        return decrypted
    except Exception as e:
        return f"[DECRYPTION FAILED: {str(e)}]"


@app.route('/api/v1/devices/onboard', methods=['POST'])
def onboard_device():
    """
    Receive device onboarding webhook from NetBox

    Expected payload:
    {
        "event": "device.onboarded",
        "timestamp": "2026-02-05T11:30:00+05:30",
        "data": {
            "device_id": 42,
            "device_name": "CPE-192-168",
            "ip_address": "192.168.1.100",
            "username": "admin",
            "password": "gAAAAABl...(encrypted)",
            "device_role": "CPE",
            "device_type": "CTC Union MaxLinear 10GE",
            ...
        }
    }
    """
    try:
        payload = request.get_json()

        print("\n" + "="*70)
        print("WEBHOOK RECEIVED FROM NETBOX")
        print("="*70)
        print(f"Timestamp: {datetime.now().isoformat()}")
        print(f"Headers: {dict(request.headers)}")
        print(f"\nPayload:\n{json.dumps(payload, indent=2)}")

        # Extract device data
        data = payload.get('data', payload)

        # Try to decrypt password
        encrypted_password = data.get('password') or data.get('custom_field_data', {}).get('onboarding_password')
        if encrypted_password:
            decrypted_password = decrypt_password(encrypted_password)
            print(f"\n[SECURITY] Password decryption result: {decrypted_password[:3]}***")

        # Store webhook for later viewing
        webhook_entry = {
            'received_at': datetime.now().isoformat(),
            'payload': payload,
            'headers': dict(request.headers)
        }
        received_webhooks.append(webhook_entry)

        # Keep only last 100 webhooks
        if len(received_webhooks) > 100:
            received_webhooks.pop(0)

        print("\n[SUCCESS] Webhook processed successfully")
        print("="*70 + "\n")

        # Return success response
        return jsonify({
            'status': 'success',
            'message': 'Device onboarding notification received',
            'device_id': data.get('device_id') or data.get('id'),
            'device_name': data.get('device_name') or data.get('name'),
            'received_at': datetime.now().isoformat()
        }), 200

    except Exception as e:
        print(f"\n[ERROR] Failed to process webhook: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/v1/webhooks', methods=['GET'])
def list_webhooks():
    """List all received webhooks (for debugging)"""
    return jsonify({
        'count': len(received_webhooks),
        'webhooks': received_webhooks[-20:]  # Return last 20
    })


@app.route('/api/v1/webhooks/clear', methods=['POST'])
def clear_webhooks():
    """Clear all stored webhooks"""
    received_webhooks.clear()
    return jsonify({'status': 'success', 'message': 'Webhooks cleared'})


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'telemetry-mock',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/', methods=['GET'])
def index():
    """Root endpoint with service info"""
    return jsonify({
        'service': 'Mock Telemetry Service',
        'description': 'Receives device onboarding webhooks from NetBox',
        'endpoints': {
            'POST /api/v1/devices/onboard': 'Receive device onboarding webhook',
            'GET /api/v1/webhooks': 'List received webhooks',
            'POST /api/v1/webhooks/clear': 'Clear stored webhooks',
            'GET /health': 'Health check'
        },
        'webhooks_received': len(received_webhooks)
    })


if __name__ == '__main__':
    print("\n" + "="*70)
    print("MOCK TELEMETRY SERVICE STARTED")
    print("="*70)
    print(f"Listening on: http://0.0.0.0:5000")
    print(f"Webhook endpoint: POST http://localhost:5000/api/v1/devices/onboard")
    print(f"View webhooks: GET http://localhost:5000/api/v1/webhooks")
    print("="*70 + "\n")

    app.run(host='0.0.0.0', port=5000, debug=True)
