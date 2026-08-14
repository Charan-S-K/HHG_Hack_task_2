import json
import os
from backend.config import SUBSET_PATH

def load_subset_data():
    """
    Loads and returns the sampled subset of the MSMARCO-XI dataset.
    """
    if not os.path.exists(SUBSET_PATH):
        raise FileNotFoundError(f"Subset file not found at {SUBSET_PATH}. Please run the sampling script first.")
        
    records = []
    with open(SUBSET_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records
