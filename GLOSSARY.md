# AI Triage Platform

A platform where users describe what they need in natural language to an AI agent, which turns each need into a Ticket; Triage then maps each Ticket to one predefined Workflow Definition.

## Language

### Intake

**Conversation**:
The natural-language exchange between a User and the Intake Agent from which Tickets are drawn. One Conversation can produce several Tickets.
_Avoid_: Chat, session, thread

**Intake Agent**:
The AI agent the User talks to in a Conversation. It turns each distinct request into a Ticket, and acts on existing Tickets (for example cancelling one) at the User's request. It does not triage.
_Avoid_: Bot, assistant, "the agent" (ambiguous once Triage runs separately)

**Ticket**:
A single request extracted from a Conversation, which is triaged to at most one Workflow Definition.
_Avoid_: Issue, case, request, message

**Ticket Status**:
Where a Ticket is in its Triage lifecycle. Only the system changes it, except that a User may cancel.
- **CREATED**: saved, not yet handed off for Triage.
- **QUEUED**: waiting for Triage.
- **TRIAGING**: Triage is in progress.
- **TRIAGED**: a Workflow Definition was selected and its Workflow Run created. The Ticket's lifecycle ends here; the work's progress is the Workflow Run's own status.
- **UNMATCHED**: Triage finished, but no Workflow Definition met its Confidence Threshold.
- **FAILED**: Triage could not finish, even after retries.
- **CANCELLED**: the User withdrew the Ticket. Cancelling a TRIAGED Ticket also cancels its active Workflow Run.

A deleted Ticket no longer exists; deletion is not a status.
_Avoid_: State, PENDING, COMPLETED, CLOSED

### Triage

**Triage**:
Matching a Ticket to a Workflow Definition and creating its Workflow Run, which happens only when the Match Confidence meets that definition's Confidence Threshold. If no definition qualifies, the Ticket becomes UNMATCHED and the Intake Agent asks the User clarifying questions; if several qualify, the highest Match Confidence wins.
_Avoid_: Routing, classification, assignment

**Match Confidence**:
How sure Triage is that a Ticket belongs to a particular Workflow Definition.
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
