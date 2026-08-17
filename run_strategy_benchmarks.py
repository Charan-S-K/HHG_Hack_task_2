import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8')

from backend.benchmark.harness import run_benchmark
from backend.config import BENCHMARK_RESULTS_PATH

strategies = ["fixed", "sentence", "metadata", "hybrid"]
results = {}

print("================================================================")
print("RUNNING BENCHMARK COMPARISON ACROSS ALL 4 CHUNKING STRATEGIES")
print("================================================================")

for strat in strategies:
    print(f"\n--- Benchmarking Strategy: {strat} (10 queries, seed=42) ---")
    t0 = time.time()
    rep = run_benchmark(strategy=strat, max_queries=10)
    elapsed = time.time() - t0
    
    overall = rep.get("overall", {}).get("excl_stt_latency_s", {})
    stages = rep.get("per_stage_s", {})
    
    results[strat] = {
        "overall": overall,
        "stages": stages,
        "bottleneck": rep.get("bottleneck_stage"),
        "meets_target": rep.get("meets_200ms_target"),
        "elapsed_s": round(elapsed, 2)
    }
    
    print(f"[{strat}] P50: {overall.get('p50')}s | P70: {overall.get('p70')}s | P100: {overall.get('p100')}s | Avg: {overall.get('avg')}s")
    print(f"[{strat}] Bottleneck: {rep.get('bottleneck_stage')}")
    print(f"[{strat}] Elapsed: {round(elapsed, 2)}s")

print("\n\n================================================================")
print("FINAL BENCHMARK COMPARISON TABLE")
print("================================================================")
print(json.dumps(results, indent=2))

with open("data/multi_strategy_benchmark.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print("\nSaved comparison to data/multi_strategy_benchmark.json")
