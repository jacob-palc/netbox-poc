import logging
import os
import socket
from typing import Dict, Any

from django.conf import settings

logger = logging.getLogger('netbox.webhooks.ssh_validator')

__all__ = (
    'SSHValidator',
    'validate_device_ssh',
)


class SSHValidator:
    """
    Validates device SSH credentials by connecting directly using Paramiko.
    Replaces the external Server2 HTTP-based validation.
    """

    def __init__(
        self,
        port: int = None,
        timeout: int = None,
        test_command: str = None,
    ):
        self.port = port or int(
            getattr(settings, 'SSH_VALIDATION_PORT', os.getenv('SSH_VALIDATION_PORT', '22'))
        )
        self.timeout = timeout or int(
            getattr(settings, 'SSH_VALIDATION_TIMEOUT', os.getenv('SSH_VALIDATION_TIMEOUT', '30'))
        )
        self.test_command = test_command or getattr(
            settings, 'SSH_VALIDATION_COMMAND', os.getenv('SSH_VALIDATION_COMMAND', 'show version')
        )

    def validate_device(
        self,
        ip_address: str,
        username: str,
        password: str,
    ) -> Dict[str, Any]:
        """
        Validate device SSH credentials by attempting a direct SSH connection.

        Args:
            ip_address: Device IP address
            username: SSH username
            password: SSH password

        Returns:
            Dict with 'success' (bool), 'status_code' (int), and 'message' (str)
        """
        try:
            import paramiko
        except ImportError:
            logger.error("paramiko is not installed. Install it with: pip install paramiko")
            return {
                'success': False,
                'status_code': 500,
                'message': 'paramiko is not installed',
            }

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            logger.info(f"SSH connecting to {ip_address}:{self.port} as {username}")
            ssh.connect(
                hostname=ip_address,
                port=self.port,
                username=username,
                password=password,
                timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False,
            )

            # Run a test command to confirm the session works
            stdin, stdout, stderr = ssh.exec_command(self.test_command, timeout=self.timeout)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode('utf-8', errors='replace').strip()
            error_output = stderr.read().decode('utf-8', errors='replace').strip()

            if exit_status == 0:
                logger.info(f"SSH validation successful for {ip_address}")
                return {
                    'success': True,
                    'status_code': 200,
                    'message': f'SSH validation successful',
                }
            else:
                msg = error_output or f'Command exited with status {exit_status}'
                logger.warning(f"SSH command failed on {ip_address}: {msg}")
                return {
                    'success': True,  # SSH connected, command result is secondary
                    'status_code': 200,
                    'message': f'SSH connected, command returned exit status {exit_status}',
                }

        except paramiko.AuthenticationException:
            logger.warning(f"SSH authentication failed for {ip_address} as {username}")
            return {
                'success': False,
                'status_code': 401,
                'message': f'SSH authentication failed for {username}@{ip_address}',
            }
        except (paramiko.SSHException, socket.error) as e:
            logger.warning(f"SSH connection failed for {ip_address}: {e}")
            return {
                'success': False,
                'status_code': 502,
                'message': f'SSH connection failed: {str(e)}',
            }
        except Exception as e:
            logger.error(f"Unexpected error during SSH validation for {ip_address}: {e}")
            return {
                'success': False,
                'status_code': 500,
                'message': f'SSH validation error: {str(e)}',
            }
        finally:
            ssh.close()


def validate_device_ssh(device_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to validate a device via direct SSH.

    Args:
        device_data: Dictionary containing device information with keys:
            - 'primary_ip4': IP address object with 'address' field
            - 'custom_fields': Dict with 'username' and 'password'

    Returns:
        Dict with 'success' (bool), 'status_code' (int), and 'message' (str)
    """
    # Check if SSH validation is enabled
    validation_enabled = getattr(
        settings, 'SSH_VALIDATION_ENABLED',
        os.getenv('SSH_VALIDATION_ENABLED', 'true').lower() == 'true'
    )

    if not validation_enabled:
        logger.debug("SSH validation is disabled, skipping")
        return {
            'success': True,
            'status_code': 200,
            'message': 'SSH validation disabled',
        }

    # Extract device IP
    primary_ip4 = device_data.get('primary_ip4')
    if not primary_ip4 or not primary_ip4.get('address'):
        logger.warning("Device has no primary IP address, skipping SSH validation")
        return {
            'success': False,
            'status_code': 400,
            'message': 'Device has no primary IP address',
        }

    ip_address = primary_ip4['address']
    # Remove CIDR suffix if present
    if '/' in ip_address:
        ip_address = ip_address.split('/')[0]

    # Extract credentials from custom fields
    custom_fields = device_data.get('custom_fields', {})
    username = custom_fields.get('username') or custom_fields.get('ssh_username')
    password = custom_fields.get('password') or custom_fields.get('ssh_password')

    if not username or not password:
        logger.warning(f"Device {ip_address} missing SSH credentials, skipping validation")
        return {
            'success': False,
            'status_code': 400,
            'message': 'Device missing SSH credentials',
        }

    # Decrypt password if encryption key is available
    encryption_key = getattr(
        settings, 'NETBOX_DEVICE_ENCRYPTION_KEY',
        os.getenv('NETBOX_DEVICE_ENCRYPTION_KEY')
    )
    if encryption_key:
        try:
            from cryptography.fernet import Fernet, InvalidToken
            fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
            password = fernet.decrypt(password.encode() if isinstance(password, str) else password).decode()
        except (InvalidToken, Exception) as e:
            # Password may not be encrypted, use as-is
            logger.debug(f"Password decryption skipped for {ip_address}: {e}")

    # Validate via SSH
    validator = SSHValidator()
    return validator.validate_device(
        ip_address=ip_address,
        username=username,
        password=password,
    )
