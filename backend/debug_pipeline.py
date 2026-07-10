
import os
import sys
import logging
from sqlalchemy import text

# Setup paths
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from src.core.config import settings
from src.agents import triage, models
from src.memory import storage

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
log = logging.getLogger("debug_pipeline")

def debug_run():
    print("\n--- 1. Checking Database Configuration ---")
    print(f"DATABASE_URL: {settings.DATABASE_URL}")
    print(f"VECTOR_DB_PATH: {settings.VECTOR_DB_PATH}")
    
    # Check absolute path of sqlite file
    if "sqlite:///" in settings.DATABASE_URL:
        rel_path = settings.DATABASE_URL.replace("sqlite:///", "")
        abs_path = os.path.abspath(rel_path)
        print(f"SQLite File Path (Abs): {abs_path}")
        if os.path.exists(abs_path):
            print("✅ SQLite file exists.")
        else:
            print("❌ SQLite file does NOT exist yet (will be created).")

    print("\n--- 2. Initializing System & Models ---")
    storage.init_database()
    models.load_all_models()
    
    print("\n--- 3. Running Triage (Input Analysis) ---")
    file_path = "backend/test.pdf"
    if not os.path.exists(file_path):
        print(f"❌ Test file not found at {file_path}. Please ensure backend/test.pdf exists.")
        return

    # Run Triage
    chunks = triage.triage_document(file_path, "application/pdf", settings.TRIAGE_STRATEGY)
    print(f"Generated {len(chunks)} chunks.")
    
    if not chunks:
        print("❌ Triage failed to extract any chunks! This is likely the root cause.")
        return

    # Validating Chunk integrity
    print(f"DEBUG: First Chunk Content Preview (first 200 chars):\n{chunks[0].content[:200]}")
    if len(chunks[0].content.strip()) == 0:
        print("❌ Warning: First chunk is empty/whitespace!")

    print("\n--- 4. Verifying Storage (DB Check) ---")
    doc_id = "debug_doc_001"
    
    # Clear old debug data
    storage.delete_document_data(doc_id)
    storage.delete_chunks(doc_id)
    
    # Store
    print(f"Storing chunks for {doc_id}...")
    storage.store_chunks(doc_id, chunks)
    
    # Verify count via SQL
    db = storage.DBSessionLocal()
    try:
        count = db.execute(text(f"SELECT COUNT(*) FROM chunks WHERE document_id = '{doc_id}'")).scalar()
        print(f"✅ DB Row Count for '{doc_id}': {count}")
        if count == len(chunks):
            print("✅ Storage count matches input count.")
        else:
            print(f"❌ Mismatch! Input: {len(chunks)}, Stored: {count}")
    except Exception as e:
        print(f"❌ DB Query Failed: {e}")
    finally:
        db.close()

    print("\n--- 5. Running Summarization Pipeline ---")
    summaries = []
    
    # Light Summarizer
    model_usage = {"light": 0, "medium": 0, "large": 0}
    state = {"model_usage_chars": model_usage} # minimal state mock
    
    print("Running Light Summarizer on first 3 chunks...")
    for i, chunk in enumerate(chunks[:3]):
        print(f"Chunk {i} Length: {len(chunk.content)}")
        summary = models.run_light_summarizer(chunk.content, state)
        summaries.append(summary)
        print(f"-> Summary {i}: {summary}")
        
    if not summaries:
        print("❌ No summaries generated.")
        return

    # Compile Summary
    print("\nRunning Final Compiler (Large Model) on these summaries...")
    combined = "\n\n".join(summaries)
    final_summary = models.run_large_model_compile(combined, state)
    
    print(f"\n✅ FINAL SUMMARY:\n{final_summary}")
    
    if "Error" in final_summary or not final_summary.strip():
        print("❌ Final summary generation failed/empty.")
    else:
        print("✅ Pipeline finished successfully.")

    print("\n--- 6. Verifying RAG Answer Generation (Groq) ---")
    query = "What is the main topic of this document?"
    # We already have 'chunks' from Triage
    # In real app, we search db, but here we can just pass the chunks to test the model generation
    # purely. Or we can search. Let's search to be sure.
    
    print(f"Querying: '{query}'")
    found_chunks = storage.search_similar_chunks(query, doc_id)
    if not found_chunks:
        print("❌ No chunks found via search (Search broken?)")
    else:
        print(f"✅ Found {len(found_chunks)} relevant chunks.")
        
        answer, sources = models.run_large_model_rag(query, found_chunks)
        print(f"✅ RAG Answer:\n{answer}")
        
        if "Error" in answer or "failed" in answer.lower():
             print("❌ RAG Generation Failed.")
        else:
             print("✅ RAG Generation Works.")

if __name__ == "__main__":
    debug_run()
