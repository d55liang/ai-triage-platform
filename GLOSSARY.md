# AI Triage Platform

A platform where users describe what they need in natural language to an AI agent, which turns each need into a Ticket; Triage then maps each Ticket to one predefined Workflow Definition.

## Language

### Intake

**Conversation**:
The natural-language exchange between a User and the Intake Agent from which Tickets are drawn. One Conversation can produce several Tickets.
_Avoid_: Chat, session, thread

**Intake Agent**:
The AI agent the User talks to in a Conversation. It turns each distinct request into a Ticket, acts on existing Tickets (for example cancelling one) at the User's request, and asks the User for missing Required Inputs. It does not triage.
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
- **CANCELLED**: the User withdrew the Ticket. Cancelling a TRIAGED Ticket also cancels its Workflow Run; a Ticket whose Run is COMPLETED or FAILED can't be cancelled.

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

**Admin**:
A person who authors and maintains Workflow Definitions.
_Avoid_: Operator, author, owner

**Workflow Definition**:
A predefined kind of work that Triage can select, described by its description, Sample Requests, ordered Steps, Required Inputs and Confidence Threshold.
_Avoid_: Workflow, template, playbook

**Disabled**:
Said of a Workflow Definition that Triage does not select until an Admin enables it again. Its existing Workflow Runs continue. Workflow Definitions are never deleted.
_Avoid_: Retired, paused, archived, deleted, inactive

**Sample Request**:
An example of how a User might phrase a need that a Workflow Definition handles, shown to Triage to improve matching.
_Avoid_: Example, sample body, utterance

**Workflow Definition Version**:
One unchangeable revision of a Workflow Definition. Every edit creates a new version, and a Workflow Run stays on the version it started from.
_Avoid_: Revision, draft

**Step**:
One ordered instruction in a Workflow Definition, saying what to do and written for an LLM or a person to follow.
_Avoid_: Task, action, stage

**Required Input**:
A named value a Workflow Run needs before it can start.
_Avoid_: Field, parameter, slot

**Workflow Run**:
A single execution instance of one Workflow Definition Version for one Ticket. It waits until its Required Inputs are supplied. A Ticket has at most one Workflow Run, created by Triage.
_Avoid_: Workflow, execution, job, run instance

**Workflow Run Status**:
Where a Workflow Run is in its own lifecycle, which starts when Triage creates it.
- **AWAITING_INPUTS**: at least one Required Input is still missing.
- **READY**: every Required Input is supplied, and it is waiting to be carried out. A Run whose version has no Required Inputs starts here.
- **RUNNING**: its Steps are being carried out.
- **COMPLETED**: every Step is done.
- **FAILED**: it could not finish.
- **CANCELLED**: withdrawn because the User cancelled its Ticket.

_Avoid_: PENDING, DONE, ACTIVE
