import requests
import io

# Create file from the test CSV
with open('/tmp/test_etl_pipeline.csv', 'rb') as f:
    file_content = f.read()

files = {'file': ('test_etl_pipeline.csv', io.BytesIO(file_content), 'text/csv')}

# Upload via connector-service from inside Docker network
try:
    print("[TEST] Uploading file to trigger ETL pipeline...")
    response = requests.post(
        "http://connector-service:8000/api/upload/",
        files=files,
        timeout=10
    )
    
    print(f"[TEST] Status Code: {response.status_code}")
    print(f"[TEST] Response: {response.json()}")
    
    if response.status_code == 200:
        print("\n✅ [TEST] File upload successful! ETL pipeline should be processing...")
    else:
        print(f"\n❌ [TEST] File upload failed")
        
except Exception as e:
    print(f"[TEST ERROR] {e}")
    import traceback
    traceback.print_exc()

