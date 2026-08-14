# Dataset Notes: ai4bharat/MSMARCO-XI

This document provides details on the schema and properties of the `ai4bharat/MSMARCO-XI` dataset subset used for the **HH Goa Voice Radar** project.

## Schema Details

Each record in the dataset is a dictionary representing a question-answering task instance, containing the following fields:

*   **`query_id`** (`int`): Unique identifier for the query.
*   **`query`** (`str`): The translated query in Hindi (the target Indic language).
*   **`Eng_Query`** (`str`): The original English query.
*   **`Answer`** (`str`): The translated human-generated answer in Hindi.
*   **`Eng_Answer`** (`str`): The original English human-generated answer.
*   **`query_type`** (`str`): The type of query (e.g., description, entity).
*   **`source_lang`** (`str`): Source language code (`"eng_Latn"`).
*   **`target_lang`** (`str`): Target language code (`"hin_Deva"`).
*   **`meta`** (`dict`): Generation parameters used by the translation model (e.g., `temperature`, `max_tokens`, `model_name`).
*   **`passages`** (`dict`): Passages associated with the query, containing:
    *   **`English_passages`** (`list` of `str`): The original English passage texts.
    *   **`Translated_passages`** (`list` of `str`): The translated Hindi passage texts.
    *   **`is_selected`** (`list` of `int`): Binary indicators (`0` or `1`) showing if the corresponding passage is relevant (i.e. contains the answer).

## Language & Script
*   **Language**: Hindi (`hi`)
*   **Script**: Devanagari (`Deva`)

## Size Justification & Selection
*   **Source Size**: The full validation split of `ai4bharat/MSMARCO-XI` for Hindi (`validation/hinval.parquet`) is **461.88 MB** containing **97,941** records. The training split (`train/hintrain.parquet`) is **3.72 GB**.
*   **Subset Choice**: We sampled a subset of **100 records** containing **998 passages** (averaging ~10 passages per query).
*   **Justification**: This subset size (100 queries / 998 passages) is large enough to build a representative FAISS vector store index (~1,000 embedded chunks) for testing retrieval and generation, while remaining small enough to run quickly on free-tier compute, require minimal memory, build the index in under 10 seconds, and fit within Git file size limits (~2.2 MB total size) without needing Git LFS.

## Embedding Model Update (Re-indexing)
*   **Update Date**: 2026-08-14
*   **New Embedding Model**: `intfloat/multilingual-e5-small` (dimension: 384)
*   **Reasoning**: The previous embedding model (`all-MiniLM-L6-v2`) is English-only and mapped Devanagari query/passage characters to generic `[UNK]` tokens, destroying semantic retrieval. The new multilingual E5 model is specifically trained for multilingual retrieval and supports Devanagari. We prepend `query: ` and `passage: ` prefixes to queries and documents respectively for optimal semantic alignment.
