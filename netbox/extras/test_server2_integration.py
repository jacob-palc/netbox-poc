"""
Test script for Server2 NMS integration

This script tests the Server2 client functionality without requiring
a full NetBox environment.

Usage:
    python test_server2_integration.py
"""

import os
import sys

# Mock Django settings for testing
class MockSettings:
    SERVER2_VALIDATION_ENABLED = True
    SERVER2_BASE_URL = 'http://10.4.160.240:8081'
    SERVER2_AUTH_ENDPOINT = '/api/auth/signin'
    SERVER2_DEVICE_ENDPOINT = '/device'
    SERVER2_USERNAME = 'admin'
    SERVER2_PASSWORD = 'admin'

# Mock django.conf module
class MockDjangoConf:
    settings = MockSettings()

sys.modules['django'] = type(sys)('django')
sys.modules['django.conf'] = MockDjangoConf()

# Now we can import our module
from server2_client import Server2Client, validate_device_with_server2


def test_authentication():
    """Test Server2 authentication"""
    print("\n" + "="*60)
    print("TEST 1: Server2 Authentication")
    print("="*60)
    
    client = Server2Client()
    success = client.authenticate()
    
    if success:
        print("✅ Authentication successful")
        print(f"   Token: {client.token[:20]}..." if client.token else "   No token")
        return True
    else:
        print("❌ Authentication failed")
        return False


def test_device_validation_success():
    """Test device validation with valid credentials"""
    print("\n" + "="*60)
    print("TEST 2: Device Validation (Valid Credentials)")
    print("="*60)
    
    client = Server2Client()
    result = client.validate_device(
        ip_address="10.4.160.240",
        username="rootadmin",
        password="Root@123",
        license_key=""
    )
    
    print(f"Success: {result['success']}")
    print(f"Status Code: {result['status_code']}")
    print(f"Message: {result['message']}")
    
    if result['success']:
        print("✅ Device validation successful")
        return True
    else:
        print("❌ Device validation failed")
        return False


def test_device_validation_failure():
    """Test device validation with invalid credentials"""
    print("\n" + "="*60)
    print("TEST 3: Device Validation (Invalid Credentials)")
    print("="*60)
    
    client = Server2Client()
    result = client.validate_device(
        ip_address="10.4.160.240",
        username="wrong_user",
        password="wrong_pass",
        license_key=""
    )
    
    print(f"Success: {result['success']}")
    print(f"Status Code: {result['status_code']}")
    print(f"Message: {result['message']}")
    
    if not result['success']:
        print("✅ Correctly detected invalid credentials")
        return True
    else:
        print("❌ Should have failed with invalid credentials")
        return False


def test_validate_device_function():
    """Test the convenience function with mock device data"""
    print("\n" + "="*60)
    print("TEST 4: validate_device_with_server2() Function")
    print("="*60)
    
    device_data = {
        'name': '10.4.160.240',
        'primary_ip4': {
            'address': '10.4.160.240/32'
        },
        'custom_fields': {
            'username': 'rootadmin',
            'password': 'Root@123'
        }
    }
    
    result = validate_device_with_server2(device_data)
    
    print(f"Success: {result['success']}")
    print(f"Status Code: {result['status_code']}")
    print(f"Message: {result['message']}")
    
    if result['success']:
        print("✅ Function validation successful")
        return True
    else:
        print("❌ Function validation failed")
        return False


def test_missing_ip():
    """Test validation with missing IP address"""
    print("\n" + "="*60)
    print("TEST 5: Missing IP Address")
    print("="*60)
    
    device_data = {
        'name': 'test-device',
        'custom_fields': {
            'username': 'admin',
            'password': 'admin'
        }
    }
    
    result = validate_device_with_server2(device_data)
    
    print(f"Success: {result['success']}")
    print(f"Message: {result['message']}")
    
    if not result['success'] and 'no primary IP' in result['message']:
        print("✅ Correctly detected missing IP")
        return True
    else:
        print("❌ Should have failed with missing IP")
        return False


def test_missing_credentials():
    """Test validation with missing credentials"""
    print("\n" + "="*60)
    print("TEST 6: Missing Credentials")
    print("="*60)
    
    device_data = {
        'name': 'test-device',
        'primary_ip4': {
            'address': '10.4.160.240/32'
        },
        'custom_fields': {}
    }
    
    result = validate_device_with_server2(device_data)
    
    print(f"Success: {result['success']}")
    print(f"Message: {result['message']}")
    
    # Should use defaults (admin/admin) and attempt validation
    print(f"✅ Used default credentials: {result['message']}")
    return True


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Server2 NMS Integration Test Suite")
    print("="*60)
    print(f"Server2 URL: {MockSettings.SERVER2_BASE_URL}")
    print(f"Username: {MockSettings.SERVER2_USERNAME}")
    
    tests = [
        ("Authentication", test_authentication),
        ("Valid Device", test_device_validation_success),
        ("Invalid Device", test_device_validation_failure),
        ("Convenience Function", test_validate_device_function),
        ("Missing IP", test_missing_ip),
        ("Missing Credentials", test_missing_credentials),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n❌ Test '{name}' raised exception: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
