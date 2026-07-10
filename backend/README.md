# Green-Agentic Backend API 

This is the complete, production-ready backend for the Green-Agentic Document Intelligence Platform. It is designed to run 100% locally on a laptop with *no* Docker or database server required.

It uses:
- **FastAPI** for the API
- **LangGraph** for the agentic "brain" (the Orchestrator)
- **Capability Requirement Engine (CRE)** for capability-first model routing
- **NVIDIA NIM** for Light / Medium / Heavy LLMs, embeddings, and reranking
- A local **NLI + Quality Validation Agent** for confidence-based escalation
- Carbon intensity as an **optimization weight** (never overrides capability floors)


## How to Run This

1.  **Install System Dependencies (for `unstructured`):**
    * This is for visual document analysis.
    * **On Mac:** `brew install tesseract poppler`
    * **On Ubuntu/Linux:** `sudo apt-get install tesseract-ocr poppler-utils`
    * **On Windows:** You must install [Tesseract](https://github.com/tesseract-ocr/tessdoc) and [Poppler for Windows](https://github.com/oschwartz10612/poppler-windows/releases/) and add them to your system's PATH.

2.  **Install Python Dependencies:**
    * Create a virtual environment: `python -m venv .venv`
    * Activate it: `source .venv/bin/activate` (or `.venv\Scripts\activate` on Windows)
    * Install requirements from the `requirements.txt` file:
        ```bash
        pip install -r requirements.txt
        ```

3.  **Set Up Environment:**
    * Copy the example `.env` file: `cp .env.example .env`
    * **CRITICAL:** Open the `.env` file and add your **`NVIDIA_API_KEY`** from [build.nvidia.com](https://build.nvidia.com/settings/api-keys).

4.  **Run the FastAPI Server:**
    * From within the `backend/` directory:
    ```bash
    uvicorn src.api.main:app --reload --port 8000
    ```
    * Your API is now running at `http://127.0.0.1:8000`.
    * You can see the auto-generated documentation at `http://127.0.0.1:8000/docs`.

## Model stack (NVIDIA NIM) + CRE routing

| Tier | Primary | Fallbacks | When selected |
|------|---------|-----------|---------------|
| Light | Llama 3.2 3B | Gemma 2 2B | CRS < 0.35 (no domain floor) |
| Medium | Gemma 4 31B | Ministral 14B | 0.35 ≤ CRS < 0.65 |
| Heavy | Llama 3.3 70B | GPT OSS 120B → Qwen3.5 122B | CRS ≥ 0.65 or medical floor |

Pipeline: Triage → Feature Extraction → CRE (CRS) → Intelligent Router → Generate → QVA → escalate +1 tier if needed → Store + telemetry.

Eco / Balanced / Performance only change utility weights; they never bypass domain floors or skip summarization.
