import os
import re
import json
import asyncio
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import ADK core components
from google.adk import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

# Import our workflow and schemas
try:
    from agent import root_agent
    from ambient_expense_agent.policy_plugin import ZeroTrustPolicyPlugin
except ImportError:
    from ambient_expense_agent.agent import root_agent
    from policy_plugin import ZeroTrustPolicyPlugin

app = FastAPI(title="Ambient Expense Web Interface Console")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active runners dictionary to support resuming paused sessions
active_runners: Dict[str, Runner] = {}
active_session_services: Dict[str, InMemorySessionService] = {}

# Map transaction_id -> asyncio.Queue for streaming cloud-hosted events asynchronously
cloud_transaction_queues: Dict[str, asyncio.Queue] = {}

class SubmitRequest(BaseModel):
    query: str
    user: str = "test_user"
    role: str = "employee"

class ResumeRequest(BaseModel):
    session_id: str
    approved: bool
    reason: str = ""
    user: str = "manager_user"
    role: str = "manager"

# Helper to serialize event data
def serialize_event(event_type: str, data: Any) -> str:
    return f"data: {json.dumps({'event': event_type, 'data': data})}\n\n"

# ----------------------------------------------------
# CLOUD WORKSPACE ASYNC SIMULATION ENGINE
# ----------------------------------------------------
async def run_cloud_agent_background(transaction_id: str, query: str, user: str, role: str):
    queue = cloud_transaction_queues[transaction_id]
    
    # Store credentials in env context for the Zero-Trust Policy Plugin
    os.environ["SEC_USER"] = user
    os.environ["SEC_ROLE"] = role

    # Initialize Runner
    session_service = InMemorySessionService()
    runner = Runner(
        node=root_agent,
        session_service=session_service,
        plugins=[ZeroTrustPolicyPlugin()]
    )
    
    active_runners[transaction_id] = runner
    active_session_services[transaction_id] = session_service

    try:
        # Simulate initial PubSub ingestion delay & log
        await queue.put({
            "event": "cloud_gateway_received", 
            "data": {
                "transaction_id": transaction_id, 
                "status": "Queued", 
                "gateway": "api-gateway.cloud.internal", 
                "topic": "projects/expense-production/topics/transaction-ingest"
            }
        })
        await asyncio.sleep(1.2) # queue lag simulation

        session = await session_service.create_session(
            app_name=runner.app_name,
            user_id=user
        )

        await queue.put({"event": "policy_check_start", "data": {"user": user, "role": role}})
        
        new_message = types.Content(
            role="user",
            parts=[types.Part(text=query)]
        )

        suspended = False
        async for event in runner.run_async(
            user_id=user,
            session_id=session.id,
            new_message=new_message
        ):
            # 1. Output parser details
            if event.output and event.node_info and "expense_parser" in event.node_info.path:
                await queue.put({"event": "parsed_details", "data": event.output})

            # 2. Capture policy passed log
            if event.node_info and "expense_parser" in event.node_info.path:
                await queue.put({"event": "policy_check_passed", "data": {"user": user, "role": role}})

            # 3. Check for interruption/manual approval request
            if event.long_running_tool_ids and "manual_approval" in event.long_running_tool_ids:
                suspended = True
                interrupt_msg = "Manual approval required"
                if event.content and event.content.parts:
                    fc = event.content.parts[0].function_call
                    if fc and fc.args:
                        interrupt_msg = fc.args.get("message", interrupt_msg)
                
                await queue.put({"event": "workflow_suspended", "data": {
                    "session_id": transaction_id,
                    "interrupt_id": "manual_approval",
                    "message": interrupt_msg,
                    "parsed_expense": event.output
                }})
                break

            # 4. Stream final output node
            if event.node_info and "print_result" in event.node_info.path:
                await queue.put({"event": "workflow_completed", "data": event.output})

        if not suspended:
            # Clean up
            active_runners.pop(transaction_id, None)
            active_session_services.pop(transaction_id, None)
            await queue.put(None) # end of stream marker

    except Exception as e:
        await queue.put({"event": "workflow_failed", "data": {"error": str(e)}})
        active_runners.pop(transaction_id, None)
        active_session_services.pop(transaction_id, None)
        await queue.put(None)

async def run_cloud_agent_resume_background(transaction_id: str, approved: bool, reason: str, user: str, role: str):
    queue = cloud_transaction_queues.get(transaction_id)
    if not queue:
        return
    
    runner = active_runners[transaction_id]
    
    try:
        await queue.put({"event": "policy_check_start", "data": {"user": user, "role": role, "action": "resume_workflow"}})
        await asyncio.sleep(0.5)

        new_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        name="adk_request_input",
                        id="manual_approval",
                        response={"approved": approved, "reason": reason}
                    )
                )
            ]
        )

        async for event in runner.run_async(
            user_id=user,
            session_id=transaction_id,
            new_message=new_message
        ):
            if event.node_info and "triage_guardrail" in event.node_info.path:
                await queue.put({"event": "policy_check_passed", "data": {"user": user, "role": role, "action": "resume_workflow"}})

            if event.node_info and "print_result" in event.node_info.path:
                await queue.put({"event": "workflow_completed", "data": event.output})

        active_runners.pop(transaction_id, None)
        active_session_services.pop(transaction_id, None)
        await queue.put(None)
        
    except Exception as e:
        await queue.put({"event": "workflow_failed", "data": {"error": str(e)}})
        active_runners.pop(transaction_id, None)
        active_session_services.pop(transaction_id, None)
        await queue.put(None)

# ----------------------------------------------------
# REST API GATEWAYS
# ----------------------------------------------------
@app.post("/api/cloud-gateway")
async def cloud_gateway_submit(req: SubmitRequest):
    """
    Mock Cloud Gateway: Accepts payload asynchronously and queues it to the 
    ingestion pipeline. Returns 202 Accepted.
    """
    transaction_id = f"tx-{uuid_str()}"
    queue = asyncio.Queue()
    cloud_transaction_queues[transaction_id] = queue
    
    # Spawn background cloud runner task
    asyncio.create_task(
        run_cloud_agent_background(transaction_id, req.query, req.user, req.role)
    )
    
    return {
        "status": "Accepted",
        "transaction_id": transaction_id,
        "gateway_routing": "http://api-gateway.cloud.internal/routing/v1",
        "ingestion_method": "PubSub Push Queue",
        "tracking_url": f"/api/cloud-gateway/stream/{transaction_id}"
    }

@app.get("/api/cloud-gateway/stream/{transaction_id}")
async def cloud_gateway_stream(transaction_id: str):
    """
    Status Tracking stream for asynchronous cloud transaction executions.
    """
    if transaction_id not in cloud_transaction_queues:
        raise HTTPException(status_code=404, detail="Transaction tracking stream expired or not found.")
    
    queue = cloud_transaction_queues[transaction_id]
    
    async def event_generator():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield serialize_event(item["event"], item["data"])
        except Exception as e:
            yield serialize_event("workflow_failed", {"error": str(e)})
        finally:
            cloud_transaction_queues.pop(transaction_id, None)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Fallback Legacy endpoints
@app.post("/api/submit")
async def submit_workflow(req: SubmitRequest):
    # Simply route synchronous requests to our cloud-gateway format locally
    transaction_id = f"tx-{uuid_str()}"
    queue = asyncio.Queue()
    cloud_transaction_queues[transaction_id] = queue
    asyncio.create_task(run_cloud_agent_background(transaction_id, req.query, req.user, req.role))
    
    async def event_generator():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield serialize_event(item["event"], item["data"])
        except Exception as e:
            yield serialize_event("workflow_failed", {"error": str(e)})
        finally:
            cloud_transaction_queues.pop(transaction_id, None)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/resume")
async def resume_workflow(req: ResumeRequest):
    session_id = req.session_id
    if session_id not in active_runners:
        raise HTTPException(status_code=404, detail="Active session not found or already completed.")
    
    # Process cloud gateway resumption asynchronously
    if session_id in cloud_transaction_queues:
        asyncio.create_task(
            run_cloud_agent_resume_background(session_id, req.approved, req.reason, req.user, req.role)
        )
        return {
            "status": "Resumed",
            "session_id": session_id,
            "message": "Asynchronous resumption successfully triggered."
        }
    
    # Synced backup response fallback
    runner = active_runners[session_id]
    os.environ["SEC_USER"] = req.user
    os.environ["SEC_ROLE"] = req.role

    async def event_generator():
        try:
            yield serialize_event("policy_check_start", {"user": req.user, "role": req.role, "action": "resume_workflow"})
            new_message = types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            name="adk_request_input",
                            id="manual_approval",
                            response={"approved": req.approved, "reason": req.reason}
                        )
                    )
                ]
            )
            async for event in runner.run_async(user_id=req.user, session_id=session_id, new_message=new_message):
                if event.node_info and "triage_guardrail" in event.node_info.path:
                    yield serialize_event("policy_check_passed", {"user": req.user, "role": req.role, "action": "resume_workflow"})
                if event.node_info and "print_result" in event.node_info.path:
                    yield serialize_event("workflow_completed", event.output)
            active_runners.pop(session_id, None)
            active_session_services.pop(session_id, None)
        except Exception as e:
            yield serialize_event("workflow_failed", {"error": str(e)})
            active_runners.pop(session_id, None)
            active_session_services.pop(session_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/config")
async def get_config():
    pdp_url = os.environ.get("POLICY_SERVER_URL", "http://127.0.0.1:8181/v1/data/expense/allow")
    mock_enabled = os.environ.get("POLICY_SERVER_MOCK", "false").lower() == "true"
    return {
        "pdp_url": pdp_url,
        "mock_enabled": mock_enabled,
        "gateway_url": "http://api-gateway.cloud.internal",
        "ingress_mode": "Asynchronous (PubSub Push Ingestion)"
    }

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    if not os.path.exists(index_path):
        index_path = "index.html"
    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return html_content

def uuid_str() -> str:
    import uuid
    return str(uuid.uuid4())[:8]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5000)
