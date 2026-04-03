import os
import json
import csv
import uvicorn
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import Dict, Any, List
from pydantic import BaseModel

app = FastAPI(title="Maya Dashboard API")

# Enable CORS for the React frontend (Vite)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = "data"
STATS_FILE = os.path.join(DATA_DIR, "stats.json")
LEADS_FILE = os.path.join(DATA_DIR, "leads_audit.jsonl")
SENTIMENT_FILE = os.path.join(DATA_DIR, "sentiment_log.csv")

os.makedirs(DATA_DIR, exist_ok=True)

# --- Persistence Helpers ---

def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    return {
        "total_leads": 0, "total_calls": 0, "total_chats": 0, 
        "leads_by_maya": 0, "conversions": 0, "last_updated": datetime.now().isoformat()
    }

def save_stats(stats):
    stats["last_updated"] = datetime.now().isoformat()
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)

def append_lead(lead: Dict[str, Any]):
    with open(LEADS_FILE, "a") as f:
        f.write(json.dumps(lead) + "\n")

# --- API Models ---

class StatIncrement(BaseModel):
    key: str
    amount: int = 1

class LeadAudit(BaseModel):
    session_id: str
    record_id: str
    name: str
    email: str
    phone: str
    product: str
    summary: str

# --- Endpoints ---

@app.get("/api/dashboard")
async def get_dashboard_stats():
    """Aggregated metrics for the home overview."""
    return load_stats()

@app.post("/api/stats/increment")
async def increment_stat(update: StatIncrement):
    """Pushed by Maya when a call ends or interaction occurs."""
    stats = load_stats()
    if update.key in stats:
        stats[update.key] += update.amount
        save_stats(stats)
        return {"status": "success", "new_value": stats[update.key]}
    raise HTTPException(status_code=400, detail="Invalid stat key")

@app.post("/api/leads")
async def create_lead_audit(lead: LeadAudit):
    """Pushed by Maya when a lead is successfully created in Salesforce."""
    lead_dict = lead.dict()
    lead_dict["timestamp"] = datetime.now().isoformat()
    append_lead(lead_dict)
    
    # Auto-increment lead counters
    stats = load_stats()
    stats["total_leads"] += 1
    stats["leads_by_maya"] += 1
    save_stats(stats)
    
    return {"status": "success", "record_id": lead.record_id}

@app.get("/api/leads-history")
async def get_leads_history():
    """Returns the full leads audit log as a JSON list."""
    if not os.path.exists(LEADS_FILE):
        return []
    leads = []
    with open(LEADS_FILE, "r") as f:
        for line in f:
            if line.strip():
                leads.append(json.loads(line))
    return leads

@app.get("/api/feedback")
async def get_feedback():
    """Returns the parsed sentiment CSV as a JSON list."""
    if not os.path.exists(SENTIMENT_FILE):
        return []
    feedback = []
    try:
        with open(SENTIMENT_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Add score for frontend charting
                score = 0
                if row.get("OverallSentiment") == 'POSITIVE': score = 1
                if row.get("OverallSentiment") == 'NEGATIVE': score = -1
                feedback.append({**row, "score": score})
    except Exception as e:
        print(f"Error reading feedback CSV: {e}")
    return feedback

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
