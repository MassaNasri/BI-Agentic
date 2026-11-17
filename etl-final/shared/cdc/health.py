"""Container readiness checks a recent successful control-plane poll."""
import os
import time
import urllib.request


def ready():
    with urllib.request.urlopen(f"http://127.0.0.1:{int(os.getenv('CDC_METRICS_PORT', '9110'))}/metrics", timeout=2) as response:
        lines=response.read(131072).decode().splitlines()
    heartbeat=[float(line.rsplit(' ',1)[1]) for line in lines if line.startswith('biavora_cdc_worker_heartbeat_seconds{')]
    return bool(heartbeat) and time.time()-max(heartbeat)<60


if __name__=='__main__':
    raise SystemExit(0 if ready() else 1)
