import os
import asyncio
from pydantic import BaseModel, Field
from google.adk import Agent, Workflow, Context
from google.adk.workflow import START, node
from google.adk.events import RequestInput

# Define the structured output schema for the expense parser
class ExpenseDetail(BaseModel):
    amount: float = Field(description="The numeric amount of the expense.")
    currency: str = Field(description="The currency of the expense (e.g. INR, USD, EUR, rupees, dollars, etc.).")
    description: str = Field(description="The category or description of the expense.")

# Check if a valid Gemini API key is present
api_key = os.environ.get("GEMINI_API_KEY", "")
has_real_key = api_key and api_key != "your-gemini-api-key-here"

if has_real_key:
    # Define the parsing agent node
    expense_parser = Agent(
        name="expense_parser",
        model="gemini-2.5-flash",
        instruction=(
            "You are an ambient expense parsing agent. "
            "Your task is to analyze the input text and extract exactly three data points:\n"
            "1. amount: the numeric value of the expense.\n"
            "2. currency: the currency of the expense (e.g. INR, USD, rupees).\n"
            "3. description: the category or description of what was purchased.\n"
            "Output the result conforming strictly to the specified schema."
        ),
        output_schema=ExpenseDetail
    )
else:
    # Fallback to local python node when no API key is provided (e.g. during local tests)
    @node
    def expense_parser(node_input: str) -> ExpenseDetail:
        import re
        text = node_input.replace(",", "")
        
        # Extract amount
        amount_match = re.search(r'\b\d+(?:\.\d+)?\b', text)
        amount = float(amount_match.group(0)) if amount_match else 0.0
        
        # Extract currency
        currency_match = re.search(r'(INR|USD|EUR|rupees|rupee|rs\.|rs|₹|\$)', text, re.IGNORECASE)
        currency = currency_match.group(0) if currency_match else "INR"
        
        # Extract description
        description = "expense submission"
        for kw in ["dinner", "lunch", "coffee", "travel", "flight", "taxi", "hotel"]:
            if kw in text.lower():
                description = kw
                break
                
        return ExpenseDetail(amount=amount, currency=currency, description=description)

# Define manual approval schema
class ManualApprovalResponse(BaseModel):
    approved: bool = Field(description="Whether the expense is approved (True) or rejected (False).")
    reason: str = Field(default="", description="Reason for the decision.")

# Define the triage guardrail node
@node(rerun_on_resume=True)
def triage_guardrail(ctx: Context, node_input: ExpenseDetail) -> ExpenseDetail:
    # Check if this is a resumption with manual approval response
    approval = ctx.resume_inputs.get("manual_approval")
    if approval is not None:
        if isinstance(approval, dict):
            approved = approval.get("approved", False)
            reason = approval.get("reason", "")
        else:
            approved = getattr(approval, "approved", False)
            reason = getattr(approval, "reason", "")
            
        if not approved:
            raise ValueError(f"Expense rejected by reviewer. Reason: {reason}")
        
        return node_input

    # Check if the currency is INR/rupees and amount > 10,000
    currency = node_input.currency.upper()
    is_inr = currency in ["INR", "₹", "RUPEES", "RUPEE", "RS", "RS."]
    
    if is_inr and node_input.amount > 10000:
        return RequestInput(
            interrupt_id="manual_approval",
            message=f"Expense of {node_input.amount} {node_input.currency} (exceeds ₹10,000 limit) requires manual approval.",
            response_schema=ManualApprovalResponse
        )
        
    return node_input

# Define the print node to display the structured result
@node
def print_result(node_input: ExpenseDetail) -> ExpenseDetail:
    print(f"Amount: {node_input.amount}")
    print(f"Currency: {node_input.currency}")
    print(f"Category/Description: {node_input.description}")
    return node_input

# Define the root agent workflow
root_agent = Workflow(
    name="ambient_expense_workflow",
    edges=[
        (START, expense_parser, triage_guardrail, print_result)
    ]
)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        query = sys.argv[1]
        
        # Programmatic runner using in-memory session service
        from google.adk import Runner
        from google.adk.sessions.in_memory_session_service import InMemorySessionService
        from google.genai import types
        try:
            from ambient_expense_agent.policy_plugin import ZeroTrustPolicyPlugin
        except ImportError:
            from policy_plugin import ZeroTrustPolicyPlugin
        
        async def run_query():
            session_service = InMemorySessionService()
            runner = Runner(
                node=root_agent,
                session_service=session_service,
                plugins=[ZeroTrustPolicyPlugin()]
            )
            session = await session_service.create_session(
                app_name=runner.app_name,
                user_id="test_user"
            )
            new_message = types.Content(role="user", parts=[types.Part(text=query)])
            async for _ in runner.run_async(
                user_id="test_user",
                session_id=session.id,
                new_message=new_message
            ):
                pass
            await runner.close()
            
        asyncio.run(run_query())
    else:
        print("Ambient Expense Agent initialized. Use `adk run` or `python agent.py <query>` to execute or interact with this agent.")
