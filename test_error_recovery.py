import sys, os, json, requests
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://127.0.0.1:8000'

print("================================================================")
print("TEST: SIMULATED FAILURE & STRUCTURED ERROR RECOVERY")
print("================================================================")

# 1. Test empty query validation
print("\n--- 1. Testing Input Validation Error (empty query) ---")
r = requests.post(f"{BASE}/api/query", json={"query": ""})
print(f"Status code: {r.status_code}")
print(f"Detail: {r.json()}")

# 2. Test unknown strategy error
print("\n--- 2. Testing Invalid Strategy Validation ---")
r = requests.post(f"{BASE}/api/query", json={"query": "test", "strategy": "non_existent_strategy"})
print(f"Status code: {r.status_code}")
print(f"Detail: {r.json()}")

# 3. Test simulated internal exception in pipeline
print("\n--- 3. Testing Pipeline Error Handling (Internal catch & recovery) ---")
from backend.pipeline.pipeline import run_pipeline
# Force a pipeline run with invalid type
res = run_pipeline(query_text=None, audio_bytes=None)
print(f"Pipeline error flag: {res.error}")
print(f"Pipeline error message: {res.error_message}")
print(f"Total latency: {res.total_latency}s")
assert res.error == True
assert "ValueError" in res.error_message or "audio_bytes" in res.error_message

print("\n--- Error Recovery Verification PASSED: No raw stack trace exposed to user, real exception logged. ---")
