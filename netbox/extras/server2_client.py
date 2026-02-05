import logging
import os
from typing import Optional, Dict, Any

import requests
from django.conf import settings

logger = logging.getLogger('netbox.webhooks.server2')

__all__ = (
    'Server2Client',
    'validate_device_with_server2',
)


class Server2Client:
    """
    Client for interacting with Server2 NMS for device validation.
    """
    
    def __init__(
        self,
        base_url: str = None,
        auth_endpoint: str = None,
        device_endpoint: str = None,
        username: str = None,
        password: str = None
    ):
        """
        Initialize Server2 client with configuration.
        
        Args:
            base_url: Base URL of Server2 (e.g., http://10.4.160.240:8081)
            auth_endpoint: Authentication endpoint path (e.g., /api/auth/signin)
            device_endpoint: Device validation endpoint path (e.g., /device)
            username: Server2 admin username
            password: Server2 admin password
        """
        # Load from settings or environment variables
        self.base_url = base_url or getattr(settings, 'SERVER2_BASE_URL', os.getenv('SERVER2_BASE_URL', 'http://10.4.160.240:8081'))
        self.auth_endpoint = auth_endpoint or getattr(settings, 'SERVER2_AUTH_ENDPOINT', os.getenv('SERVER2_AUTH_ENDPOINT', '/api/auth/signin'))
        self.device_endpoint = device_endpoint or getattr(settings, 'SERVER2_DEVICE_ENDPOINT', os.getenv('SERVER2_DEVICE_ENDPOINT', '/device'))
        self.username = username or getattr(settings, 'SERVER2_USERNAME', os.getenv('SERVER2_USERNAME', 'admin'))
        self.password = password or getattr(settings, 'SERVER2_PASSWORD', os.getenv('SERVER2_PASSWORD', 'admin'))
        
        self.token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
    
    def authenticate(self) -> bool:
        """
        Authenticate with Server2 and obtain access token.
        
        Returns:
            True if authentication successful, False otherwise
        """
        auth_url = f"{self.base_url}{self.auth_endpoint}"
        
        try:
            logger.info(f"Authenticating with Server2 at {auth_url}")
            response = self.session.post(
                auth_url,
                json={
                    'username': self.username,
                    'password': self.password
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.token = data.get('token') or data.get('access_token')
                
                if self.token:
                    self.session.headers.update({'Authorization': f'Bearer {self.token}'})
                    logger.info("Server2 authentication successful")
                    return True
                else:
                    logger.error("Server2 authentication response missing token")
                    return False
            else:
                logger.error(f"Server2 authentication failed: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Server2 authentication request failed: {e}")
            return False
    
    def validate_device(
        self,
        ip_address: str,
        username: str,
        password: str,
        license_key: str = ""
    ) -> Dict[str, Any]:
        """
        Validate device SSH credentials with Server2.
        
        Args:
            ip_address: Device IP address
            username: SSH username
            password: SSH password
            license_key: Optional license key
            
        Returns:
            Dict with 'success' (bool), 'status_code' (int), and 'message' (str)
        """
        # Ensure we're authenticated
        if not self.token:
            if not self.authenticate():
                return {
                    'success': False,
                    'status_code': 401,
                    'message': 'Failed to authenticate with Server2'
                }
        
        device_url = f"{self.base_url}{self.device_endpoint}"
        payload = {
            'ipAddress': ip_address,
            'username': username,
            'password': password,
            'licenseKey': license_key
        }
        
        try:
            logger.info(f"Validating device {ip_address} with Server2")
            response = self.session.post(
                device_url,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                message = data.get('message', 'Device validated successfully')
                logger.info(f"Device {ip_address} validation successful: {message}")
                return {
                    'success': True,
                    'status_code': 200,
                    'message': message
                }
            else:
                error_msg = response.text
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', error_msg)
                except:
                    pass
                
                logger.warning(f"Device {ip_address} validation failed: {response.status_code} - {error_msg}")
                return {
                    'success': False,
                    'status_code': response.status_code,
                    'message': error_msg
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Device {ip_address} validation request failed: {e}")
            return {
                'success': False,
                'status_code': 500,
                'message': f'Server2 request failed: {str(e)}'
            }
    
    def close(self):
        """Close the session."""
        self.session.close()


def validate_device_with_server2(device_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to validate a device with Server2.
    
    Args:
        device_data: Dictionary containing device information with keys:
            - 'primary_ip4': IP address object with 'address' field
            - 'custom_fields': Dict with 'username' and 'password'
            
    Returns:
        Dict with 'success' (bool), 'status_code' (int), and 'message' (str)
    """
    # Check if Server2 validation is enabled
    validation_enabled = getattr(settings, 'SERVER2_VALIDATION_ENABLED', os.getenv('SERVER2_VALIDATION_ENABLED', 'true').lower() == 'true')
    
    if not validation_enabled:
        logger.debug("Server2 validation is disabled, skipping")
        return {
            'success': True,
            'status_code': 200,
            'message': 'Server2 validation disabled'
        }
    
    # Extract device IP
    primary_ip4 = device_data.get('primary_ip4')
    if not primary_ip4 or not primary_ip4.get('address'):
        logger.warning("Device has no primary IP address, skipping Server2 validation")
        return {
            'success': False,
            'status_code': 400,
            'message': 'Device has no primary IP address'
        }
    
    ip_address = primary_ip4['address']
    # Remove CIDR suffix if present
    if '/' in ip_address:
        ip_address = ip_address.split('/')[0]
    
    # Extract credentials from custom fields
    custom_fields = device_data.get('custom_fields', {})
    username = custom_fields.get('username') or custom_fields.get('ssh_username', 'admin')
    password = custom_fields.get('password') or custom_fields.get('ssh_password', 'admin')
    
    if not username or not password:
        logger.warning(f"Device {ip_address} missing SSH credentials, skipping Server2 validation")
        return {
            'success': False,
            'status_code': 400,
            'message': 'Device missing SSH credentials'
        }
    
    # Validate with Server2
    client = Server2Client()
    try:
        result = client.validate_device(
            ip_address=ip_address,
            username=username,
            password=password
        )
        return result
    finally:
        client.close()
