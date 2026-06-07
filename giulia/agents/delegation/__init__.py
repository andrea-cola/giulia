"""Fire-and-forget inter-agent delegation queue.

Public surface:
  - ``mount_inbound_delegation`` — wire the /internal/delegation route + worker
  - ``start_inbound_delegation_worker`` / ``stop_inbound_delegation_worker``
  - ``submit_inbound_delegation`` — sender-side HTTP POST helper
  - ``make_delegate_registered_agent_tool`` — ADK tool factory (fire-and-forget)
  - ``InboundDelegationJob`` — shared job dataclass
  - ``InboundDelegationBackend`` — backend protocol
"""

from giulia.agents.delegation.backends import InboundDelegationBackend  # noqa: F401
from giulia.agents.delegation.handler import (  # noqa: F401
    INBOUND_DELEGATION_PATH,
    INBOUND_DELEGATION_SECRET_HEADER,
    get_inbound_delegation_backend,
    get_inbound_delegation_queue,
    inbound_delegation_lifespan,
    inbound_delegation_secret,
    mount_inbound_delegation,
    resolve_delegation_target_base_url,
    run_inbound_job_with_runner,
    start_inbound_delegation_worker,
    stop_inbound_delegation_worker,
    submit_inbound_delegation,
)
from giulia.agents.delegation.tools import (
    make_delegate_registered_agent_tool,  # noqa: F401
)
from giulia.agents.delegation.types import InboundDelegationJob  # noqa: F401

__all__ = [
    "INBOUND_DELEGATION_PATH",
    "INBOUND_DELEGATION_SECRET_HEADER",
    "InboundDelegationBackend",
    "InboundDelegationJob",
    "get_inbound_delegation_backend",
    "get_inbound_delegation_queue",
    "inbound_delegation_lifespan",
    "inbound_delegation_secret",
    "make_delegate_registered_agent_tool",
    "mount_inbound_delegation",
    "resolve_delegation_target_base_url",
    "run_inbound_job_with_runner",
    "start_inbound_delegation_worker",
    "stop_inbound_delegation_worker",
    "submit_inbound_delegation",
]
