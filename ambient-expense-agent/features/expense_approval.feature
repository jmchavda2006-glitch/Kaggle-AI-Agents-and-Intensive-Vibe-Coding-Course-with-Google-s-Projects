Feature: Ambient Expense Parsing and Approval
  As an enterprise system
  I want to submit expense details in natural language
  So that the system can automatically parse, triage, and enforce zero-trust access control policy decisions

  Scenario: Expense under threshold is approved automatically
    Given the expense submission is "I want to submit an expense of Rs 5,000 for team lunch"
    And the user is authorized with a valid role "employee"
    When the expense is processed by the agent workflow
    Then the parsed amount should be 5000.0
    And the parsed currency should be "INR"
    And the parsed description should be "lunch"
    And the workflow execution should succeed without raising permission errors

  Scenario: Expense over threshold requires manual approval
    Given the expense submission is "I want to submit an expense of Rs 15,000 for client dinner"
    And the user is authorized with a valid role "employee"
    When the expense is processed by the agent workflow
    Then the parsed amount should be 15000.0
    And the system should interrupt for "manual_approval" review

  Scenario: Unauthorized user request is rejected by Policy Server
    Given the expense submission is "I want to submit an expense of Rs 2,000 for taxi"
    And the user is unauthorized with role "guest"
    When the expense is processed by the agent workflow
    Then the request should be blocked by the policy server with a permission error
