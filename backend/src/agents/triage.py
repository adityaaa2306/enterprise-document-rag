import logging
from typing import List, Literal
from pydantic import BaseModel, Field

# unstructured is the core of our "Triage" (visual chunking) agent
from unstructured.partition.auto import partition
from unstructured.documents.elements import Element, Title, NarrativeText, Table, ListItem

log = logging.getLogger(__name__)

# --- Chunk Data Model ---
# This is our standardized "smart chunk" format.
# Every piece of the document will be converted into one of these.
class Chunk(BaseModel):
    """
    A single "smart chunk" of the document.
    It contains the text content and its semantic type.
    """
    id: str = Field(..., description="The unique ID for this chunk (e.g., doc_XYZ_chunk_0)")
    document_id: str = Field(..., description="The ID of the document this chunk belongs to")
    chunk_index: int = Field(..., description="The order of this chunk in the document")
    type: Literal["Title", "Text", "Table", "List", "Other"] = Field(..., description="The semantic type of the chunk")
    content: str = Field(..., description="The actual text content of the chunk")

# --- Triage Agent Function ---

def triage_document(file_path: str, file_type: str, strategy: str) -> List[Chunk]:
    """
    This is the main "Triage" or "Visual Chunking" function.
    
    It uses the `unstructured` library to partition a document
    based on its *visual layout* (if 'hi_res') or text (if 'fast').
    
    It returns a structured list of Chunk objects.
    """
    log.info(f"Triaging document: {file_path} (Strategy: {strategy})")
    
    try:
        # This is the core call to the 'unstructured' library.
        # It runs the AI models to parse the document.
        elements = partition(filename=file_path, content_type=file_type, strategy=strategy)
    except Exception as e:
        log.error(f"Failed to partition document {file_path}: {e}")
        # Fallback to "fast" strategy if "hi_res" fails
        if strategy == "hi_res":
            log.warning("Falling back to 'fast' triage strategy...")
            try:
                elements = partition(filename=file_path, content_type=file_type, strategy="fast")
            except Exception as e2:
                log.error(f"Fallback 'fast' strategy also failed: {e2}")
                return []
        else:
            return []

    chunks: List[Chunk] = []
    document_id = file_path.split("/")[-1].split("_")[0] # Get the doc_id from the filename
    chunk_index = 0

    # This loop converts the 'unstructured' elements into our simple 'Chunk' format
    for el in elements:
        chunk_type: Literal["Title", "Text", "Table", "List", "Other"] = "Other"
        content = ""
        
        if isinstance(el, Title):
            chunk_type = "Title"
            content = el.text

        elif isinstance(el, NarrativeText):
            chunk_type = "Text"
            content = el.text

        elif isinstance(el, ListItem):
            chunk_type = "List"
            content = el.text # unstructured handles list formatting
            
        elif isinstance(el, Table):
            chunk_type = "Table"
            # For tables, we get the HTML representation!
            # This is *far* better for an LLM to understand than raw text.
            # We also add the text in case the HTML is complex.
            content = f"--- TABLE START ---\n"
            content += f"HTML:\n{el.metadata.text_as_html}\n\n"
            content += f"TEXT:\n{el.text}\n"
            content += f"--- TABLE END ---"
        
        # We only add the chunk if it has meaningful content
        if content.strip(): # .strip() removes whitespace
            chunk_id = f"{document_id}_chunk_{chunk_index}"
            
            chunks.append(
                Chunk(
                    id=chunk_id,
                    document_id=document_id,
                    chunk_index=chunk_index,
                    type=chunk_type,
                    content=content
                )
            )
            chunk_index += 1

    log.info(f"Triage complete. Extracted {len(chunks)} smart chunks.")
    return chunks