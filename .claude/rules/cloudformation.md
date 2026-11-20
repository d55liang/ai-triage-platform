---
paths:
  - "infra/**"
---

# AWS CloudFormation rules

Rationale is in `DESIGN.md` §18, *AWS queues and IAM*. Creating, changing or deleting a stack is an AWS change and needs explicit approval (`aws.md`).

## Templates

- One YAML template per stack in `infra/`, named after what it holds (`triage-queues.yaml`). Short-form intrinsics (`!Ref`, `!GetAtt`, `!Sub`).
- No account IDs, ARNs, URLs or hosts in a template. Build ARNs with `!Sub` and the pseudo parameters (`${AWS::Partition}`, `${AWS::Region}`, `${AWS::AccountId}`); take anything account-specific, such as the IAM user name, as a parameter without a default.
- Comment a setting whose value isn't obvious or whose CloudFormation default differs from the console's (`VisibilityTimeout` defaults to 30 s).
- Two resources that reference each other's `!GetAtt` are a circular dependency. Break it by building one ARN with `!Sub` from the known name.
- Expose what the app needs in `.env` as `Outputs`, not by looking it up by hand.
- Queues must match `elasticmq.conf` (names, visibility timeout, redrive). Change both together (`sqs.md`).

## IAM in templates

- Least privilege: list each action and scope it to the stack's own resource ARNs (`!GetAtt <Queue>.Arn`). No `*` actions or resources.
- One `Sid` per consumer of the permissions (relay, workers, test), with a comment saying who it's for.
- A fixed `ManagedPolicyName` needs `CAPABILITY_NAMED_IAM` at deploy time. State it in the deploy command.

## Deploying

- Deploy from AWS CloudShell, signed in as root; the `daniel` user can't create SQS or IAM resources, by design.
- Always review first: `aws cloudformation deploy ... --no-execute-changeset`, read the change set (`describe-change-set`), and execute it only after the change list is what was planned. A `Replace` on a named queue deletes it with its messages.
- Never edit stack resources in the console or CLI afterwards; change the template and deploy again, or the stack drifts.
- Verify afterwards from the laptop as `daniel`, read-only (`GetQueueUrl`, `GetQueueAttributes`).
- Remove everything with `aws cloudformation delete-stack`. A deleted queue's name can't be reused for 60 s.
