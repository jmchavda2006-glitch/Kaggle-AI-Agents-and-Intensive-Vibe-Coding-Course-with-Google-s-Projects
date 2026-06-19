import os
import asyncio
from behave import given, when, then

# Import the workflow and schemas
try:
    from agent import root_agent
except ImportError:
    from ambient_expense_agent.agent import root_agent

# Ensure mock policy validation is enabled by default for tests if server is not running
if "POLICY_SERVER_URL" not in os.environ:
    os.environ["POLICY_SERVER_MOCK"] = "true"

@given('the expense submission is "{submission_text}"')
def step_given_submission(context, submission_text):
    context.submission_text = submission_text

@given('the user is authorized with a valid role "{role}"')
def step_given_authorized_role(context, role):
    os.environ["SEC_ROLE"] = role
    os.environ["SEC_USER"] = "test_user_authorized"

@given('the user is unauthorized with role "{role}"')
def step_given_unauthorized_role(context, role):
    os.environ["SEC_ROLE"] = role
    os.environ["SEC_USER"] = "test_user_unauthorized"

@when('the expense is processed by the agent workflow')
def step_when_processed(context):
    from google.adk import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.genai import types

    try:
        from ambient_expense_agent.policy_plugin import ZeroTrustPolicyPlugin
    except ImportError:
        from policy_plugin import ZeroTrustPolicyPlugin

    # Initialize runner with the zero-trust policy plugin
    session_service = InMemorySessionService()
    runner = Runner(
        node=root_agent,
        session_service=session_service,
        plugins=[ZeroTrustPolicyPlugin()]
    )

    context.workflow_error = None
    context.workflow_interrupted = False
    context.interrupt_message = None
    context.parsed_details = None

    async def run_workflow():
        session = await session_service.create_session(
            app_name=runner.app_name,
            user_id="test_user"
        )
        msg = types.Content(
            role="user",
            parts=[types.Part(text=context.submission_text)]
        )
        try:
            async for event in runner.run_async(
                user_id="test_user",
                session_id=session.id,
                new_message=msg
            ):
                # 1. Track parsed expense details if emitted
                if event.output and isinstance(event.output, dict):
                    context.parsed_details = event.output
                
                # 2. Track manual approval interruption
                if event.long_running_tool_ids and "manual_approval" in event.long_running_tool_ids:
                    context.workflow_interrupted = True
                    # Safely extract message from function call if present
                    if event.content and event.content.parts:
                        fc = event.content.parts[0].function_call
                        if fc and fc.args:
                            context.interrupt_message = fc.args.get("message")
        except Exception as e:
            context.workflow_error = e
        finally:
            await runner.close()

    # Run the async loop
    asyncio.run(run_workflow())

@then('the parsed amount should be {amount:f}')
def step_then_amount(context, amount):
    assert context.workflow_error is None, f"Workflow failed with error: {context.workflow_error}"
    assert context.parsed_details is not None, "No expense details parsed in workflow."
    parsed_amount = float(context.parsed_details.get("amount", 0))
    assert abs(parsed_amount - amount) < 0.01, f"Expected amount {amount}, got {parsed_amount}"

@then('the parsed currency should be "{currency}"')
def step_then_currency(context, currency):
    assert context.workflow_error is None, f"Workflow failed with error: {context.workflow_error}"
    assert context.parsed_details is not None, "No expense details parsed in workflow."
    parsed_currency = context.parsed_details.get("currency", "")
    # Standardize common currency terms for assertion
    if currency == "INR" and parsed_currency in ["Rs", "INR", "rupees"]:
        pass
    else:
        assert parsed_currency.lower() == currency.lower(), f"Expected currency {currency}, got {parsed_currency}"

@then('the parsed description should be "{description}"')
def step_then_description(context, description):
    assert context.workflow_error is None, f"Workflow failed with error: {context.workflow_error}"
    assert context.parsed_details is not None, "No expense details parsed in workflow."
    parsed_desc = context.parsed_details.get("description", "")
    assert description.lower() in parsed_desc.lower(), f"Expected description containing {description}, got {parsed_desc}"

@then('the workflow execution should succeed without raising permission errors')
def step_then_succeed(context):
    assert context.workflow_error is None, f"Workflow failed unexpectedly with error: {context.workflow_error}"

@then('the system should interrupt for "{interrupt_id}" review')
def step_then_interrupt(context, interrupt_id):
    assert context.workflow_error is None, f"Workflow failed with error: {context.workflow_error}"
    assert context.workflow_interrupted, f"Workflow was not interrupted for {interrupt_id}."

@then('the request should be blocked by the policy server with a permission error')
def step_then_blocked(context):
    assert context.workflow_error is not None, "Workflow completed successfully, but should have been blocked by Policy Server."
    err_str = str(context.workflow_error)
    assert "Access Denied by Policy Server" in err_str, f"Unexpected error message: {err_str}"
