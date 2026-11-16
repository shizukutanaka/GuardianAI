"""GuardianAI MCP server - Model Context Protocol over stdio.

Exposes GuardianAI's read-only core to AI agents as MCP tools:

  classify_request  Router classification + first-principles plan
                    (pure computation - nothing is executed and
                    nothing is written to the audit DB)
  scan_sensitive    names of sensitive-data patterns found in text
                    (pattern names only - the matched secret itself
                    is never returned)
  redact_text       text with sensitive spans replaced by
                    <REDACTED:name> markers
  audit_integrity   verify the local audit DB (sqlite quick_check +
                    HMAC chain) - the DB path is NOT a parameter, so
                    the tool cannot be pointed at arbitrary files
  list_agents       the agent types the router can select, with the
                    complexity -> model map

Deliberately NOT exposed: the Executor (it writes audit rows and
ingests local files by name - a write path and a file-read path an
agent must not reach), export/backup/decrypt (file paths), config
(writes preferences), and update (the product's only network call).

Stdlib only: MCP over stdio is newline-delimited JSON-RPC 2.0, so no
`mcp` package is needed. No network code exists in this module; the
tools run entirely on this machine, and no data leaves it.

Run:  python src/main.py mcp        (one-shot, intercepted pre-init)
      python -m guardian_ai.mcp_server
"""
import json
import sys

from guardian_ai import __version__
from guardian_ai.compliance import audit_integrity, redact, scan_sensitive
from guardian_ai.router import AgentType, Router, RouterConfig

# Protocol revisions whose stdio framing + tools surface this server
# implements. The client's requested version is echoed back when it
# is one of these; otherwise the oldest (widest-supported) is used.
_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
_DEFAULT_PROTOCOL = "2024-11-05"

# A classify/scan prompt is a paragraph, not a corpus. The cap keeps a
# runaway (or hostile) client from making the server chew unbounded
# input; pattern scans are regex passes over the whole string.
_MAX_TEXT = 100_000

_router = None


def _get_router() -> Router:
    global _router
    if _router is None:
        _router = Router()
    return _router


def _text_arg(arguments, key):
    """Validate a required string argument; return (value, error)."""
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        return None, f"argument '{key}' must be a non-empty string"
    if len(value) > _MAX_TEXT:
        return None, f"argument '{key}' exceeds {_MAX_TEXT} characters"
    return value, None


def _tool_classify(arguments):
    request, err = _text_arg(arguments, "request")
    if err:
        return None, err
    # Router.analyze is pure: classify + think. It does NOT run the
    # Executor, so no audit row is written and no file is ingested.
    return _get_router().analyze(request), None


def _tool_scan(arguments):
    text, err = _text_arg(arguments, "text")
    if err:
        return None, err
    # scan_sensitive returns pattern names only - the secret matched
    # by a pattern is never part of the result.
    return {"findings": scan_sensitive(text)}, None


def _tool_redact(arguments):
    text, err = _text_arg(arguments, "text")
    if err:
        return None, err
    return {"redacted": redact(text)}, None


def _tool_audit_integrity(arguments):
    # No parameters on purpose: audit_integrity() with its default
    # path only. Accepting a path would turn this into a probe for
    # arbitrary sqlite files on the machine.
    return audit_integrity(), None


def _tool_list_agents(arguments):
    config = RouterConfig()
    return {
        "agents": [a.value for a in AgentType],
        "complexity_models": dict(config.complexity_map),
        "default_model": config.default_model,
    }, None


_TOOLS = {
    "classify_request": {
        "handler": _tool_classify,
        "definition": {
            "name": "classify_request",
            "description": "Classify a request to one of GuardianAI's "
                           "agents (accounting / legal / hr / it / "
                           "developer / medical / general) and return "
                           "the first-principles plan (assumptions "
                           "questioned, fundamentals, unknowns, task "
                           "list). Analysis only: nothing is executed "
                           "and nothing is written to the audit log.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {"type": "string",
                                "description": "The request text to classify."},
                },
                "required": ["request"],
            },
        },
    },
    "scan_sensitive": {
        "handler": _tool_scan,
        "definition": {
            "name": "scan_sensitive",
            "description": "Scan text for sensitive-data patterns "
                           "(private keys, API keys, tokens, passwords, "
                           "credit cards, JP My Number, ...). Returns "
                           "the NAMES of the patterns found only - the "
                           "matched secret itself is never returned.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                             "description": "The text to scan."},
                },
                "required": ["text"],
            },
        },
    },
    "redact_text": {
        "handler": _tool_redact,
        "definition": {
            "name": "redact_text",
            "description": "Return the text with sensitive-data spans "
                           "replaced by <REDACTED:pattern> markers, so "
                           "it is safe to log or share.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                             "description": "The text to redact."},
                },
                "required": ["text"],
            },
        },
    },
    "audit_integrity": {
        "handler": _tool_audit_integrity,
        "definition": {
            "name": "audit_integrity",
            "description": "Verify GuardianAI's local audit trail: "
                           "sqlite structural check plus the HMAC "
                           "hash-chain over audit entries (catches "
                           "hand-edited rows). Read-only.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    },
    "list_agents": {
        "handler": _tool_list_agents,
        "definition": {
            "name": "list_agents",
            "description": "List the agent types GuardianAI's router "
                           "can select, with the complexity -> model "
                           "mapping used for local inference.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    },
}


def _result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def _tool_result(payload, is_error=False):
    return {
        "content": [{"type": "text",
                     "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": is_error,
    }


def handle_message(msg):
    """One parsed JSON-RPC message -> response dict, or None when the
    message is a notification (which never gets a response)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" \
            or not isinstance(msg.get("method"), str):
        return _error(msg.get("id") if isinstance(msg, dict) else None,
                      -32600, "invalid request")

    method = msg["method"]
    is_notification = "id" not in msg
    if is_notification or method.startswith("notifications/"):
        return None
    req_id = msg["id"]
    params = msg.get("params") or {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in _PROTOCOL_VERSIONS \
            else _DEFAULT_PROTOCOL
        return _result(req_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "guardian-ai", "version": __version__},
        })
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {
            "tools": [t["definition"] for t in _TOOLS.values()],
        })
    if method == "tools/call":
        if not isinstance(params, dict) \
                or not isinstance(params.get("name"), str):
            return _error(req_id, -32602, "invalid params: 'name' required")
        tool = _TOOLS.get(params["name"])
        if tool is None:
            # Per MCP convention an unknown tool is a tool-level
            # error result, not a protocol error.
            return _result(req_id, _tool_result(
                {"error": f"unknown tool: {params['name']}"},
                is_error=True))
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(req_id, -32602,
                          "invalid params: 'arguments' must be an object")
        try:
            payload, err = tool["handler"](arguments)
        except Exception as e:  # a tool failure is a tool result, not
            payload, err = None, f"{type(e).__name__}: {e}"  # a dead server
        if err:
            return _result(req_id, _tool_result({"error": err},
                                                is_error=True))
        return _result(req_id, _tool_result(payload))
    return _error(req_id, -32601, f"method not found: {method}")


def serve(stdin=None, stdout=None) -> None:
    """Newline-delimited JSON-RPC loop over stdio until EOF."""
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            response = _error(None, -32700, "parse error")
            stdout.write(json.dumps(response).encode("utf-8") + b"\n")
            stdout.flush()
            continue
        # JSON-RPC batch: answer each element, keep the array shape.
        messages = msg if isinstance(msg, list) else [msg]
        responses = [r for r in (handle_message(m) for m in messages)
                     if r is not None]
        if not responses:
            continue
        out = responses if isinstance(msg, list) else responses[0]
        stdout.write(json.dumps(out, ensure_ascii=False).encode("utf-8")
                     + b"\n")
        stdout.flush()


def main() -> None:
    try:
        serve()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()


__all__ = ["handle_message", "serve", "main"]
