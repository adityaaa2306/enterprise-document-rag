"""
Check the latest summary in the database to see if it contains CNN/military content
"""
import sqlite3

conn = sqlite3.connect('agentic_db.sqlite')
cursor = conn.cursor()

cursor.execute('SELECT id, summary, saved_at FROM documents ORDER BY saved_at DESC LIMIT 1')
row = cursor.fetchone()

if row:
    doc_id, summary, saved_at = row
    print(f"Document ID: {doc_id}")
    print(f"Saved At: {saved_at}")
    print(f"\n{'='*80}")
    print("FULL SUMMARY:")
    print(f"{'='*80}")
    print(summary)
    print(f"\n{'='*80}")
    
    # Check for problematic content
    if "CNN" in summary or "military" in summary.lower() or "Navy" in summary or "Gulf War" in summary:
        print("\n⚠️  WARNING: Summary contains problematic content!")
    else:
        print("\n✅ Summary looks clean!")
else:
    print("No documents found in database")

conn.close()
