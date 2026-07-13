"""
Request cleaning for Cursor/Vertex AI compatibility.

Shared by the HTTP proxy and the FastAPI app. Removes orphaned
tool_result blocks, tool_choice, and other params/headers that Vertex AI rejects.
Also trims overly long conversations to stay within model context limits.
"""

import json
import logging

# Parameters to remove from requests (incompatible with Vertex AI).
# Note: thinking / reasoning_effort / extended_thinking / budget_tokens are
# intentionally NOT blocked here — app.py injects the correct values per model.
BLOCKED_PARAMS = [
    "tool_choice",
    "metadata",
    "google",
]

# Thinking-related params stripped so app.py can re-inject canonical values.
THINKING_PARAMS = [
    "thinking",
    "reasoning_effort",
    "extended_thinking",
    "budget_tokens",
]

RECURSIVE_STRIP_KEYS = {"google", "thinking", "extended_thinking", "budget_tokens"}


def remove_blocked_keys_recursive(obj):
    """Recursively remove google, thinking, and other blocked keys from any nested structure."""
    if isinstance(obj, dict):
        for key in RECURSIVE_STRIP_KEYS:
            obj.pop(key, None)
        for value in list(obj.values()):
            remove_blocked_keys_recursive(value)
    elif isinstance(obj, list):
        for item in obj:
            remove_blocked_keys_recursive(item)
    return obj


def remove_blocked_keys(obj):
    """Recursively remove blocked keys (google, thinking, etc.) from any nested structure."""
    return remove_blocked_keys_recursive(obj)


def extract_tool_use_ids(message: dict) -> set:
    """Extract all tool_use IDs from an assistant message (either format)."""
    tool_ids = set()
    content = message.get("content", [])
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                tool_id = item.get("id")
                if tool_id:
                    tool_ids.add(tool_id)
    tool_calls = message.get("tool_calls", [])
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if isinstance(tc, dict):
                tool_id = tc.get("id")
                if tool_id:
                    tool_ids.add(tool_id)
    return tool_ids


def convert_tool_use_to_openai(tool_use: dict) -> dict:
    """Convert Anthropic-style tool_use to OpenAI-style tool_call."""
    input_data = tool_use.get("input", {})
    if isinstance(input_data, dict):
        arguments = json.dumps(input_data)
    else:
        arguments = str(input_data)
    return {
        "id": tool_use.get("id", ""),
        "type": "function",
        "function": {
            "name": tool_use.get("name", ""),
            "arguments": arguments,
        },
    }


def convert_tool_result_to_openai(tool_result: dict) -> dict:
    """Convert Anthropic-style tool_result to OpenAI-style tool message."""
    content = tool_result.get("content", "")
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif isinstance(item, str):
                text_parts.append(item)
        content = "\n".join(text_parts)
    return {
        "role": "tool",
        "tool_call_id": tool_result.get("tool_use_id", ""),
        "content": str(content),
    }


def convert_image_to_openai(item: dict) -> dict:
    """Convert Anthropic-style image to OpenAI-style image_url."""
    source = item.get("source", {})
    source_type = source.get("type", "")
    if source_type == "base64":
        media_type = source.get("media_type", "image/png")
        data = source.get("data", "")
        url = f"data:{media_type};base64,{data}"
        return {"type": "image_url", "image_url": {"url": url}}
    if source_type == "url":
        return {"type": "image_url", "image_url": {"url": source.get("url", "")}}
    return {
        "type": "image_url",
        "image_url": {"url": item.get("url", source.get("url", ""))},
    }


def clean_messages(messages: list, logger: logging.Logger) -> list:
    """
    Clean messages to be compatible with LiteLLM and Vertex AI Claude.
    Converts Anthropic-style tool_use/tool_result to OpenAI format and removes orphaned tool_result blocks.
    """
    cleaned = []
    pending_tool_ids = set()

    for msg in messages:
        if not isinstance(msg, dict):
            cleaned.append(msg)
            continue

        role = msg.get("role", "")
        content = msg.get("content")

        if role == "assistant":
            pending_tool_ids = extract_tool_use_ids(msg)
            if isinstance(content, list):
                tool_calls = []
                other_content = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "tool_use":
                            tool_calls.append(convert_tool_use_to_openai(item))
                        else:
                            remove_blocked_keys(item)
                            other_content.append(item)
                    else:
                        other_content.append(item)
                if tool_calls:
                    logger.debug(
                        "Converting %d tool_use to OpenAI tool_calls format",
                        len(tool_calls),
                    )
                    msg["tool_calls"] = tool_calls
                    if other_content:
                        text_parts = [
                            item.get("text", "")
                            for item in other_content
                            if isinstance(item, dict) and item.get("type") == "text"
                        ]
                        msg["content"] = " ".join(text_parts) if text_parts else None
                    else:
                        msg["content"] = None
                else:
                    msg["content"] = other_content if other_content else content
            cleaned.append(msg)
            continue

        if role == "user" and isinstance(content, list):
            new_content = []
            tool_messages = []
            removed_results = 0
            converted_images = 0

            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type", "")
                    if item_type == "tool_result":
                        tool_use_id = item.get("tool_use_id", "")
                        if tool_use_id in pending_tool_ids:
                            logger.debug(
                                "Converting tool_result to OpenAI format: %s",
                                tool_use_id,
                            )
                            tool_messages.append(convert_tool_result_to_openai(item))
                        else:
                            logger.debug(
                                "Removing orphaned tool_result: %s", tool_use_id
                            )
                            removed_results += 1
                    elif item_type == "image":
                        logger.debug("Converting image to OpenAI image_url format")
                        new_content.append(convert_image_to_openai(item))
                        converted_images += 1
                    else:
                        remove_blocked_keys(item)
                        new_content.append(item)
                else:
                    new_content.append(item)

            if converted_images > 0:
                logger.info("Converted %d images to OpenAI format", converted_images)
            if tool_messages or removed_results > 0:
                logger.info(
                    "Tool results: converted %d, removed %d orphaned",
                    len(tool_messages),
                    removed_results,
                )
            pending_tool_ids = set()
            if new_content:
                msg["content"] = new_content
                cleaned.append(msg)
            for tool_msg in tool_messages:
                cleaned.append(tool_msg)
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            if tool_call_id in pending_tool_ids:
                logger.debug("Keeping OpenAI tool message: %s", tool_call_id)
                remove_blocked_keys(msg)
                cleaned.append(msg)
            else:
                logger.debug("Removing orphaned OpenAI tool message: %s", tool_call_id)
        else:
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        remove_blocked_keys(item)
            cleaned.append(msg)

    return cleaned


# ── Token estimation ─────────────────────────────────────────────────────────

CHARS_PER_TOKEN = 4  # conservative estimate; real ratio is ~3.5 for English

MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "claude": 199_000,  # 200k hard limit, 1k headroom
}
DEFAULT_CONTEXT_LIMIT = 199_000

CONDENSATION_MODEL = "gemini-2.5-flash"
CONDENSATION_RESERVE = 20_000  # tokens reserved for the recent tail after condensation


def context_limit_for_model(model_name: str) -> int:
    """Return the context-window token limit for a given model name."""
    model_lower = model_name.lower()
    for prefix, limit in MODEL_CONTEXT_LIMITS.items():
        if prefix in model_lower:
            return limit
    return DEFAULT_CONTEXT_LIMIT


def estimate_tokens(obj) -> int:
    """Fast approximate token count based on serialised JSON length."""
    if isinstance(obj, str):
        return max(1, len(obj) // CHARS_PER_TOKEN)
    return max(1, len(json.dumps(obj, ensure_ascii=False)) // CHARS_PER_TOKEN)


def estimate_messages_tokens(
    messages: list, tools: list | None = None, system=None
) -> int:
    """Estimate total token count for the full request payload."""
    total = sum(estimate_tokens(msg) for msg in messages)
    if tools:
        total += estimate_tokens(tools)
    if system:
        total += estimate_tokens(system)
    return total


def split_for_condensation(
    messages: list,
    max_tokens: int,
    logger: logging.Logger,
    tools: list | None = None,
    system=None,
) -> tuple[list[dict], list[dict]] | None:
    """Decide whether condensation is needed and split messages into (history, tail).

    Returns ``None`` if the conversation already fits within *max_tokens*.
    Otherwise returns ``(history_to_summarise, tail_to_keep)``.

    The tail always includes at least the last 4 non-system messages to preserve
    the active turn and enough recent context for the model.
    The split point is chosen so the tail alone (+ system + tools) fits within
    *max_tokens* with room to spare for the condensed summary.
    """
    total = estimate_messages_tokens(messages, tools=tools, system=system)
    if total <= max_tokens:
        return None

    logger.warning(
        "Prompt too long (~%d tokens, limit %d). Will condense history.",
        total,
        max_tokens,
    )

    system_msgs = []
    non_system = []
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            system_msgs.append(msg)
        else:
            non_system.append(msg)

    fixed_cost = estimate_messages_tokens(system_msgs, tools=tools)
    budget_for_tail = max_tokens - fixed_cost - CONDENSATION_RESERVE

    MIN_TAIL = 4
    tail_start = len(non_system)
    for i in range(len(non_system) - 1, -1, -1):
        tail_candidate = non_system[i:]
        tail_tokens = estimate_messages_tokens(tail_candidate)
        tail_len = len(non_system) - i
        if tail_tokens > budget_for_tail and tail_len >= MIN_TAIL:
            break
        tail_start = i

    tail_start = min(tail_start, max(0, len(non_system) - MIN_TAIL))

    while tail_start < len(non_system):
        msg = non_system[tail_start]
        role = msg.get("role", "")

        if role == "tool":
            tail_start += 1
            continue

        if role == "user" and isinstance(msg.get("content"), list):
            has_tool_result = any(
                isinstance(item, dict) and item.get("type") == "tool_result"
                for item in msg.get("content")
            )
            if has_tool_result:
                tail_start += 1
                continue

        break

    history = non_system[:tail_start]
    tail = non_system[tail_start:]

    if not history:
        logger.warning("No history to condense; the tail alone exceeds the limit.")
        return None

    logger.info(
        "Condensation split: %d history messages (~%d tokens) + %d tail messages (~%d tokens)",
        len(history),
        estimate_messages_tokens(history),
        len(tail),
        estimate_messages_tokens(tail),
    )

    return history, system_msgs + tail


CONDENSATION_SYSTEM_PROMPT = """\
You are a conversation summariser. You will receive the earlier portion of a \
conversation between a user and a coding assistant. Produce a concise but \
thorough summary that preserves:

1. **Key decisions and outcomes** — what was decided, built, or changed.
2. **Current state of the codebase** — files created/modified, architectural choices.
3. **Important context** — constraints, requirements, user preferences, error messages.
4. **Pending items** — anything unfinished or explicitly deferred.

Write in bullet-point form. Be specific (file names, function names, error messages) \
but omit large code blocks or raw tool output. Aim for maximum information density \
in under 2000 words."""


GENERATION_SYSTEM_PROMPT = """\
You are a senior coding assistant working as a first-pass analyst. You have \
access to the FULL conversation history (which is too large for the final \
model's context window). Your job is to produce a comprehensive response \
to the user's latest request, using all the context available to you.

Your output will be handed to a second model (Claude) which will use it as \
a detailed briefing to produce the final answer. Therefore you should:

1. **Answer the user's request directly** — write the actual code, analysis, \
   or explanation they asked for.
2. **Include all relevant context** — reference specific files, functions, \
   variable names, error messages, and prior decisions from the conversation.
3. **Note any ambiguities** — flag places where you're unsure or where the \
   user's intent is unclear so the final model can handle them.
4. **Preserve tool calls** — if the user's request would typically involve \
   tool calls (file reads, writes, shell commands), describe what should be \
   done in detail so the final model can execute them.

Be thorough and specific. Do not summarise — produce the actual work product. \
The final model will refine your output but it won't have the full history, \
so anything you omit is lost."""


def build_condensation_request(history: list[dict]) -> dict:
    """Build the LLM request to summarise *history* messages using the condensation model."""
    history_text = _messages_to_text(history)
    return {
        "model": CONDENSATION_MODEL,
        "messages": [
            {"role": "system", "content": CONDENSATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Summarise the following conversation history:\n\n{history_text}",
            },
        ],
        "max_tokens": 4096,
        "temperature": 0.0,
        "stream": False,
    }


def build_generation_request(
    all_messages: list[dict],
    tools: list | None = None,
    system=None,
) -> dict:
    """Build a request for the large-context model to generate a full draft response."""
    gen_messages: list[dict] = [
        {"role": "system", "content": GENERATION_SYSTEM_PROMPT},
    ]

    if system:
        sys_text = system if isinstance(system, str) else json.dumps(system)
        gen_messages.append(
            {
                "role": "user",
                "content": (
                    "[ORIGINAL SYSTEM PROMPT — this is the system prompt the final model "
                    "will operate under. Keep your response compatible with it.]\n\n"
                    + sys_text
                ),
            }
        )
        gen_messages.append(
            {
                "role": "assistant",
                "content": "Understood. I'll keep the original system prompt in mind.",
            }
        )

    if tools:
        tools_text = json.dumps(tools, indent=1)
        gen_messages.append(
            {
                "role": "user",
                "content": (
                    "[AVAILABLE TOOLS — the final model has these tools. "
                    "Reference them by name when suggesting actions.]\n\n"
                    + tools_text[:50_000]
                ),
            }
        )
        gen_messages.append(
            {
                "role": "assistant",
                "content": "Noted. I'll reference these tools in my response.",
            }
        )

    conv_text = _messages_to_text(all_messages)
    gen_messages.append(
        {
            "role": "user",
            "content": (
                "[FULL CONVERSATION — produce a comprehensive response to the "
                "user's latest message using all the context below.]\n\n" + conv_text
            ),
        }
    )

    return {
        "model": CONDENSATION_MODEL,
        "messages": gen_messages,
        "max_tokens": 16384,
        "temperature": 0.0,
        "stream": False,
    }


def _messages_to_text(messages: list[dict]) -> str:
    """Render a message list as readable text for the summarisation prompt."""
    parts = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        if isinstance(content, list):
            text_bits = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text_bits.append(item.get("text", ""))
                    elif item.get("type") in ("image", "image_url"):
                        text_bits.append("[image]")
                    else:
                        text_bits.append(json.dumps(item)[:500])
                else:
                    text_bits.append(str(item))
            content = "\n".join(text_bits)
        elif not isinstance(content, str):
            content = json.dumps(content)[:1000] if content else ""

        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            tc_parts = []
            for tc in tool_calls:
                fn = tc.get("function", {})
                tc_parts.append(
                    f"  → {fn.get('name', '?')}({fn.get('arguments', '')[:200]})"
                )
            content = (content or "") + "\n" + "\n".join(tc_parts)

        if content:
            parts.append(f"[{role}]: {content[:3000]}")
    return "\n\n".join(parts)


def inject_summary_into_messages(
    summary: str,
    tail: list[dict],
    logger: logging.Logger,
) -> list[dict]:
    """Prepend a condensed-history user message before the tail messages."""
    summary_msg = {
        "role": "user",
        "content": (
            "[Condensed conversation history — the earlier messages in this chat "
            "have been automatically summarised to fit the context window.]\n\n"
            + summary
        ),
    }
    ack_msg = {
        "role": "assistant",
        "content": (
            "Understood. I have the condensed history of our earlier conversation "
            "and will continue with full awareness of the prior context."
        ),
    }
    result = []
    for msg in tail:
        if isinstance(msg, dict) and msg.get("role") == "system":
            result.append(msg)
    result.extend([summary_msg, ack_msg])
    for msg in tail:
        if not (isinstance(msg, dict) and msg.get("role") == "system"):
            result.append(msg)

    logger.info(
        "Injected condensed summary (%d chars) + %d tail messages = %d total messages",
        len(summary),
        len(tail),
        len(result),
    )
    return result


def inject_draft_into_messages(
    draft: str,
    summary: str,
    tail: list[dict],
    logger: logging.Logger,
) -> list[dict]:
    """Build the final message list with both the draft and condensed history."""
    result = []

    for msg in tail:
        if isinstance(msg, dict) and msg.get("role") == "system":
            result.append(msg)

    result.append(
        {
            "role": "user",
            "content": (
                "[Condensed conversation history — the earlier messages have been "
                "automatically summarised to fit the context window.]\n\n" + summary
            ),
        }
    )
    result.append(
        {
            "role": "assistant",
            "content": "Understood. I have the condensed history.",
        }
    )

    result.append(
        {
            "role": "user",
            "content": (
                "[DRAFT ANALYSIS — a large-context model (Gemini) processed the full "
                "conversation and produced the following draft response. Use this as "
                "your primary reference for context you don't have directly. Refine, "
                "correct, and improve this draft to produce the final answer. Execute "
                "any tool calls it suggests if appropriate.]\n\n" + draft
            ),
        }
    )
    result.append(
        {
            "role": "assistant",
            "content": (
                "Understood. I have the draft analysis from the full conversation context. "
                "I'll use it as reference while producing the final response."
            ),
        }
    )

    for msg in tail:
        if not (isinstance(msg, dict) and msg.get("role") == "system"):
            result.append(msg)

    logger.info(
        "Injected draft (%d chars) + summary (%d chars) + %d tail messages = %d total messages",
        len(draft),
        len(summary),
        len(tail),
        len(result),
    )
    return result


def process_request_body(data: dict, logger: logging.Logger) -> dict:
    """
    Process and clean the request body for Vertex AI compatibility.
    Returns the modified request data.
    """
    logger.debug("Original data: %s", json.dumps(data, indent=2)[:2000])
    remove_blocked_keys_recursive(data)
    for param in BLOCKED_PARAMS + THINKING_PARAMS:
        if param in data:
            logger.debug("Removing parameter: %s", param)
            del data[param]
    if "system" in data:
        remove_blocked_keys_recursive(data["system"])
    if "messages" in data:
        original_count = len(data["messages"])
        data["messages"] = clean_messages(data["messages"], logger)
        new_count = len(data["messages"])
        if original_count != new_count:
            logger.info("Cleaned messages: %d -> %d", original_count, new_count)
    return data
