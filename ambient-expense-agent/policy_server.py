import os
import uuid
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="Zero-Trust Policy Server (Local PDP)",
    description="Local Policy Decision Point sidecar enforcing zero-trust authorization rules."
)

class PolicyInput(BaseModel):
    user: str = "anonymous"
    role: str = "guest"
    action: str = "submit_expense"
    amount: float = 0.0
    currency: str = "INR"

class PolicyRequest(BaseModel):
    input: PolicyInput

class PolicyResponse(BaseModel):
    result: Dict[str, Any]

# In a hybrid Policy Server layout, local policy engines cache rules and evaluate locally
# for speed and reliability, and periodically sync / log audits to a central server.
CENTRAL_POLICY_ENDPOINT = os.environ.get("CENTRAL_POLICY_ENDPOINT", "http://central-policy-authority.local/api/v1")

@app.post("/v1/data/expense/allow", response_model=PolicyResponse)
def evaluate_policy(request: PolicyRequest):
    inp = request.input
    decision_id = str(uuid.uuid4())
    
    # Zero-Trust Rules:
    # 1. Access is denied by default (Fail-Closed).
    # 2. guest role is always denied.
    # 3. employee role is allowed to submit expenses up to 50,000 INR.
    # 4. manager/admin roles are always allowed.
    
    allow = False
    reason = "Default Deny"
    
    role = inp.role.lower()
    if role in ["admin", "manager"]:
        allow = True
        reason = f"Role '{inp.role}' is always authorized to submit any expense amount."
    elif role == "employee":
        if inp.amount <= 50000.0:
            allow = True
            reason = f"Employee authorized for expense amount {inp.amount} within limit (50,000)."
        else:
            allow = False
            reason = f"Expense amount {inp.amount} exceeds maximum employee limit of 50,000."
    elif role == "guest":
        allow = False
        reason = "Guest role is not authorized to submit expenses."
    else:
        allow = False
        reason = f"Unknown role '{inp.role}' is blocked by Zero-Trust policy."

    # In a hybrid design, write the local audit log and simulate forwarding it to the central authority
    print(f"[AUDIT LOG] Decision ID: {decision_id} | User: {inp.user} | Role: {inp.role} | Amount: {inp.amount} | Allowed: {allow} | Reason: {reason} | Synced: True")
    
    return PolicyResponse(
        result={
            "allow": allow,
            "decision_id": decision_id,
            "reason": reason,
            "layout": "hybrid-policy-server-layout",
            "central_synced": True
        }
    )

if __name__ == "__main__":
    import uvicorn
    # Listen on localhost port 8181 to serve as the local sidecar/PDP
    uvicorn.run(app, host="127.0.0.1", port=8181)
