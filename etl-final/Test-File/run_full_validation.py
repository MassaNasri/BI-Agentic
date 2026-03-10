"""
Complete ETL Pipeline Validation and Testing
Comprehensive end-to-end validation with automatic fixes
"""
import subprocess
import json
import time
import requests
import io
from datetime import datetime

def exec_docker(cmd_list):
    """Execute docker command"""
    try:
        result = subprocess.run(
            ["docker"] + cmd_list,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return False, "", str(e)

def check_kafka_topic(topic):
    """Check if Kafka topic exists"""
    success, stdout, _ = exec_docker(["exec", "kafka", "kafka-topics", "--bootstrap-server", "localhost:9092", "--list"])
    return topic in stdout if success else False

def create_kafka_topic(topic):
    """Create Kafka topic"""
    success, stdout, stderr = exec_docker([
        "exec", "kafka", "kafka-topics", "--bootstrap-server", "localhost:9092",
        "--create", "--if-not-exists", "--topic", topic, "--partitions", "1", "--replication-factor", "1"
    ])
    return success

print("="*70)
print("ETL PIPELINE FULL VALIDATION & TESTING")
print("="*70)
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# A) Service Validation
print("A) SERVICE VALIDATION")
print("-"*70)
services = ["zookeeper", "kafka", "clickhouse", "surrealdb", 
            "connector-service", "extractor-service", "transformer-service",
            "loader-service", "metadata-service"]

service_status = {}
for svc in services:
    success, stdout, _ = exec_docker(["ps", "--filter", f"name={svc}", "--format", "{{.Names}}\t{{.Status}}"])
    is_running = svc in stdout and "Up" in stdout
    service_status[svc] = is_running
    icon = "✅" if is_running else "❌"
    print(f"{icon} {svc}: {'running' if is_running else 'stopped'}")

# B) Kafka Topics
print("\nB) KAFKA TOPIC DIAGNOSTICS")
print("-"*70)
topics = ["connection_topic", "schema_topic", "extracted_rows_topic", 
          "clean_rows_topic", "load_rows_topic", "metadata_topic"]

topic_status = {}
for topic in topics:
    exists = check_kafka_topic(topic)
    if not exists:
        print(f"❌ {topic}: NOT FOUND - Creating...")
        if create_kafka_topic(topic):
            print(f"   ✅ Created {topic}")
            exists = True
        else:
            print(f"   ❌ Failed to create {topic}")
    else:
        print(f"✅ {topic}: EXISTS")
    topic_status[topic] = exists

# C) Infrastructure
print("\nC) INFRASTRUCTURE VALIDATION")
print("-"*70)

# ClickHouse
success, stdout, stderr = exec_docker([
    "exec", "clickhouse", "clickhouse-client", "-u", "etl_user", 
    "--password", "etl_pass123", "-d", "etl", "--query", "SELECT 1"
])
ch_connected = success
print(f"{'✅' if ch_connected else '❌'} ClickHouse: {'Connected' if ch_connected else 'Failed'}")

if ch_connected:
    success2, tables, _ = exec_docker([
        "exec", "clickhouse", "clickhouse-client", "-u", "etl_user",
        "--password", "etl_pass123", "-d", "etl", "--query", "SHOW TABLES"
    ])
    if success2:
        table_list = [t.strip() for t in tables.split('\n') if t.strip()]
        print(f"   Tables: {len(table_list)} ({', '.join(table_list[:3])})")

# SurrealDB
try:
    resp = requests.post(
        "http://localhost:8000/sql",
        auth=("root", "root"),
        headers={"Content-Type": "text/plain"},
        data="USE NS bi_etl; USE DB etl_logs; SELECT 1;",
        timeout=5
    )
    surreal_connected = resp.status_code == 200
    print(f"{'✅' if surreal_connected else '❌'} SurrealDB: {'Connected' if surreal_connected else 'Failed'}")
except:
    print("❌ SurrealDB: Connection failed")

# D) Full Pipeline Test
print("\nD) FULL PIPELINE TEST")
print("-"*70)

# Create test file
test_file = "validation_test.csv"
with open(test_file, 'w') as f:
    f.write("id,name,age,city,active\n")
    f.write("1,Test User 1,25,New York,true\n")
    f.write("2,Test User 2,30,Los Angeles,false\n")
    f.write("3,Test User 3,35,Chicago,true\n")

print(f"📁 Created test file: {test_file}")

# Upload
print("📤 Uploading file...")
try:
    with open(test_file, 'rb') as f:
        files = {'file': (test_file, f, 'text/csv')}
        resp = requests.post("http://localhost:8001/api/upload/", files=files, timeout=30)
    
    if resp.status_code == 200:
        print(f"   ✅ Upload successful")
        upload_data = resp.json()
        print(f"   Response: {upload_data.get('message', 'OK')}")
    else:
        print(f"   ❌ Upload failed: {resp.status_code}")
        print("   Testing from inside Docker network...")
        # Try from inside container
        exec_docker(["cp", test_file, "extractor-service:/tmp/test.csv"])
        exec_docker(["exec", "extractor-service", "python", "-c", 
                    "import requests; f=open('/tmp/test.csv','rb'); r=requests.post('http://connector-service:8000/api/upload/', files={'file':f}); print(r.status_code)"])
except Exception as e:
    print(f"   ⚠️  Upload error: {e}")

# Wait for processing
print("\n⏳ Waiting 60 seconds for pipeline processing...")
time.sleep(60)

# Check service logs
print("\n📊 Checking Service Activity:")
services_to_check = {
    "extractor-service": ["EXTRACTOR", "Published", "Processing"],
    "transformer-service": ["TRANSFORMER", "Processed", "clean_rows_topic"],
    "loader-service": ["LOADER", "Loaded", "Flushed", "Table"],
    "metadata-service": ["METADATA", "Logged", "metadata_topic"]
}

for svc, patterns in services_to_check.items():
    success, logs, _ = exec_docker(["logs", svc, "--tail", "50"])
    if success and logs:
        found = any(p in logs for p in patterns)
        icon = "✅" if found else "⚠️"
        print(f"{icon} {svc}: {'Active' if found else 'No activity detected'}")

# E) Final Report
print("\n" + "="*70)
print("VALIDATION SUMMARY")
print("="*70)

running_services = sum(1 for s in service_status.values() if s)
print(f"Services: {running_services}/{len(services)} running")
print(f"Topics: {sum(1 for t in topic_status.values() if t)}/{len(topics)} exist")
print(f"ClickHouse: {'✅' if ch_connected else '❌'}")
print(f"SurrealDB: {'✅' if surreal_connected else '❌'}")

print("\n✅ Validation Complete!")
print("Check individual service logs for detailed activity:")
print("  docker logs -f extractor-service")
print("  docker logs -f transformer-service")
print("  docker logs -f loader-service")
print("  docker logs -f metadata-service")

