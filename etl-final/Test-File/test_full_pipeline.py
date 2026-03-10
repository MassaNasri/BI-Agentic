"""
Full ETL Pipeline End-to-End Test
Tests complete pipeline flow and validates all stages
"""
import requests
import time
import json
import subprocess
from datetime import datetime

def run_cmd(cmd):
    """Run command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def check_service_logs(service, pattern):
    """Check service logs for pattern"""
    success, stdout, _ = run_cmd(f"docker logs {service} 2>&1 | Select-String -Pattern '{pattern}' | Select-Object -Last 5")
    return stdout if success else ""

def test_pipeline():
    """Test full ETL pipeline"""
    print("="*70)
    print("FULL ETL PIPELINE END-TO-END TEST")
    print("="*70)
    print(f"Started: {datetime.now().isoformat()}\n")
    
    results = {
        "test_start": datetime.now().isoformat(),
        "stages": {},
        "topics": {},
        "errors": [],
        "fixes": []
    }
    
    # Step 1: Create test file
    print("📝 Step 1: Creating test file...")
    test_file = "test_full_pipeline.csv"
    with open(test_file, 'w') as f:
        f.write("id,name,age,city,active\n")
        f.write("1,John Doe,25,New York,true\n")
        f.write("2,Jane Smith,30,Los Angeles,false\n")
        f.write("3,Bob Johnson,35,Chicago,true\n")
        f.write("4,Alice Brown,28,Houston,false\n")
        f.write("5,Charlie Wilson,32,Phoenix,true\n")
    print(f"   ✅ Created {test_file} with 5 rows\n")
    
    # Step 2: Upload file
    print("📤 Step 2: Uploading file to connector-service...")
    try:
        with open(test_file, 'rb') as f:
            files = {'file': (test_file, f, 'text/csv')}
            response = requests.post(
                "http://localhost:8001/api/upload/",
                files=files,
                timeout=30
            )
        
        if response.status_code == 200:
            print(f"   ✅ Upload successful: {response.json()}")
            results["stages"]["upload"] = {"status": "success", "response": response.json()}
        else:
            print(f"   ❌ Upload failed: {response.status_code}")
            results["stages"]["upload"] = {"status": "failed", "code": response.status_code}
            return results
    except Exception as e:
        print(f"   ❌ Upload error: {e}")
        results["errors"].append(f"Upload failed: {e}")
        return results
    
    # Step 3: Wait and check each stage
    print("\n⏳ Step 3: Waiting for pipeline to process (45 seconds)...")
    time.sleep(45)
    
    # Step 4: Check Extract stage
    print("\n🔍 Step 4: Checking Extract Stage...")
    extractor_logs = check_service_logs("extractor-service", "EXTRACTOR|Published|Processing")
    if "Published" in extractor_logs or "Processing" in extractor_logs:
        print("   ✅ Extractor is processing")
        results["stages"]["extract"] = {"status": "processing"}
    else:
        print("   ⚠️  No extractor activity detected")
        results["stages"]["extract"] = {"status": "unknown"}
    
    # Step 5: Check Transform stage
    print("\n🔄 Step 5: Checking Transform Stage...")
    transformer_logs = check_service_logs("transformer-service", "TRANSFORMER|Processed|Sent to clean_rows_topic")
    if "Processed" in transformer_logs or "Sent to clean_rows_topic" in transformer_logs:
        print("   ✅ Transformer is processing")
        results["stages"]["transform"] = {"status": "processing"}
    else:
        print("   ⚠️  No transformer activity detected")
        results["stages"]["transform"] = {"status": "unknown"}
    
    # Step 6: Check Load stage
    print("\n💾 Step 6: Checking Load Stage...")
    loader_logs = check_service_logs("loader-service", "LOADER|Loaded|Table|Flushed")
    if "Loaded" in loader_logs or "Flushed" in loader_logs:
        print("   ✅ Loader is processing")
        results["stages"]["load"] = {"status": "processing"}
    else:
        print("   ⚠️  No loader activity detected")
        results["stages"]["load"] = {"status": "unknown"}
    
    # Step 7: Check Metadata stage
    print("\n📊 Step 7: Checking Metadata Stage...")
    metadata_logs = check_service_logs("metadata-service", "METADATA|Logged|metadata_topic")
    if "Logged" in metadata_logs or "metadata_topic" in metadata_logs:
        print("   ✅ Metadata service is processing")
        results["stages"]["metadata"] = {"status": "processing"}
    else:
        print("   ⚠️  No metadata activity detected")
        results["stages"]["metadata"] = {"status": "unknown"}
    
    # Step 8: Verify ClickHouse data
    print("\n🗄️  Step 8: Verifying ClickHouse Data...")
    success, stdout, stderr = run_cmd(
        'docker exec clickhouse clickhouse-client -u etl_user --password etl_pass123 -d etl --query "SHOW TABLES"'
    )
    if success and stdout:
        tables = [t.strip() for t in stdout.strip().split('\n') if t.strip()]
        print(f"   ✅ Found {len(tables)} tables: {', '.join(tables)}")
        
        # Check for our test table
        test_table = None
        for table in tables:
            if "test_full_pipeline" in table.lower():
                test_table = table
                break
        
        if test_table:
            # Count rows
            success2, count_out, _ = run_cmd(
                f'docker exec clickhouse clickhouse-client -u etl_user --password etl_pass123 -d etl --query "SELECT count() FROM {test_table}"'
            )
            if success2:
                count = count_out.strip()
                print(f"   ✅ Table {test_table} has {count} rows")
                results["stages"]["clickhouse"] = {"status": "success", "table": test_table, "rows": count}
            else:
                print(f"   ⚠️  Could not count rows in {test_table}")
        else:
            print(f"   ⚠️  Test table not found yet (may still be processing)")
    else:
        print(f"   ❌ Could not connect to ClickHouse: {stderr}")
        results["errors"].append(f"ClickHouse connection failed: {stderr}")
    
    # Step 9: Verify SurrealDB metadata
    print("\n📋 Step 9: Verifying SurrealDB Metadata...")
    try:
        response = requests.post(
            "http://localhost:8000/sql",
            auth=("root", "root"),
            headers={"Content-Type": "text/plain", "Accept": "application/json"},
            data="USE NS bi_etl; USE DB etl_logs; SELECT * FROM upload_logs LIMIT 5;",
            timeout=10
        )
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ SurrealDB connected")
            results["stages"]["surrealdb"] = {"status": "connected"}
        else:
            print(f"   ⚠️  SurrealDB query failed: {response.status_code}")
    except Exception as e:
        print(f"   ⚠️  SurrealDB error: {e}")
    
    results["test_end"] = datetime.now().isoformat()
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    for stage, data in results["stages"].items():
        status = data.get("status", "unknown")
        icon = "✅" if status == "success" else "⚠️" if status == "processing" else "❌"
        print(f"{icon} {stage}: {status}")
    
    if results["errors"]:
        print(f"\n⚠️  Errors: {len(results['errors'])}")
        for error in results["errors"][:3]:
            print(f"   - {error}")
    
    return results

if __name__ == "__main__":
    results = test_pipeline()
    with open("pipeline_test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\n📄 Results saved to pipeline_test_results.json")

