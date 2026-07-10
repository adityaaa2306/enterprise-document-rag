"""
Script to clear the database and remove any cached summaries.
This will ensure that the new prompt changes take effect.
"""
import os
import sqlite3

# Path to the database
db_path = "agentic_db.sqlite"

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Clear all documents
    cursor.execute("DELETE FROM documents")
    conn.commit()
    
    print(f"✅ Cleared all documents from the database")
    print(f"   Deleted {cursor.rowcount} rows")
    
    conn.close()
else:
    print(f"❌ Database file not found: {db_path}")
