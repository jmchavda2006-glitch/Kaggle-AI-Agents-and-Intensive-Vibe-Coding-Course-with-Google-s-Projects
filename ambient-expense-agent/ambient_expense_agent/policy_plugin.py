import os
import re
import requests
from typing import Optional, Any
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.genai import types

class ZeroTrustPolicyPlugin(BasePlugin):
    """
    ZeroTrustPolicyPlugin intercepts agent workflow executions to enforce zero-trust
    authorization checks by querying a local Policy Decision Point (PDP) sidecar
    which coordinates with a central Policy Administration Point (PAP) in a hybrid setup.
    """
    def __init__(self, pdp_url: Optional[str] = None):
        super().__init__(name="zero_trust_policy")
        # In a hybrid GKE/Cloud Run deployment, the sidecar is at http://127.0.0.1:8181
        self.pdp_url = pdp_url or os.environ.get("POLICY_SERVER_URL", "http://127.0.0.1:8181/v1/data/expense/allow")

    async def before_run_callback(
        self, *, invocation_context: InvocationContext
    ) -> Optional[types.Content]:
        """
        Enforce Zero-Trust check at the very beginning of the workflow run.
        """
        # Default credentials (fail-closed if missing)
        role = "guest"
        user = "anonymous"
        amount = 0.0
        currency = "INR"

        # 1. Resolve security credentials
        role = os.environ.get("SEC_ROLE", role)
        user = os.environ.get("SEC_USER", user)

        # 2. Extract amount from the user's message safely handling both object lists and structures
        user_msg_text = ""
        if invocation_context.user_content and invocation_context.user_content.parts:
            parts = invocation_context.user_content.parts
            
            # Safely check if parts is returned as a list array structure
            first_part = parts if isinstance(parts, list) and len(parts) > 0 else parts
            
            # Safe checking for both explicit object properties and raw dictionary indices
            if hasattr(first_part, "text"):
                user_msg_text = first_part.text or ""
            elif isinstance(first_part, dict):
                user_msg_text = first_part.get("text", "")
            elif isinstance(first_part, str):
                user_msg_text = first_part
        
        if user_msg_text:
            text_clean = user_msg_text.replace(",", "")
            amount_match = re.search(r'\b\d+(?:\.\d+)?\b', text_clean)
            if amount_match:
                amount = float(amount_match.group(0))
            
            currency_match = re.search(r'(INR|USD|EUR|rupees|rupee|rs\.|rs|₹|\$)', text_clean, re.IGNORECASE)
            if currency_match:
                currency = currency_match.group(0)

        # 3. Evaluate Authorization against PDP
        allow, decision_id, reason = self._query_pdp(user, role, amount, currency)

        if not allow:
            raise PermissionError(
                f"Access Denied by Policy Server. Decision: {decision_id}. Reason: {reason}"
            )
            
        print(f"[POLICY PASSED - RUN] Decision: {decision_id} | User: {user} | Role: {role} | Allowed: {allow}")
        return None

    async def before_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        """
        Enforce Zero-Trust check at the agent level for multi-agent configurations.
        """
        role = "guest"
        user = "anonymous"
        amount = 0.0
        currency = "INR"

        # Access variables directly from callback_context instead of looking for a nested context attribute
        if callback_context and hasattr(callback_context, "variables"):
            role = callback_context.variables.get("security_role", role)
            user = callback_context.variables.get("security_user", user)
        else:
            role = os.environ.get("SEC_ROLE", role)
            user = os.environ.get("SEC_USER", user)

        node_input = getattr(callback_context, "inputs", {})
        if node_input:
            if hasattr(node_input, "amount"):
                amount = node_input.amount
                currency = node_input.currency
            elif isinstance(node_input, dict):
                amount = node_input.get("amount", 0.0)
                currency = node_input.get("currency", "INR")

        allow, decision_id, reason = self._query_pdp(user, role, amount, currency)

        if not allow:
            raise PermissionError(
                f"Access Denied by Policy Server. Decision: {decision_id}. Reason: {reason}"
            )
            
        print(f"[POLICY PASSED - AGENT] Decision: {decision_id} | User: {user} | Role: {role} | Allowed: {allow}")
        return None

    def _query_pdp(self, user: str, role: str, amount: float, currency: str) -> tuple[bool, str, str]:
        payload = {
            "input": {
                "user": user,
                "role": role,
                "action": "submit_expense",
                "amount": amount,
                "currency": currency
            }
        }

        mock_mode = os.environ.get("POLICY_SERVER_MOCK", "false").lower() == "true"
        
        if mock_mode:
            role_lower = role.lower()
            if role_lower in ["admin", "manager"]:
                allow = True
                reason = "Mock: Admin/Manager always allowed"
            elif role_lower == "employee":
                if amount <= 50000.0:
                    allow = True
                    reason = f"Mock: Employee within limit ({amount} <= 50,000)"
                else:
                    allow = False
                    reason = f"Mock: Employee amount {amount} exceeds 50,000"
            else:
                allow = False
                reason = f"Mock: Role {role} unauthorized"
            decision_id = "mock-offline-decision"
        else:
            try:
                response = requests.post(self.pdp_url, json=payload, timeout=2.0)
                if response.status_code == 200:
                    res_data = response.json().get("result", {})
                    allow = res_data.get("allow", False)
                    reason = res_data.get("reason", "Default Deny")
                    decision_id = res_data.get("decision_id", "unknown")
                else:
                    allow = False
                    reason = f"Policy Server returned HTTP {response.status_code}"
                    decision_id = "error"
            except Exception as e:
                allow = False
                reason = f"Policy Server PDP connection failed: {str(e)}"
                decision_id = "unreachable"
                
        return allow, decision_id, reason
