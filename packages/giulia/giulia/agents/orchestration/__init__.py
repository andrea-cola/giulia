"""Inter-agent orchestration: activity logging and human-in-the-loop approvals.

Sub-modules
-----------
activity_log  — insert-only ``agent_task_log`` writes/reads
approvals     — append-only ``workflow_approvals`` CRUD (ApprovalStatus, create, resolve)
starlette     — Starlette HTTP routes mounted on each agent server
adk           — ADK tool factory (``make_request_human_approval_tool``)
"""

from giulia.agents.orchestration.activity_log import (
    get_invocation,
    get_process,
    get_workflow_by_session,
    log_event,
)
from giulia.agents.orchestration.adk import (
    make_check_approval_tool,
    make_request_email_review_tool,
    make_request_human_approval_tool,
    make_request_selection_approval_tool,
)
from giulia.agents.orchestration.approvals import (
    ApprovalStatus,
    WorkflowApprovalCreate,
    WorkflowApprovalRecord,
    create_approval,
    get_latest_approval,
    resolve_approval,
)
from giulia.agents.orchestration.starlette import (
    WORKFLOW_APPROVALS_PATH,
    mount_workflow_approvals,
)

__all__ = [
    # activity_log
    "log_event",
    "get_invocation",
    "get_workflow_by_session",
    "get_process",
    # approvals
    "ApprovalStatus",
    "WorkflowApprovalCreate",
    "WorkflowApprovalRecord",
    "create_approval",
    "get_latest_approval",
    "resolve_approval",
    # starlette
    "mount_workflow_approvals",
    "WORKFLOW_APPROVALS_PATH",
    # adk
    "make_request_human_approval_tool",
    "make_request_email_review_tool",
    "make_request_selection_approval_tool",
    "make_check_approval_tool",
]
