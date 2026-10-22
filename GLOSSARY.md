# AI Triage Platform

A platform where users describe what they need in natural language to an AI agent, which turns each need into a Ticket and maps it to one predefined Workflow Definition.

## Language

### Intake

**Conversation**:
The natural-language exchange between a User and the AI agent from which Tickets are drawn. One Conversation can produce several Tickets.
_Avoid_: Chat, session, thread

**Ticket**:
A single request extracted from a Conversation, which is triaged to at most one Workflow Definition.
_Avoid_: Issue, case, request, message

**Ticket Status**:
Where a Ticket is in its lifecycle: **CREATED** (not yet triaged) or **TRIAGED** (has a Workflow Run). A deleted Ticket no longer exists; deletion is not a status.
_Avoid_: State

### Triage

**Triage**:
The agent's act of matching a Ticket to a Workflow Definition and creating its Workflow Run, which happens only when the Match Confidence meets that definition's Confidence Threshold. If no definition qualifies, the Ticket stays CREATED and the agent asks clarifying questions; if several qualify, the highest Match Confidence wins.
_Avoid_: Routing, classification, assignment

**Match Confidence**:
How sure the agent is that a Ticket belongs to a particular Workflow Definition.
_Avoid_: Score, probability, certainty

**Confidence Threshold**:
The minimum Match Confidence a Workflow Definition requires before Triage may select it, set higher for workflows with greater consequences.
_Avoid_: Cutoff, minimum score

### Workflows

**Workflow Definition**:
A predefined template describing a kind of work, including its description, ordered steps and Confidence Threshold.
_Avoid_: Workflow, template, playbook

**Workflow Run**:
A single execution instance of one Workflow Definition for one Ticket. A Ticket has at most one active Workflow Run.
_Avoid_: Workflow, execution, job, run instance
