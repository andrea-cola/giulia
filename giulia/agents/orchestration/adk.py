"""ADK tool factory for human-in-the-loop approvals.

Usage in an agent module::

    from giulia.agents.orchestration.adk import make_request_human_approval_tool

    request_human_approval = make_request_human_approval_tool(
        target_agent_id="urn:agent:giulia:private:pr-analyzer"
    )
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from google.adk.tools.tool_context import ToolContext

from giulia.agents.orchestration.approvals import (
    dispatch_to_human,
    get_latest_approval,
)
from giulia.logging import logger


@dataclass
class DatwaveContext:
    invocation_id: str
    session_id: str
    user_id: str
    app_name: str | None
    process_id: str | None
    state: dict


def get_giulia_context(
    tool_context: ToolContext, default_user_id: str = "user"
) -> DatwaveContext:
    """Extract Datwave correlation IDs from an ADK ToolContext.

    Handles fallbacks from ContextVars -> Session State -> ADK Defaults.
    """
    from giulia.agents.core.context import current_process_id, current_session_id  # noqa: PLC0415, I001

    try:
        inv = tool_context._invocation_context  # noqa: SLF001
        invocation_id = inv.invocation_id
        user_id = inv.session.user_id or default_user_id
        app_name = inv.app_name
        state = inv.session.state or {}
    except AttributeError:
        # Fallback for contexts missing expected ADK attributes
        return DatwaveContext(
            invocation_id="unknown",
            session_id=current_session_id.get() or "unknown",
            user_id=default_user_id,
            app_name=None,
            process_id=current_process_id.get(None),
            state={},
        )

    session_id = (
        current_session_id.get() or state.get("_dw_session_id") or inv.session.id
    )
    # Resolve process_id from ContextVar first, then session state
    ctx_process_id = current_process_id.get(None)
    state_process_id = state.get("process_id")
    process_id = ctx_process_id or state_process_id or None

    # Filter out "default_process" sentinel - treat it as if process_id wasn't set
    if process_id == "default_process":
        logger.critical("process_id is not set")
        raise ValueError("process_id is not set")

    return DatwaveContext(
        invocation_id=str(invocation_id),
        session_id=str(session_id),
        user_id=str(user_id),
        app_name=app_name,
        process_id=process_id,
        state=state,
    )


def make_check_approval_tool() -> Callable[..., Awaitable[str]]:
    """Return an ADK tool that reads the current status of a pending approval."""

    async def check_human_approval_status(
        tool_context: ToolContext,  # noqa: ARG001
        *,
        approval_id: str,
    ) -> str:
        """Read the current status of a HITL approval.

        Args:
            approval_id: the ID returned by request_human_approval.
        """
        record = await get_latest_approval(approval_id)
        if record is None:
            return json.dumps(
                {
                    "status": "not_found",
                    "approval_id": approval_id,
                    "message": f"No approval record found for '{approval_id}'.",
                }
            )
        return json.dumps(
            {
                "status": record.status.value,
                "approval_id": record.approval_id,
                "response_text": record.response_text,
                "message": f"Approval '{approval_id}' is currently '{record.status.value}'.",
            }
        )

    return check_human_approval_status


def make_request_selection_approval_tool(
    *,
    target_agent_id: str,
    approval_id_prefix: str,
    tool_name: str = "request_selection_approval",
    tool_description: str | None = None,
    next_step: str | None = None,
    form_title: str = "Selection Required",
    form_description: str = "Please select the items to proceed with.",
    field_id: str = "selected_items",
    field_label: str = "Items",
) -> Callable[..., Awaitable[str]]:
    """Return an ADK tool that asks a human to select items from a checklist.

    Args:
        target_agent_id: URN of the agent that owns this approval gate.
        approval_id_prefix: Prefix for the approval ID.
        tool_name: Name of the tool.
        tool_description: Description of the tool.
        next_step: Instruction for the agent after selection.
        form_title: Title of the form in the UI.
        form_description: Description of the form in the UI.
        field_id: ID of the checklist field.
        field_label: Label of the checklist field.
    """

    async def request_selection_approval(
        tool_context: ToolContext,
        *,
        options: list[dict[str, str]],
        prompt_summary: str,
        approval_key: str | None = None,
        assignee: str = "procurement_manager",
    ) -> str:
        """Ask a human to select items from a list before continuing.

        Args:
            options: List of objects with 'label' and 'value' for the checklist.
            prompt_summary: Summary of the request.
            approval_key: Unique key for stable ID.
            assignee: Who should perform the selection.
        """
        ctx = get_giulia_context(tool_context)
        key = (approval_key or "").strip()
        approval_id = f"{approval_id_prefix}_{key}" if key else approval_id_prefix

        form_schema = {
            "type": "form",
            "title": form_title,
            "description": form_description,
            "fields": [
                {
                    "id": field_id,
                    "type": "checklist",
                    "label": field_label,
                    "required": True,
                    "options": options,
                }
            ],
        }

        record = await dispatch_to_human(
            invocation_id=ctx.invocation_id,
            session_id=ctx.session_id,
            source_agent_id=str(ctx.state.get("_dw_source_agent_id") or "").strip()
            or target_agent_id,
            target_agent_id=target_agent_id,
            assignee=assignee,
            prompt_summary=prompt_summary,
            user_id=ctx.user_id,
            process_id=ctx.process_id,
            app_name=ctx.app_name,
            approval_id=approval_id,
            next_step=next_step,
            form_schema=form_schema,
        )

        if record is None:
            return json.dumps(
                {"status": "error", "message": "DB error creating approval"}
            )

        return json.dumps(
            {
                "status": "awaiting_approval",
                "approval_id": record.approval_id,
                "message": "Selection requested. STOP and wait.",
            }
        )

    request_selection_approval.__name__ = tool_name
    if tool_description:
        request_selection_approval.__doc__ = tool_description

    return request_selection_approval


def make_request_email_review_tool(
    *,
    target_agent_id: str,
    tool_name: str = "request_email_review_approval",
    tool_description: str | None = None,
) -> Callable[..., Awaitable[str]]:
    """Return an ADK tool that shows an email draft to the user for review and editing.

    The tool presents a form with 'to', 'subject', and 'body' fields. The agent
    should stop processing after calling this tool and wait for the user to
    approve or modify the draft.

    Args:
        target_agent_id: URN of the agent that owns this approval gate.
        tool_name: Override the function name exposed to the LLM.
        tool_description: Override the tool docstring shown to the LLM.
    """

    async def request_email_review_approval(
        tool_context: ToolContext,
        *,
        to: str,
        subject: str,
        body: str,
        assignee: str = "procurement_manager",
    ) -> str:
        """Show the drafted email to the user for review and editing before sending.

        Args:
            to: Recipient email address.
            subject: Email subject.
            body: Full email body.
            assignee: Who should review the email.
        """
        ctx = get_giulia_context(tool_context)
        # Use a stable but unique ID for this email review
        recipient_slug = to.replace("@", "_at_").replace(".", "_")
        approval_id = f"email_review_{recipient_slug}_{ctx.session_id[:8]}"

        form_schema = {
            "type": "form",
            "title": "Review Email Draft",
            "description": "Please review and edit the email content before it is delivered.",
            "fields": [
                {
                    "id": "to",
                    "type": "text",
                    "label": "Recipient (To)",
                    "required": True,
                    "options": [{"value": to, "label": to, "default": True}],
                },
                {
                    "id": "subject",
                    "type": "text",
                    "label": "Subject",
                    "required": True,
                    "options": [{"value": subject, "label": subject, "default": True}],
                },
                {
                    "id": "body",
                    "type": "textarea",
                    "label": "Body",
                    "required": True,
                    "options": [{"value": body, "label": body, "default": True}],
                },
            ],
        }

        record = await dispatch_to_human(
            invocation_id=ctx.invocation_id,
            session_id=ctx.session_id,
            source_agent_id=str(ctx.state.get("_dw_source_agent_id") or "").strip()
            or target_agent_id,
            target_agent_id=target_agent_id,
            assignee=assignee,
            prompt_summary=f"Review draft email to {to}",
            user_id=ctx.user_id,
            process_id=ctx.process_id,
            app_name=ctx.app_name,
            approval_id=approval_id,
            next_step=(
                "The email review has been decided. "
                "If APPROVED: the form_data contains the final 'to', 'subject', and 'body'. "
                "Execute the next logic (e.g., call send_email or a delegation tool) with these values. "
                "If REJECTED: respond 'Email delivery cancelled by user.' and stop."
            ),
            form_schema=form_schema,
        )

        if record is None:
            return json.dumps(
                {"status": "error", "message": "DB error creating approval"}
            )

        return json.dumps(
            {
                "status": "awaiting_approval",
                "approval_id": record.approval_id,
                "message": f"Email draft for {to} sent for human review. STOP and wait.",
            }
        )

    request_email_review_approval.__name__ = tool_name
    if tool_description:
        request_email_review_approval.__doc__ = tool_description

    return request_email_review_approval


def make_request_form_approval_tool(
    *,
    target_agent_id: str,
    approval_id_prefix: str,
    form_schema: dict,
    tool_name: str = "request_form_approval",
    tool_description: str | None = None,
    next_step: str | None = None,
) -> Callable[..., Awaitable[str]]:
    """Return an ADK tool that asks a human to fill out a fixed form.

    Args:
        target_agent_id: URN of the agent that owns this approval gate.
        approval_id_prefix: Prefix for the approval ID.
        form_schema: Fixed JSON schema for the form.
        tool_name: Name of the tool.
        tool_description: Description of the tool.
        next_step: Instruction for the agent after submission.
    """

    async def request_form_approval(
        tool_context: ToolContext,
        *,
        prompt_summary: str,
        approval_key: str | None = None,
        assignee: str = "procurement_manager",
    ) -> str:
        """Ask a human to complete a form before continuing.

        Args:
            prompt_summary: Summary of the request.
            approval_key: Unique key for stable ID.
            assignee: Who should perform the action.
        """
        ctx = get_giulia_context(tool_context)
        key = (approval_key or "").strip()
        approval_id = f"{approval_id_prefix}_{key}" if key else approval_id_prefix

        record = await dispatch_to_human(
            invocation_id=ctx.invocation_id,
            session_id=ctx.session_id,
            source_agent_id=str(ctx.state.get("_dw_source_agent_id") or "").strip()
            or target_agent_id,
            target_agent_id=target_agent_id,
            assignee=assignee,
            prompt_summary=prompt_summary,
            user_id=ctx.user_id,
            process_id=ctx.process_id,
            app_name=ctx.app_name,
            approval_id=approval_id,
            next_step=next_step,
            form_schema=form_schema,
        )

        if record is None:
            return json.dumps(
                {"status": "error", "message": "DB error creating approval"}
            )

        return json.dumps(
            {
                "status": "awaiting_approval",
                "approval_id": record.approval_id,
                "message": "Form submission requested. STOP and wait.",
            }
        )

    request_form_approval.__name__ = tool_name
    if tool_description:
        request_form_approval.__doc__ = tool_description

    return request_form_approval


def make_request_human_approval_tool(
    *,
    target_agent_id: str,
    approval_id_prefix: str | None = None,
    tool_name: str = "request_human_approval",
    tool_description: str | None = None,
    next_step: str | None = None,
) -> Callable[..., Awaitable[str]]:
    """Return an ADK tool that opens a human approval gate and returns immediately.

    The tool writes a ``pending`` approval record to Cloud SQL and returns a
    JSON payload with the ``approval_id``.  The agent should stop processing
    after calling this tool and wait for the human to respond via the API.

    Args:
        target_agent_id: URN of the agent that owns this approval gate.
        approval_id_prefix: When set, generates a stable ID as ``{prefix}_{key}``
            where ``key`` is provided by the LLM at call time. Useful for pipelines
            where downstream scripts need predictable IDs (e.g. ``buyer_assignment``
            yields ``buyer_assignment_PR-2026-0014``). When ``None``, a random UUID
            is used (safe for simple agents with no external polling).
        tool_name: Override the function name exposed to the LLM.
        tool_description: Override the tool docstring shown to the LLM.
        next_step: Instruction injected verbatim into the HITL resume message so
            the agent knows exactly which action to perform after the human decision.
            Example: "Call invoke_pr_processor to create the purchase order draft."
    """

    async def request_human_approval(
        tool_context: ToolContext,
        *,
        assignee: str,
        prompt_summary: str,
        approval_key: str | None = None,
        form_schema: dict | None = None,
    ) -> str:
        """Ask a human to approve or reject before continuing.

        Args:
            assignee: Role or user that should respond (e.g. "procurement_manager").
            prompt_summary: Plain-language description of what needs approval.
            approval_key: Unique key appended to the prefix (e.g. the PR code).
                Required when the tool was created with an ``approval_id_prefix``.
            form_schema: Optional JSON schema defining form fields for structured input.
                If provided, the UI renders a dynamic form instead of free text.
                Structure: {"type": "form", "title": "...", "fields": [...]}
                Supported field types: text, textarea, select, radio, checklist, number, date.
                Field structure: {"id": "field_id", "type": "...", "label": "...",
                    "options": [{"value": "...", "label": "...", "default": true/false}],
                    "required": true/false, "placeholder": "..."}.
        """
        ctx = get_giulia_context(tool_context)

        if approval_id_prefix is not None:
            key = (approval_key or "").strip()
            approval_id: str | None = (
                f"{approval_id_prefix}_{key}" if key else approval_id_prefix
            )
        else:
            approval_id = None  # dispatch_to_human will generate a UUID

        record = await dispatch_to_human(
            invocation_id=ctx.invocation_id,
            session_id=ctx.session_id,
            source_agent_id=str(ctx.state.get("_dw_source_agent_id") or "").strip()
            or target_agent_id,
            target_agent_id=target_agent_id,
            assignee=assignee,
            prompt_summary=prompt_summary,
            user_id=ctx.user_id,
            process_id=ctx.process_id,
            app_name=ctx.app_name,
            approval_id=approval_id,
            next_step=next_step,
            form_schema=form_schema or {},
        )
        if record is None:
            return json.dumps(
                {"status": "error", "message": "DB error creating approval"}
            )

        return json.dumps(
            {
                "status": "awaiting_approval",
                "approval_id": record.approval_id,
                "message": "Human approval requested. Stop processing and wait.",
            }
        )

    request_human_approval.__name__ = tool_name
    if tool_description:
        request_human_approval.__doc__ = tool_description

    return request_human_approval
