"""
Comprehensive ETL Pipeline Validation Script
Tests all components end-to-end and generates health report
"""
import subprocess
import json
import time
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional

class PipelineValidator:
    """Comprehensive pipeline validator"""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.utcnow().isoformat(),
            "services": {},
            "kafka_topics": {},
            "pipeline_test": {},
            "metadata_validation": {},
            "errors": [],
            "fixes": []
        }
    
    def run_command(self, cmd: List[str], capture_output: bool = True) -> tuple[int, str, str]:
        """Run a shell command and return result"""
        try:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                timeout=30
            )
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            return 1, "", str(e)
    
    def check_service(self, service_name: str) -> Dict[str, Any]:
        """Check if a Docker service is running"""
        code, stdout, stderr = self.run_command(
            ["docker", "ps", "--filter", f"name={service_name}", "--format", "{{.Names}}\t{{.Status}}"]
        )
        
        is_running = service_name in stdout and "Up" in stdout
        status = "running" if is_running else "stopped"
        
        return {
            "name": service_name,
            "status": status,
            "running": is_running,
            "details": stdout.strip() if stdout else stderr
        }
    
    def check_kafka_topic(self, topic_name: str) -> Dict[str, Any]:
        """Check Kafka topic existence and details"""
        # Check if topic exists
        code, stdout, stderr = self.run_command(
            ["docker", "exec", "kafka", "kafka-topics", "--bootstrap-server", "localhost:9092", 
             "--list"]
        )
        
        exists = topic_name in stdout
        
        if exists:
            # Get topic details
            code2, details, _ = self.run_command(
                ["docker", "exec", "kafka", "kafka-topics", "--bootstrap-server", "localhost:9092",
                 "--describe", "--topic", topic_name]
            )
            
            # Parse partition and replication info
            partitions = 1
            replication = 1
            if details:
                for line in details.split('\n'):
                    if 'PartitionCount' in line:
                        try:
                            parts = line.split('PartitionCount:')[1].split(',')[0].strip()
                            partitions = int(parts)
                        except:
                            pass
                    if 'ReplicationFactor' in line:
                        try:
                            repl = line.split('ReplicationFactor:')[1].strip()
                            replication = int(repl)
                        except:
                            pass
        else:
            details = "Topic does not exist"
        
        return {
            "name": topic_name,
            "exists": exists,
            "partitions": partitions if exists else 0,
            "replication": replication if exists else 0,
            "details": details.strip() if exists else "Not found"
        }
    
    def check_clickhouse(self) -> Dict[str, Any]:
        """Check ClickHouse connectivity and tables"""
        # Test connection
        code, stdout, stderr = self.run_command(
            ["docker", "exec", "clickhouse", "clickhouse-client", 
             "-u", "etl_user", "--password", "etl_pass123", "-d", "etl",
             "--query", "SELECT 1"]
        )
        
        connected = code == 0
        
        # Get tables
        tables = []
        if connected:
            code2, stdout2, _ = self.run_command(
                ["docker", "exec", "clickhouse", "clickhouse-client",
                 "-u", "etl_user", "--password", "etl_pass123", "-d", "etl",
                 "--query", "SHOW TABLES"]
            )
            if code2 == 0 and stdout2:
                tables = [t.strip() for t in stdout2.strip().split('\n') if t.strip()]
        
        return {
            "connected": connected,
            "database": "etl",
            "user": "etl_user",
            "tables": tables,
            "table_count": len(tables)
        }
    
    def check_surrealdb(self) -> Dict[str, Any]:
        """Check SurrealDB connectivity"""
        try:
            response = requests.post(
                "http://localhost:8000/sql",
                auth=("root", "root"),
                headers={"Content-Type": "text/plain", "Accept": "application/json"},
                data="USE NS bi_etl; USE DB etl_logs; SELECT count() FROM upload_logs;",
                timeout=5
            )
            connected = response.status_code == 200
            return {
                "connected": connected,
                "namespace": "bi_etl",
                "database": "etl_logs",
                "status_code": response.status_code
            }
        except Exception as e:
            return {
                "connected": False,
                "error": str(e)
            }
    
    def validate_all_services(self):
        """Validate all Docker services"""
        print("\n" + "="*60)
        print("A) SERVICE VALIDATION")
        print("="*60)
        
        services = [
            "zookeeper", "kafka", "clickhouse", "surrealdb",
            "connector-service", "extractor-service", "transformer-service",
            "loader-service", "metadata-service", "detector-service"
        ]
        
        for service in services:
            result = self.check_service(service)
            self.results["services"][service] = result
            status_icon = "✅" if result["running"] else "❌"
            print(f"{status_icon} {service}: {result['status']}")
    
    def validate_kafka_topics(self):
        """Validate all Kafka topics"""
        print("\n" + "="*60)
        print("B) KAFKA TOPIC DIAGNOSTICS")
        print("="*60)
        
        topics = [
            "connection_topic", "schema_topic", "extracted_rows_topic",
            "clean_rows_topic", "load_rows_topic", "metadata_topic"
        ]
        
        for topic in topics:
            result = self.check_kafka_topic(topic)
            self.results["kafka_topics"][topic] = result
            
            if result["exists"]:
                print(f"✅ {topic}: {result['partitions']} partitions, replication={result['replication']}")
            else:
                print(f"❌ {topic}: NOT FOUND - Creating...")
                # Create topic
                code, stdout, stderr = self.run_command(
                    ["docker", "exec", "kafka", "kafka-topics", "--bootstrap-server", "localhost:9092",
                     "--create", "--if-not-exists", "--topic", topic, "--partitions", "1", "--replication-factor", "1"]
                )
                if code == 0:
                    print(f"   ✅ Created {topic}")
                    self.results["fixes"].append(f"Created missing topic: {topic}")
                    # Re-check
                    result = self.check_kafka_topic(topic)
                    self.results["kafka_topics"][topic] = result
                else:
                    print(f"   ❌ Failed to create: {stderr}")
                    self.results["errors"].append(f"Failed to create topic {topic}: {stderr}")
    
    def validate_infrastructure(self):
        """Validate infrastructure components"""
        print("\n" + "="*60)
        print("C) INFRASTRUCTURE VALIDATION")
        print("="*60)
        
        # ClickHouse
        ch_result = self.check_clickhouse()
        self.results["clickhouse"] = ch_result
        if ch_result["connected"]:
            print(f"✅ ClickHouse: Connected to database '{ch_result['database']}'")
            print(f"   Tables: {ch_result['table_count']} ({', '.join(ch_result['tables'][:5])})")
        else:
            print(f"❌ ClickHouse: Connection failed")
        
        # SurrealDB
        surreal_result = self.check_surrealdb()
        self.results["surrealdb"] = surreal_result
        if surreal_result["connected"]:
            print(f"✅ SurrealDB: Connected (NS: {surreal_result['namespace']}, DB: {surreal_result['database']})")
        else:
            print(f"❌ SurrealDB: Connection failed")
    
    def test_pipeline(self):
        """Test full ETL pipeline"""
        print("\n" + "="*60)
        print("D) FULL PIPELINE TEST")
        print("="*60)
        
        # Create test file
        test_file = "test_pipeline_validation.csv"
        with open(test_file, 'w') as f:
            f.write("id,name,age,city,active\n")
            f.write("1,John Doe,25,New York,true\n")
            f.write("2,Jane Smith,30,Los Angeles,false\n")
            f.write("3,Bob Johnson,35,Chicago,true\n")
        
        print(f"📁 Created test file: {test_file}")
        
        # Upload file
        try:
            with open(test_file, 'rb') as f:
                files = {'file': (test_file, f, 'text/csv')}
                response = requests.post(
                    "http://localhost:8001/api/upload/",
                    files=files,
                    timeout=30
                )
            
            if response.status_code == 200:
                print("✅ File uploaded successfully")
                self.results["pipeline_test"]["upload"] = {"status": "success", "response": response.json()}
            else:
                print(f"❌ Upload failed: {response.status_code}")
                self.results["pipeline_test"]["upload"] = {"status": "failed", "code": response.status_code}
                return
        except Exception as e:
            print(f"❌ Upload error: {e}")
            self.results["errors"].append(f"Upload failed: {e}")
            return
        
        # Wait for pipeline to process
        print("⏳ Waiting for pipeline to process (30 seconds)...")
        time.sleep(30)
        
        # Check logs
        print("\n📊 Checking service logs...")
        services_to_check = ["extractor-service", "transformer-service", "loader-service", "metadata-service"]
        for service in services_to_check:
            code, stdout, _ = self.run_command(
                ["docker", "logs", service, "--tail", "20"]
            )
            if stdout:
                # Count key messages
                processed = stdout.count("Processed") + stdout.count("Published") + stdout.count("Loaded")
                errors = stdout.count("ERROR")
                print(f"   {service}: {processed} operations, {errors} errors")
                self.results["pipeline_test"][service] = {
                    "operations": processed,
                    "errors": errors
                }
    
    def generate_report(self):
        """Generate comprehensive health report"""
        print("\n" + "="*60)
        print("E) PIPELINE HEALTH REPORT")
        print("="*60)
        
        # Services status
        running_services = sum(1 for s in self.results["services"].values() if s["running"])
        total_services = len(self.results["services"])
        print(f"\n📦 Services: {running_services}/{total_services} running")
        
        # Topics status
        existing_topics = sum(1 for t in self.results["kafka_topics"].values() if t["exists"])
        total_topics = len(self.results["kafka_topics"])
        print(f"📨 Kafka Topics: {existing_topics}/{total_topics} exist")
        
        # Infrastructure
        ch_ok = self.results.get("clickhouse", {}).get("connected", False)
        surreal_ok = self.results.get("surrealdb", {}).get("connected", False)
        print(f"🗄️  ClickHouse: {'✅' if ch_ok else '❌'}")
        print(f"🗄️  SurrealDB: {'✅' if surreal_ok else '❌'}")
        
        # Errors
        if self.results["errors"]:
            print(f"\n⚠️  Errors Found: {len(self.results['errors'])}")
            for error in self.results["errors"][:5]:
                print(f"   - {error}")
        else:
            print("\n✅ No errors found")
        
        # Fixes
        if self.results["fixes"]:
            print(f"\n🔧 Fixes Applied: {len(self.results['fixes'])}")
            for fix in self.results["fixes"]:
                print(f"   ✅ {fix}")
        
        # Save report
        report_file = "pipeline_health_report.json"
        with open(report_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\n📄 Full report saved to: {report_file}")
        
        return self.results

def main():
    """Main validation function"""
    print("="*60)
    print("ETL PIPELINE COMPREHENSIVE VALIDATION")
    print("="*60)
    print(f"Started at: {datetime.utcnow().isoformat()}")
    
    validator = PipelineValidator()
    
    # Run all validations
    validator.validate_all_services()
    validator.validate_kafka_topics()
    validator.validate_infrastructure()
    validator.test_pipeline()
    results = validator.generate_report()
    
    print("\n" + "="*60)
    print("VALIDATION COMPLETE")
    print("="*60)
    
    return results

if __name__ == "__main__":
    main()

