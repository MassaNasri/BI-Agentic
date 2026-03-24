import requests
import json
import os
import os

print("ALL ENV KEYS:")
for k in os.environ.keys():
    if "OPEN" in k or "ROUTER" in k:
        print(k, "=", os.environ.get(k))

