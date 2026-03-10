#!/usr/bin/env python
"""
Demo script to test virus scanning functionality.

This script demonstrates:
1. Mock scanner with clean and infected files
2. Configuration options
3. Error handling

Usage:
    python test_virus_scanning_demo.py
"""

import os
import sys
import tempfile

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'connector.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'connector'))

import django
django.setup()

from django.conf import settings
from etl_engine.virus_scanner import (
    scan_file,
    scan_file_or_raise,
    VirusDetectedError,
    VirusScanError,
    is_virus_scan_enabled,
    get_scanner_backend,
)


def print_header(text):
    """Print formatted header."""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def test_configuration():
    """Test configuration display."""
    print_header("Configuration")
    print(f"Virus Scan Enabled: {is_virus_scan_enabled()}")
    print(f"Scanner Backend: {settings.VIRUS_SCAN_BACKEND}")
    
    if settings.VIRUS_SCAN_BACKEND == 'clamav':
        print(f"ClamAV Host: {settings.CLAMAV_HOST}")
        print(f"ClamAV Port: {settings.CLAMAV_PORT}")
        print(f"ClamAV Timeout: {settings.CLAMAV_TIMEOUT}s")
    
    backend = get_scanner_backend()
    print(f"Backend Instance: {backend.__class__.__name__}")


def test_clean_file():
    """Test scanning a clean file."""
    print_header("Test 1: Clean File")
    
    # Create temporary clean file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("name,age,city\n")
        f.write("Alice,30,NYC\n")
        f.write("Bob,25,LA\n")
        temp_path = f.name
    
    try:
        print(f"Scanning file: {temp_path}")
        is_clean, virus_name = scan_file(temp_path)
        
        if is_clean:
            print("✓ Result: CLEAN")
            print(f"  Virus Name: {virus_name}")
        else:
            print("✗ Result: INFECTED")
            print(f"  Virus Name: {virus_name}")
    
    finally:
        os.unlink(temp_path)


def test_infected_file():
    """Test scanning a file with 'virus' in name (mock scanner)."""
    print_header("Test 2: Infected File (Mock Scanner)")
    
    # Create temporary file with 'virus' in name
    with tempfile.NamedTemporaryFile(mode='w', suffix='_virus_test.csv', delete=False) as f:
        f.write("malicious,data\n")
        temp_path = f.name
    
    try:
        print(f"Scanning file: {temp_path}")
        is_clean, virus_name = scan_file(temp_path)
        
        if is_clean:
            print("✓ Result: CLEAN")
            print(f"  Virus Name: {virus_name}")
        else:
            print("✗ Result: INFECTED")
            print(f"  Virus Name: {virus_name}")
    
    finally:
        os.unlink(temp_path)


def test_scan_or_raise():
    """Test scan_file_or_raise function."""
    print_header("Test 3: Scan or Raise")
    
    # Test with clean file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("clean,data\n")
        clean_path = f.name
    
    try:
        print(f"Scanning clean file: {clean_path}")
        scan_file_or_raise(clean_path)
        print("✓ No exception raised (file is clean)")
    except VirusDetectedError as e:
        print(f"✗ Virus detected: {e}")
    finally:
        os.unlink(clean_path)
    
    # Test with infected file (mock)
    with tempfile.NamedTemporaryFile(mode='w', suffix='_virus.csv', delete=False) as f:
        f.write("infected,data\n")
        infected_path = f.name
    
    try:
        print(f"\nScanning infected file: {infected_path}")
        scan_file_or_raise(infected_path)
        print("✗ No exception raised (should have detected virus)")
    except VirusDetectedError as e:
        print(f"✓ Exception raised: {e}")
    finally:
        os.unlink(infected_path)


def test_disabled_scanning():
    """Test with scanning disabled."""
    print_header("Test 4: Disabled Scanning")
    
    # Temporarily disable scanning
    original_enabled = settings.VIRUS_SCAN_ENABLED
    settings.VIRUS_SCAN_ENABLED = False
    
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='_virus.csv', delete=False) as f:
            f.write("infected,data\n")
            temp_path = f.name
        
        try:
            print(f"Scanning file with scanning disabled: {temp_path}")
            is_clean, virus_name = scan_file(temp_path)
            
            if is_clean:
                print("✓ Result: CLEAN (scanning disabled)")
                print(f"  Virus Name: {virus_name}")
            else:
                print("✗ Result: INFECTED (unexpected)")
        
        finally:
            os.unlink(temp_path)
    
    finally:
        settings.VIRUS_SCAN_ENABLED = original_enabled


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("  Virus Scanning Demo")
    print("="*60)
    
    try:
        test_configuration()
        test_clean_file()
        test_infected_file()
        test_scan_or_raise()
        test_disabled_scanning()
        
        print_header("Summary")
        print("✓ All tests completed successfully!")
        print("\nNote: This demo uses the mock scanner by default.")
        print("To test with real ClamAV:")
        print("  1. Start ClamAV: docker-compose up -d clamav")
        print("  2. Wait for virus definitions to download (5-10 min)")
        print("  3. Set VIRUS_SCAN_BACKEND=clamav")
        print("  4. Run this script again")
    
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
