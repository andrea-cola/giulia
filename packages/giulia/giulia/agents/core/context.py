from contextvars import ContextVar

# Stable Datwave process_id for the current execution context.
# Set at the entry point (inbound delegation handler), read by services.
current_process_id: ContextVar[str] = ContextVar("current_process_id")

# Stable Datwave session_id (the _dw_session_id propagated across every agent hop).
# Set by run_inbound_job_with_runner so tools can read it without relying on
# session state being flushed by the time a tool call fires.
current_session_id: ContextVar[str | None] = ContextVar(
    "current_session_id", default=None
)

# Set to True by dispatch_to_human so the delegation handler knows the agent's
# turn ended while waiting for a HITL approval (not a true completion).
# This causes the final "completed" log row to carry target_agent_id="human"
# instead of None, making it distinguishable from a genuine task completion.
current_hitl_pending: ContextVar[bool] = ContextVar(
    "current_hitl_pending", default=False
)

# Process-level HITL signal table.
#
# ContextVar mutations made inside an ADK tool are isolated to the child async
# context that ADK creates for each runner.run_async() turn (asyncio.create_task
# copies the context; writes into the copy are invisible to the parent coroutine).
# A plain dict keyed by receiver_inv_id is immune to that isolation: both the
# parent handler and any descendant coroutine share the same dict object in
# memory, so a write in the tool is immediately visible to the handler.
#
# Lifecycle: run_inbound_job_with_runner inserts False before the turn and
# deletes the entry after reading it; dispatch_to_human flips it to True.
_hitl_pending_by_inv: dict[str, bool] = {}
