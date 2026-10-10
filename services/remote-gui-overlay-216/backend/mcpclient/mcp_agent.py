
"""
MCP Agent for AnyLog integration with Ollama, OpenAI-compatible endpoints, and Claude
Based on ollama_demo.py
"""
import asyncio
import json
import traceback
from contextlib import AsyncExitStack
from typing import Any, Awaitable, Callable, Dict, List, Optional
import os
import re

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    httpx = None

try:
    import ollama
    HAS_OLLAMA = True
except (ImportError, ValueError, json.JSONDecodeError) as e:
    # Catch ImportError, ValueError (which includes JSONDecodeError), and JSONDecodeError
    HAS_OLLAMA = False
    ollama = None
    if isinstance(e, json.JSONDecodeError) or "JSON" in str(e) or "Expecting value" in str(e):
        print(f"⚠️  Could not import ollama (JSON parsing error during import): {e}")
    elif isinstance(e, ImportError):
        # Normal import error - library not installed
        pass
    else:
        print(f"⚠️  Unexpected error importing ollama: {e}")

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    HAS_MCP = True
except (ImportError, ValueError, json.JSONDecodeError, Exception) as e:
    # Catch ImportError, ValueError (which includes JSONDecodeError), JSONDecodeError, and any other Exception
    HAS_MCP = False
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None
    if isinstance(e, json.JSONDecodeError) or "JSON" in str(e) or "Expecting value" in str(e):
        print(f"⚠️  Could not import mcp (JSON parsing error during import): {e}")
    elif isinstance(e, ImportError):
        # Normal import error - library not installed
        pass
    else:
        print(f"⚠️  Unexpected error importing mcp ({type(e).__name__}): {e}")

# Default configuration - can be overridden via environment variables
DEFAULT_ANYLOG_MCP_SSE_URL = os.getenv("ANYLOG_MCP_SSE_URL", "")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
DEFAULT_CLAUDE_MODEL = os.getenv("CLAUDE_MODEL") or os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5"
DEFAULT_CLAUDE_ENDPOINT = os.getenv("CLAUDE_API_BASE") or os.getenv("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
DEFAULT_ANTHROPIC_VERSION = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
DEFAULT_LLM_API_TYPE = os.getenv("LLM_API_TYPE", "auto")
_MCP_TOOL_CACHE: Dict[str, Dict[str, Any]] = {}


# ── IEMS site grounding and small-model robustness ───────────────────────────
_IEMS_SITE_PROMPT = """You are the data assistant for the Los Gatos residential microgrid (the Mantey home, IEMS project). You can only see data through AnyLog. Call executeQuery to fetch it, unless LIVE READINGS below already answer the question.

Data lives in AnyLog database "customers". Timestamps are stored in UTC and arrive every few seconds.
solar_data (inverter, Solar Assistant): ts, battery_soc (battery state of charge in percent), battery_power (W, positive is charging, negative is discharging), pv_power (solar production, W), grid_power (W), load_power (house load, W), device_mode.
energy_readings (eGauge meter): ts, nm (channel name such as Grid Power, Panel1 (HVAC), Panel2 (H2O), Panel3 (Kitchen), Shop, Generac Power), w (watts), kwh.
nilm_disaggregated (appliance detection): ts, circuit, appliance, state (ON or OFF), confidence, avg_w.
anomalies (recorded events): ts, atype, severity, source, entity, value, threshold, message.

Call executeQuery with dbms "customers" and one SQL statement on one table, always limited in time. Examples:
battery state of charge now: SELECT ts, battery_soc FROM solar_data WHERE ts >= NOW() - 5 minutes ORDER BY ts DESC LIMIT 1
solar, battery, grid and load now: SELECT ts, pv_power, battery_power, battery_soc, grid_power, load_power FROM solar_data WHERE ts >= NOW() - 5 minutes ORDER BY ts DESC LIMIT 1
average house load in the last hour: SELECT AVG(load_power) AS avg_load_w FROM solar_data WHERE ts >= NOW() - 1 hour
power per meter channel now: SELECT nm, AVG(w) AS w FROM energy_readings WHERE ts >= NOW() - 1 minutes GROUP BY nm
appliances on now: SELECT appliance, confidence, avg_w FROM nilm_disaggregated WHERE ts >= NOW() - 2 minutes AND state = 'ON'
recent anomalies: SELECT ts, atype, entity, message FROM anomalies WHERE ts >= NOW() - 24 hours ORDER BY ts DESC LIMIT 20
Never filter nm with a value that contains parentheses. Group by nm instead.

How to answer: after the tool result, reply in one to three plain sentences that give the numbers with units (W, kW, %, kWh) and the reading time in Pacific time, taking every number and time from the tool result. Never state a number that did not come from a tool result in this conversation. Tool results already show times in Pacific time. Never reply with JSON, code, SQL or a tool call. If a query returns no rows, say so. Never guess values."""

_COMPACT_TOOL_NAMES = ("executeQuery", "queryWithIncrement", "listTables", "listColumns",
                       "getRootPolicies", "getPolicyChildren")
_COMPACT_DROP_PARAMS = {"mode", "target_node", "data_nodes"}
_COMPACT_DESCRIPTIONS = {
    "executeQuery": "Run one SQL query on one AnyLog table and return its rows. Use dbms 'customers'.",
    "queryWithIncrement": "Aggregate one table over time buckets (for example hourly averages). Use dbms 'customers' and timeColumn 'ts'.",
}
_DEFAULT_DBMS = os.getenv("MCP_DEFAULT_DBMS", "customers")
_PT_KEYS = re.compile(r"(^|_)(ts|time|timestamp|start|end|date)$", re.I)
_TS_VALUE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?$")
_FIELD_LABELS = {
    "battery_soc": ("Battery state of charge", "%"),
    "pv_power": ("Solar production", " W"),
    "battery_power": ("Battery power (charging +, discharging -)", " W"),
    "grid_power": ("Grid power", " W"),
    "load_power": ("House load", " W"),
    "w": ("Power", " W"),
    "avg_w": ("Average power", " W"),
    "kwh": ("Energy", " kWh"),
}


_SNAPSHOT_QUERIES = [
    ("inverter", "SELECT ts, battery_soc, battery_power, pv_power, grid_power, load_power, device_mode "
                 "FROM solar_data WHERE ts >= NOW() - 5 minutes ORDER BY ts DESC LIMIT 1"),
    ("meter", "SELECT nm, AVG(w) AS w FROM energy_readings WHERE ts >= NOW() - 30 seconds AND tp = 'P' GROUP BY nm"),
    ("appliances", "SELECT appliance, MAX(confidence) AS confidence, AVG(avg_w) AS avg_w FROM nilm_disaggregated "
                   "WHERE ts >= NOW() - 3 minutes AND state = 'ON' GROUP BY appliance"),
    ("anomalies", "SELECT ts, atype, entity, message FROM anomalies WHERE ts >= NOW() - 24 hours "
                  "ORDER BY ts DESC LIMIT 5"),
]


def _snapshot_enabled(api_type: Optional[str]) -> bool:
    flag = os.getenv("MCP_SITE_SNAPSHOT", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return normalize_llm_api_type(api_type) != "claude"


def _pt_clock(value: Any) -> str:
    """'2026-09-28 17:12:47' UTC -> '10:12 AM PDT'."""
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        v = str(value).strip().replace("T", " ")
        fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in v else "%Y-%m-%d %H:%M:%S"
        dt = datetime.strptime(v, fmt).replace(tzinfo=timezone.utc).astimezone(ZoneInfo("America/Los_Angeles"))
        return dt.strftime("%I:%M %p %Z").lstrip("0") + ("" if dt.date() == datetime.now(dt.tzinfo).date()
                                                         else dt.strftime(" on %b %d"))
    except Exception:
        return str(value)


def _w(v: Any, signed: bool = False) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not signed:
        f = abs(f)
    return ("%.2f kW" % (f / 1000.0)) if abs(f) >= 1000 else ("%d W" % round(f))


def _snapshot_text(results: Dict[str, List[Dict[str, Any]]]) -> str:
    lines = []
    inv = (results.get("inverter") or [None])[0]
    if inv:
        bp = float(inv.get("battery_power") or 0)
        lines.append(
            "Inverter reading at %s: battery state of charge %s%%, battery %s (%s), solar production %s, "
            "grid %s, house load %s, mode %s." % (
                _pt_clock(inv.get("ts")), _num(inv.get("battery_soc")), _w(bp),
                "charging" if bp > 0 else "discharging" if bp < 0 else "idle",
                _w(inv.get("pv_power")), _w(inv.get("grid_power"), True), _w(inv.get("load_power")),
                str(inv.get("device_mode") or "").strip()))
    elif "inverter" in results:
        lines.append("Inverter: no reading in the last 5 minutes.")
    meter = results.get("meter") or []
    if meter:
        parts = ["%s %s" % (str(r.get("nm")).strip(), _w(r.get("w"), str(r.get("nm")).strip() == "Grid Power"))
                 for r in meter]
        lines.append("eGauge meter, average of the last 30 seconds: " + ", ".join(parts) + ".")
    apps = results.get("appliances")
    if apps:
        lines.append("Appliances the NILM model reports ON now: " + ", ".join(
            "%s (%s, confidence %s)" % (str(r.get("appliance")).strip().replace("_", " "), _w(r.get("avg_w")),
                                        _num(r.get("confidence"))) for r in apps) + ".")
    elif apps is not None:
        lines.append("Appliances the NILM model reports ON now: none.")
    anoms = results.get("anomalies")
    if anoms:
        lines.append("Latest anomalies in the last 24 hours: " + " ".join(
            "%s, %s: %s." % (_pt_clock(r.get("ts")), str(r.get("atype")).strip(), str(r.get("message") or "").strip())
            for r in anoms))
    elif anoms is not None:
        lines.append("No anomalies in the last 24 hours.")
    if not lines:
        return ""
    return ("LIVE READINGS, fetched from AnyLog moments ago (times are Pacific):\n" + "\n".join(lines) +
            "\nWhen these readings answer the question, answer directly from them without calling a tool. "
            "For history, averages over time or anything not listed here, call executeQuery.")


def _system_prompt() -> str:
    extra = (
        "Keep tool calls minimal and only use the tools you are given. "
        "When query results include several rows, give the key rows or aggregates in a small markdown table. "
        "If required identifiers are missing and the site description above does not supply them, ask for them."
    )
    return (os.getenv("MCP_SITE_PROMPT") or _IEMS_SITE_PROMPT) + "\n\n" + extra


def _compact_tools_enabled(api_type: Optional[str]) -> bool:
    flag = os.getenv("MCP_COMPACT_TOOLS", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return normalize_llm_api_type(api_type) != "claude"


def _short(text: str, limit: int = 220) -> str:
    text = " ".join(str(text or "").split())
    cut = text.find(". ", 40)
    if 0 < cut < limit:
        return text[:cut + 1]
    return text[:limit]


def _compact_tool_list(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for t in tools:
        fn = t.get("function", {})
        name = fn.get("name")
        if name not in _COMPACT_TOOL_NAMES:
            continue
        params = json.loads(json.dumps(fn.get("parameters") or {"type": "object", "properties": {}}))
        props = params.get("properties") or {}
        for k in list(props):
            if k in _COMPACT_DROP_PARAMS:
                props.pop(k)
                continue
            props[k].pop("examples", None)
            if props[k].get("description"):
                props[k]["description"] = _short(props[k]["description"], 160)
        if name == "executeQuery" and "sql" in props:
            props["sql"]["description"] = ("One SELECT on one table, e.g. SELECT ts, battery_soc FROM solar_data "
                                           "WHERE ts >= NOW() - 5 minutes ORDER BY ts DESC LIMIT 1")
        if "required" in params:
            params["required"] = [r for r in params["required"] if r not in _COMPACT_DROP_PARAMS]
        out.append({"type": "function", "function": {
            "name": name,
            "description": _COMPACT_DESCRIPTIONS.get(name) or _short(fn.get("description", "")),
            "parameters": params,
        }})
    return out or tools


def _json_candidates(content: str):
    """Yield (dict, span) for every JSON object that parses inside content."""
    dec = json.JSONDecoder()
    i = 0
    while True:
        i = content.find("{", i)
        if i < 0:
            return
        try:
            obj, end = dec.raw_decode(content, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            yield obj, (i, end)
        i = end


def _parse_json_tool_calls(content: str) -> List[Dict[str, Any]]:
    """Tool calls a local model wrote as JSON text, e.g. a ```json block with
    {"name": "executeQuery", "arguments": {...}} or a <tool_call> tag."""
    if not content or '"name"' not in content:
        return []
    calls: List[Dict[str, Any]] = []
    for obj, span in _json_candidates(content):
        name = obj.get("name")
        if not isinstance(name, str) or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            continue
        if "arguments" not in obj and "parameters" not in obj:
            continue
        args = obj.get("arguments", obj.get("parameters")) or {}
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                args = {}
        calls.append({
            "id": "json-tool-%d-%s" % (len(calls) + 1, name),
            "function": {"name": name, "arguments": args if isinstance(args, dict) else {}},
            "text_span": span,
        })
    return calls


def _strip_json_tool_calls(content: str) -> str:
    if not content:
        return ""
    out = content
    for call in reversed(_parse_json_tool_calls(content)):
        a, b = call["text_span"]
        out = out[:a] + out[b:]
    out = re.sub(r"```(?:json)?\s*```", "", out)
    out = re.sub(r"</?tool_call>", "", out)
    return out.strip()


def _looks_like_tool_markup(content: str) -> bool:
    return bool(_parse_json_tool_calls(content) or "<tool_call" in content or "call:" in content
                and _parse_text_tool_calls(content))


def _repair_tool_args(tool_name: str, args: Dict[str, Any], known: set):
    """Fill the defaults a small model forgets and explain calls that cannot work."""
    if known and tool_name not in known:
        return args, ("There is no tool named '%s'. Available tools: %s. To read site data call executeQuery "
                      "with dbms 'customers' and a SQL statement." % (tool_name, ", ".join(sorted(known))))
    args = dict(args or {})
    args.setdefault("mode", "execute")
    if tool_name in ("executeQuery", "queryWithIncrement", "listTables", "listColumns"):
        if not str(args.get("dbms") or "").strip():
            args["dbms"] = _DEFAULT_DBMS
    if tool_name == "executeQuery" and not str(args.get("sql") or "").strip():
        return args, ("executeQuery needs a 'sql' argument. Tables in 'customers' are solar_data, energy_readings, "
                      "nilm_disaggregated and anomalies. For example, battery state of charge is "
                      "SELECT ts, battery_soc FROM solar_data WHERE ts >= NOW() - 5 minutes ORDER BY ts DESC LIMIT 1")
    if tool_name == "queryWithIncrement":
        args.setdefault("timeColumn", "ts")
    return args, None


def _to_pacific(value: str) -> str:
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        v = value.replace("T", " ")
        fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in v else "%Y-%m-%d %H:%M:%S"
        dt = datetime.strptime(v, fmt).replace(tzinfo=timezone.utc).astimezone(ZoneInfo("America/Los_Angeles"))
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return value


def _json_rows(text: str):
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict):
        for key in ("Query", "rows", "data", "result"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if isinstance(data, list) and all(isinstance(r, dict) for r in data):
        return data
    return None


def _rows_to_pacific(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        r2 = {}
        for k, v in r.items():
            if isinstance(v, str) and _PT_KEYS.search(str(k)) and _TS_VALUE.match(v.strip()):
                v = _to_pacific(v.strip())
            r2[k] = v
        out.append(r2)
    return out


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return ("%d" % f) if f == int(f) else ("%.2f" % f).rstrip("0").rstrip(".")


def _rows_markdown(rows: List[Dict[str, Any]], limit: int = 50) -> str:
    cols = list(rows[0].keys())
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows[:limit]:
        lines.append("| " + " | ".join(str(_num(r.get(c, ""))).strip() for c in cols) + " |")
    if len(rows) > limit:
        lines.append("")
        lines.append("%d more rows not shown." % (len(rows) - limit))
    return "\n".join(lines)


def _rows_sentence(row: Dict[str, Any]) -> str:
    when = None
    parts = []
    for k, v in row.items():
        if _PT_KEYS.search(str(k)) and isinstance(v, str) and when is None:
            when = v
            continue
        label, unit = _FIELD_LABELS.get(str(k).lower(), (str(k).replace("_", " "), ""))
        val = _num(v)
        parts.append("%s %s%s" % (label, val, unit if isinstance(val, str) and val[:1].lstrip("-").isdigit() else ""))
    text = ", ".join(parts) if parts else "no values"
    return text + (" (as of %s)" % when if when else "") + "."


def _as_dict(value: Any) -> Dict[str, Any]:
    """Normalize Ollama response objects across client versions."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {}


def normalize_llm_api_type(value: Optional[str]) -> str:
    normalized = (value or DEFAULT_LLM_API_TYPE or "auto").strip().lower()
    aliases = {
        "lmstudio": "openai",
        "lm-studio": "openai",
        "lm studio": "openai",
        "openai-compatible": "openai",
        "openai_compatible": "openai",
        "anthropic": "claude",
        "claude-api": "claude",
        "claude_api": "claude",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"auto", "ollama", "openai", "claude"} else "auto"


def _effective_llm_api_key(bearer_token: Optional[str] = None) -> Optional[str]:
    if not bearer_token or not bearer_token.strip():
        return None
    token = bearer_token.strip().strip("\"'")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token or None


def _effective_claude_api_key(bearer_token: Optional[str] = None) -> Optional[str]:
    return (
        _effective_llm_api_key(bearer_token)
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("CLAUDE_API_KEY")
    )


def _is_gemma_model(model: Optional[str]) -> bool:
    return "gemma" in (model or "").lower()


def _parse_text_tool_calls(content: str) -> List[Dict[str, Any]]:
    """
    Parse local-model text tool-call syntax such as:
    <|tool_call>call:listLocalDatabases{}
    """
    if not content or "call:" not in content:
        return []

    calls: List[Dict[str, Any]] = []
    pattern = re.compile(r"(?:<\|tool_call\>|<tool_call\|>\s*)?\s*call:([A-Za-z_][A-Za-z0-9_]*)\s*(\{.*?\})", re.DOTALL)
    for index, match in enumerate(pattern.finditer(content)):
        tool_name = match.group(1)
        raw_args = match.group(2) or "{}"
        try:
            arguments = json.loads(raw_args)
        except (json.JSONDecodeError, ValueError):
            arguments = {}
        calls.append({
            "id": f"text-tool-{index + 1}-{tool_name}",
            "function": {
                "name": tool_name,
                "arguments": arguments,
            },
            "text_span": match.span(),
        })
    return calls


def _strip_text_tool_calls(content: str) -> str:
    if not content:
        return ""
    stripped = re.sub(r"(?:<\|tool_call\>|<tool_call\|>\s*)?\s*call:[A-Za-z_][A-Za-z0-9_]*\s*\{.*?\}", "", content, flags=re.DOTALL)
    stripped = stripped.replace("<|tool_call>", "").replace("<tool_call|>", "")
    return stripped.strip()

def sanitize_json_schema(schema: dict) -> dict:
    """
    Fix common JSON Schema mistakes that break Ollama tool validation.
    - Move 'required' out of properties if incorrectly placed there.
    - Fix properties that are lists instead of proper schema objects.
    - Recursively sanitize nested schemas.
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    # Make a copy to avoid mutating the original
    schema = dict(schema)
    
    # Recursively sanitize nested schemas (items, properties, etc.)
    if "items" in schema and isinstance(schema["items"], dict):
        schema["items"] = sanitize_json_schema(schema["items"])
    
    if "properties" in schema and isinstance(schema["properties"], dict):
        sanitized_props = {}
        for prop_name, prop_value in schema["properties"].items():
            # Skip 'required' if it's incorrectly nested in properties
            if prop_name == "required" and isinstance(prop_value, list):
                continue
            
            # Fix properties that are lists instead of objects
            if isinstance(prop_value, list):
                # If it's a list, convert to array type with items
                # This handles cases like: "nodes": [{"type": "string"}] 
                # Should become: "nodes": {"type": "array", "items": {"type": "string"}}
                if len(prop_value) > 0 and isinstance(prop_value[0], dict):
                    # Assume it's an array of objects
                    sanitized_props[prop_name] = {
                        "type": "array",
                        "items": sanitize_json_schema(prop_value[0])
                    }
                else:
                    # Fallback: make it a generic array
                    sanitized_props[prop_name] = {
                        "type": "array",
                        "items": {"type": "string"}
                    }
            elif isinstance(prop_value, dict):
                # Recursively sanitize nested property schemas
                sanitized_props[prop_name] = sanitize_json_schema(prop_value)
            else:
                # Keep as-is if it's already a valid type
                sanitized_props[prop_name] = prop_value
        
        schema["properties"] = sanitized_props
    
    # Move 'required' from properties to top-level if incorrectly placed
    props = schema.get("properties", {})
    if isinstance(props, dict) and "required" in props and isinstance(props["required"], list):
        schema_required = props["required"]
        props = dict(props)
        props.pop("required", None)
        schema["properties"] = props
        # Merge/override required at top-level
        if "required" not in schema or not isinstance(schema["required"], list):
            schema["required"] = schema_required
        else:
            # Merge if both exist
            existing = set(schema["required"])
            new = set(schema_required)
            schema["required"] = list(existing | new)

    return schema

def mcp_tools_to_ollama_tools(mcp_tools) -> List[Dict[str, Any]]:
    """
    Convert MCP tool schema to Ollama tool schema:
    Ollama expects: [{"type":"function","function":{"name","description","parameters"}}]
    """
    out = []
    for t in mcp_tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": sanitize_json_schema(t.inputSchema or {"type": "object", "properties": {}}),
                },
            }
        )
    return out


def _truncate_text(text: str, limit: int = 40000) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n\n[truncated {len(text) - limit} characters]"


def _extract_mcp_result_text(payload: Any) -> str:
    """Extract model-readable text from an MCP CallToolResult payload."""
    if payload is None:
        return ""

    if isinstance(payload, str):
        return payload

    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, list):
            blocks = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and item.get("text") is not None:
                        blocks.append(str(item.get("text")))
                    elif item.get("text") is not None:
                        blocks.append(str(item.get("text")))
                    else:
                        blocks.append(json.dumps(item, default=str))
                else:
                    blocks.append(str(item))
            if blocks:
                return "\n".join(blocks)

        if payload.get("text") is not None:
            return str(payload.get("text"))

    return json.dumps(payload, default=str)


def _format_tool_result_for_model(tool_name: str, payload: Any) -> str:
    result_text = _extract_mcp_result_text(payload).strip()
    if not result_text:
        result_text = json.dumps(payload, default=str)
    rows = _json_rows(result_text)
    if rows is not None:
        if not rows:
            return f"Result from MCP tool `{tool_name}`: the query returned no rows."
        rows = _rows_to_pacific(rows)
        return _truncate_text(f"Result from MCP tool `{tool_name}` ({len(rows)} rows, times in Pacific time):\n"
                              + _rows_markdown(rows, limit=200))
    return _truncate_text(f"Result from MCP tool `{tool_name}`:\n{result_text}")


def _build_tool_result_report(tool_results: List[Dict[str, Any]]) -> str:
    """User-visible answer built from the rows when the model fails to summarise.
    Plain language and tables only, never raw JSON."""
    if not tool_results:
        return ""
    parts: List[str] = []
    for item in tool_results:
        text = _extract_mcp_result_text(item.get("response")).strip()
        rows = _json_rows(text)
        if rows is None:
            if text:
                parts.append(_truncate_text(text, 4000))
            continue
        if not rows:
            parts.append("The query returned no rows for that time window.")
        elif len(rows) == 1:
            parts.append(_rows_sentence(_rows_to_pacific(rows)[0]))
        else:
            parts.append("Times are Pacific.\n\n" + _rows_markdown(_rows_to_pacific(rows)))
    return "\n\n".join(parts) if parts else ""


def _openai_compatible_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize messages for local OpenAI-compatible servers.

    Some LM Studio model templates, especially Gemma-family templates, reject the
    OpenAI `system` channel with a runner-side "Channel Error". Fold system text
    into the first user turn while preserving assistant/tool messages.
    """
    system_parts: List[str] = []
    raw_messages: List[Dict[str, Any]] = []

    def public_message(message: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in message.items() if not key.startswith("_") and key != "text_span"}

    for message in messages:
        role = message.get("role")
        if role == "system":
            content = message.get("content") or ""
            if content:
                system_parts.append(str(content))
            continue
        if role == "assistant" and message.get("_text_tool_calls"):
            # Text-form tool calls are an internal compatibility shim for
            # local models. Do not send synthetic assistant.tool_calls back to
            # LM Studio; several runners reject that as invalid messages.
            continue
        if role in {"user", "assistant", "tool"}:
            raw_messages.append(public_message(dict(message)))

    # Gemma-family templates in LM Studio often fail if history starts with an
    # assistant turn. Drop stale leading non-user messages so the chat begins
    # with a user channel.
    while raw_messages and raw_messages[0].get("role") != "user":
        raw_messages.pop(0)

    normalized: List[Dict[str, Any]] = []
    for message in raw_messages:
        role = message.get("role")
        content = message.get("content") or ""

        # Consecutive user/assistant turns from persisted retries can also
        # trip local templates. Merge adjacent same-role text turns.
        if (
            normalized
            and role in {"user", "assistant"}
            and normalized[-1].get("role") == role
            and "tool_calls" not in normalized[-1]
            and "tool_calls" not in message
        ):
            normalized[-1]["content"] = f"{normalized[-1].get('content', '')}\n\n{content}".strip()
            continue

        if role == "tool":
            # Keep tool messages only when they follow an assistant tool call.
            previous = normalized[-1] if normalized else {}
            if previous.get("role") != "assistant" or not previous.get("tool_calls"):
                normalized.append({
                    "role": "user",
                    "content": f"Tool result:\n{content}",
                })
                continue

        normalized.append(message)

    if not system_parts:
        return normalized

    system_text = "\n\n".join(system_parts)
    for message in normalized:
        if message.get("role") == "user":
            message["content"] = f"{system_text}\n\nUser request:\n{message.get('content', '')}"
            return normalized

    return [{"role": "user", "content": system_text}, *normalized]


async def list_models_from_local_ollama(timeout: float = 10.0) -> List[Dict[str, Any]]:
    """
    List available models from local Ollama installation.
    
    Args:
        timeout: Request timeout in seconds
    
    Returns:
        List of model dictionaries with name, size, etc.
    """
    if not HAS_OLLAMA:
        raise RuntimeError("Ollama is not installed. Please install it with: pip install ollama")
    
    try:
        # Use ollama.ps() to get running local models. ollama.list() returns
        # installed models, which can make the UI show models that are not
        # actually loaded/running.
        # This is a sync call, so run it in a thread
        if not hasattr(ollama, "ps"):
            raise RuntimeError("The installed Ollama Python client does not support listing running models.")
        models_response = await asyncio.to_thread(ollama.ps)
        models_data = _as_dict(models_response)
        
        # Convert to list of dicts
        model_list = []
        for raw_model in models_data.get("models", []):
            model = _as_dict(raw_model)
            # Ollama.list() returns models as dicts with 'name' key
            # But let's be defensive and check multiple possible fields
            model_name = (
                model.get("name") or 
                model.get("model") or 
                model.get("model_name") or
                ""
            )
            
            # Debug logging
            if not model_name:
                print(f"⚠️  Warning: Model object has no name. Keys: {list(model.keys()) if isinstance(model, dict) else 'not a dict'}, Full object: {model}")
            else:
                print(f"✅ Found model: {model_name}")
            
            # Only add models that have a name
            if model_name:
                model_list.append({
                    "name": model_name,
                    "model": model_name,  # For consistency with HTTP API format
                    "size": model.get("size", 0),
                    "modified_at": model.get("modified_at", ""),
                    "details": {
                        "parameter_size": model.get("details", {}).get("parameter_size", ""),
                        "quantization_level": model.get("details", {}).get("quantization_level", ""),
                        "family": model.get("details", {}).get("family", ""),
                    } if model.get("details") else {}
                })
        print(f"📋 Running local Ollama models found: {[m['name'] for m in model_list]}")
        
        return model_list
    except Exception as e:
        raise RuntimeError(f"Failed to list running models from local Ollama: {str(e)}")


async def list_models_from_docker(endpoint: str, timeout: float = 10.0) -> List[Dict[str, Any]]:
    """
    List available models from an Ollama HTTP endpoint.
    
    Args:
        endpoint: Base URL of the Ollama server (e.g., "http://localhost:11434")
        timeout: Request timeout in seconds
    
    Returns:
        List of model dictionaries with name, size, etc.
    """
    if not HAS_HTTPX:
        raise RuntimeError("httpx is not installed. Please install it with: pip install httpx")
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Ollama API endpoint for running models. /api/tags lists installed
            # models, which is too broad for this UI.
            url = f"{endpoint.rstrip('/')}/api/ps"
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            models = data.get("models", [])
            print(f"🔍 Ollama running models response: {data}")
            print(f"🔍 Ollama running models found: {[m.get('name', m.get('model', 'unknown')) for m in models]}")
            return models
    except httpx.TimeoutException:
        raise RuntimeError(f"Request to Ollama endpoint timed out after {timeout}s")
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Ollama endpoint returned error {e.response.status_code}: {e.response.text}")
    except Exception as e:
        raise RuntimeError(f"Failed to list running models from Ollama endpoint at {endpoint}: {str(e)}")


def _openai_model_urls(endpoint: str) -> List[str]:
    base = endpoint.rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    urls = [
        f"{root}/api/v0/models",  # LM Studio native API.
        f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models",
    ]
    seen = set()
    return [url for url in urls if not (url in seen or seen.add(url))]


def _claude_model_url(endpoint: Optional[str] = None) -> str:
    base = (endpoint or DEFAULT_CLAUDE_ENDPOINT).rstrip("/")
    return f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"


def _normalize_openai_model_response(data: Any, source_url: str) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        if isinstance(data.get("error"), dict) or isinstance(data.get("error"), str):
            raise RuntimeError(f"{source_url} returned error: {data.get('error')}")
        entries = data.get("data") or data.get("models") or []
    elif isinstance(data, list):
        entries = data
    else:
        entries = []

    models = []
    for model in entries:
        if isinstance(model, str):
            model_id = model
            details = {"id": model}
        elif isinstance(model, dict):
            model_id = model.get("id") or model.get("name") or model.get("model") or model.get("path") or ""
            details = model
        else:
            model_id = getattr(model, "id", None) or getattr(model, "name", None) or getattr(model, "model", None) or ""
            details = {"raw": str(model)}
        if model_id:
            models.append({
                "name": model_id,
                "model": model_id,
                "size": details.get("size", 0) if isinstance(details, dict) else 0,
                "modified_at": details.get("created", "") if isinstance(details, dict) else "",
                "details": details,
            })
    return models


async def list_models_from_openai_endpoint(
    endpoint: str,
    timeout: float = 10.0,
    bearer_token: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    List available models from an OpenAI-compatible endpoint such as LM Studio.
    """
    if not HAS_HTTPX:
        raise RuntimeError("httpx is not installed. Please install it with: pip install httpx")

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            headers = {}
            api_key = _effective_llm_api_key(bearer_token)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            errors = []
            for url in _openai_model_urls(endpoint):
                try:
                    response = await client.get(url, headers=headers)
                    response.raise_for_status()
                    models = _normalize_openai_model_response(response.json(), url)
                    if models:
                        print(f"🔍 OpenAI-compatible models found via {url}: {[m.get('name', 'unknown') for m in models]}")
                        return models
                    errors.append(f"{url} returned no models")
                except Exception as e:
                    errors.append(f"{url}: {e}")
            raise RuntimeError(" | ".join(errors))
    except httpx.TimeoutException:
        raise RuntimeError(
            f"OpenAI-compatible model list request timed out after {timeout:.1f}s. "
            "Check that the LLM base URL is reachable and that the server exposes a model-list endpoint."
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"OpenAI-compatible endpoint returned error {e.response.status_code}: {e.response.text}")
    except Exception as e:
        raise RuntimeError(f"Failed to list models from OpenAI-compatible endpoint at {endpoint}: {str(e)}")


async def list_models_from_claude_endpoint(
    endpoint: Optional[str] = None,
    timeout: float = 10.0,
    bearer_token: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    List available models from the Claude API.
    """
    if not HAS_HTTPX:
        raise RuntimeError("httpx is not installed. Please install it with: pip install httpx")

    api_key = _effective_claude_api_key(bearer_token)
    if not api_key:
        raise RuntimeError("Claude API key is required. Set the API token field, ANTHROPIC_API_KEY, or CLAUDE_API_KEY.")

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            url = _claude_model_url(endpoint)
            headers = {
                "x-api-key": api_key,
                "anthropic-version": DEFAULT_ANTHROPIC_VERSION,
            }
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            entries = data.get("data", []) if isinstance(data, dict) else []
            models = []
            for model in entries:
                if not isinstance(model, dict):
                    continue
                model_id = model.get("id") or model.get("name") or ""
                if not model_id:
                    continue
                models.append({
                    "name": model_id,
                    "model": model_id,
                    "size": 0,
                    "modified_at": model.get("created_at", ""),
                    "details": model,
                })
            print(f"🔍 Claude models found via {url}: {[m.get('name', 'unknown') for m in models]}")
            return models
    except httpx.TimeoutException:
        raise RuntimeError(f"Claude model list request timed out after {timeout:.1f}s.")
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Claude endpoint returned error {e.response.status_code}: {e.response.text}")
    except Exception as e:
        raise RuntimeError(f"Failed to list models from Claude endpoint at {endpoint or DEFAULT_CLAUDE_ENDPOINT}: {str(e)}")


async def list_models_from_endpoint(
    endpoint: str,
    llm_api_type: Optional[str] = "auto",
    timeout: float = 10.0,
    bearer_token: Optional[str] = None
) -> Dict[str, Any]:
    api_type = normalize_llm_api_type(llm_api_type)
    if api_type == "ollama":
        return {"models": await list_models_from_docker(endpoint, timeout=timeout), "source": "ollama"}
    if api_type == "openai":
        return {"models": await list_models_from_openai_endpoint(endpoint, timeout=timeout, bearer_token=bearer_token), "source": "openai"}
    if api_type == "claude":
        return {"models": await list_models_from_claude_endpoint(endpoint, timeout=timeout, bearer_token=bearer_token), "source": "claude"}

    errors = []
    try:
        models = await list_models_from_docker(endpoint, timeout=timeout)
        if models:
            return {"models": models, "source": "ollama"}
        errors.append("Ollama endpoint returned no models")
    except Exception as e:
        errors.append(str(e))

    try:
        models = await list_models_from_openai_endpoint(endpoint, timeout=timeout, bearer_token=bearer_token)
        return {"models": models, "source": "openai"}
    except Exception as e:
        errors.append(str(e))

    raise RuntimeError("Could not list models from endpoint. " + " | ".join(errors))


async def _openai_endpoint_available(
    endpoint: str,
    timeout: float = 3.0,
    bearer_token: Optional[str] = None
) -> bool:
    if not HAS_HTTPX:
        return False
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            headers = {}
            api_key = _effective_llm_api_key(bearer_token)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            for url in _openai_model_urls(endpoint):
                try:
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200 and _normalize_openai_model_response(response.json(), url):
                        return True
                except Exception:
                    continue
            return False
    except Exception:
        return False


def _claude_tools_from_openai_tools(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    claude_tools = []
    for tool in tools or []:
        fn = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = fn.get("name")
        if not name:
            continue
        claude_tools.append({
            "name": name,
            "description": fn.get("description") or "",
            "input_schema": sanitize_json_schema(fn.get("parameters") or {"type": "object", "properties": {}}),
        })
    return claude_tools


def _parse_tool_arguments(arguments: Any) -> Dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def _claude_messages(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    system_parts: List[str] = []
    claude_messages: List[Dict[str, Any]] = []
    index = 0

    while index < len(messages):
        message = messages[index]
        role = message.get("role")
        content = message.get("content") or ""

        if role == "system":
            if content:
                system_parts.append(str(content))
            index += 1
            continue

        if role == "tool":
            blocks = []
            while index < len(messages) and messages[index].get("role") == "tool":
                tool_message = messages[index]
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tool_message.get("tool_call_id") or tool_message.get("id") or tool_message.get("name") or "tool-call",
                    "content": str(tool_message.get("content") or ""),
                })
                index += 1
            claude_messages.append({"role": "user", "content": blocks})
            continue

        if role == "assistant":
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                blocks = []
                if content:
                    blocks.append({"type": "text", "text": str(content)})
                for tool_call in tool_calls:
                    fn = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
                    tool_name = fn.get("name")
                    if not tool_name:
                        continue
                    blocks.append({
                        "type": "tool_use",
                        "id": tool_call.get("id") or f"toolu_{len(blocks) + 1}",
                        "name": tool_name,
                        "input": _parse_tool_arguments(fn.get("arguments")),
                    })
                if blocks:
                    claude_messages.append({"role": "assistant", "content": blocks})
            elif content:
                claude_messages.append({"role": "assistant", "content": str(content)})
            index += 1
            continue

        if role == "user":
            claude_messages.append({"role": "user", "content": str(content)})
        index += 1

    while claude_messages and claude_messages[0].get("role") != "user":
        claude_messages.pop(0)

    return {
        "system": "\n\n".join(system_parts),
        "messages": claude_messages,
    }


async def ollama_chat_async(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    stream: bool = False,
    llm_endpoint: Optional[str] = None,
    llm_api_type: Optional[str] = "auto",
    llm_bearer_token: Optional[str] = None,
    timeout: float = 900.0
) -> Dict[str, Any]:
    """
    Run a chat request against local Ollama, Ollama HTTP, OpenAI-compatible, or Claude endpoints.
    
    Args:
        model: Model name to use
        messages: List of message dictionaries
        tools: Optional list of tool definitions
        stream: Whether to stream responses
        llm_endpoint: Optional LLM endpoint. If None, uses local Ollama library.
        timeout: Request timeout in seconds
    
    Returns:
        Response dictionary with "message" key containing the assistant's response
    """
    # If an endpoint is provided, use the selected HTTP API.
    if llm_endpoint:
        api_type = normalize_llm_api_type(llm_api_type)
        if api_type == "claude":
            print(f"🌐 Using Claude endpoint: {llm_endpoint} with model: {model}")
            return await _claude_chat_http(llm_endpoint, model, messages, tools, timeout, bearer_token=llm_bearer_token)
        if api_type == "openai" or llm_endpoint.rstrip("/").endswith("/v1"):
            print(f"🌐 Using OpenAI-compatible endpoint: {llm_endpoint} with model: {model}")
            return await _openai_chat_http(llm_endpoint, model, messages, tools, timeout, bearer_token=llm_bearer_token)
        if api_type == "ollama":
            print(f"🌐 Using Ollama endpoint: {llm_endpoint} with model: {model}")
            return await _ollama_chat_docker(llm_endpoint, model, messages, tools, timeout)

        if await _openai_endpoint_available(llm_endpoint, bearer_token=llm_bearer_token):
            print(f"🌐 Auto-detected OpenAI-compatible endpoint: {llm_endpoint} with model: {model}")
            return await _openai_chat_http(llm_endpoint, model, messages, tools, timeout, bearer_token=llm_bearer_token)

        try:
            print(f"🌐 Auto-detecting endpoint API via Ollama first: {llm_endpoint} with model: {model}")
            return await _ollama_chat_docker(llm_endpoint, model, messages, tools, timeout)
        except Exception as ollama_error:
            print(f"⚠️  Ollama-compatible chat failed, trying OpenAI-compatible endpoint: {ollama_error}")
            try:
                return await _openai_chat_http(llm_endpoint, model, messages, tools, timeout, bearer_token=llm_bearer_token)
            except Exception as openai_error:
                raise RuntimeError(
                    "Endpoint did not work as Ollama or OpenAI/LM Studio. "
                    f"Ollama error: {ollama_error}. OpenAI-compatible error: {openai_error}"
                )
    
    # Otherwise, use local Ollama library
    if not HAS_OLLAMA:
        raise RuntimeError("Ollama is not installed. Please install it with: pip install ollama")
    
    if stream:
        raise NotImplementedError("Streaming not yet supported for local Ollama")
    
    # ollama.chat is sync; run it without blocking the event loop
    return await asyncio.to_thread(ollama.chat, model=model, messages=messages, tools=tools, stream=False)


async def _ollama_chat_docker(
    endpoint: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: float = 900.0
) -> Dict[str, Any]:
    """
    Call Ollama API via HTTP.
    Handles streaming response format (multiple JSON objects).
    
    Args:
        endpoint: Base URL of the Ollama server (e.g., "http://localhost:11434")
        model: Model name
        messages: List of message dictionaries
        tools: Optional list of tool definitions
        timeout: Request timeout in seconds
    
    Returns:
        Response dictionary compatible with local Ollama format
    """
    if not HAS_HTTPX:
        raise RuntimeError("httpx is not installed. Please install it with: pip install httpx")
    
    try:
        # Set timeout for both connect and read operations
        # httpx timeout: (connect timeout, read timeout, write timeout, pool timeout)
        httpx_timeout = httpx.Timeout(timeout, connect=10.0, read=timeout, write=30.0, pool=10.0)
        
        async with httpx.AsyncClient(timeout=httpx_timeout) as client:
            # Ollama API endpoint for chat
            url = f"{endpoint.rstrip('/')}/api/chat"
            
            payload = {
                "model": model,
                "messages": messages,
                "stream": False  # Non-streaming response
            }
            
            print(f"🌐 Ollama HTTP Request - URL: {url}, Model: {model}, Messages: {len(messages)}")
            
            if tools:
                payload["tools"] = tools
            
            # When stream=False, Ollama returns a single JSON object
            # Use regular POST request instead of streaming
            response = await client.post(url, json=payload, timeout=timeout)
            
            print(f"🌐 Ollama HTTP Response - Status: {response.status_code}")
            
            # Check for errors
            if response.status_code != 200:
                try:
                    error_json = response.json()
                    error_msg = error_json.get("error", {}).get("message", str(error_json)) if isinstance(error_json, dict) else str(error_json)
                except Exception:
                    error_msg = response.text or f"HTTP {response.status_code}"
                
                # Check if error is about tools not being supported
                error_lower = error_msg.lower()
                if "does not support tools" in error_lower or ("tool" in error_lower and "not support" in error_lower):
                    # MCP agent requires tools to function, so we can't proceed without them
                    if tools:
                        raise RuntimeError(
                            f"Model '{model}' does not support function calling (tools), which is required for MCP. "
                            f"Please use a model that supports tools, such as 'qwen2.5:7b-instruct' or other instruction-tuned models. "
                            f"Original error: {error_msg}"
                        )
                    else:
                        # Tools weren't used, so this is a different error
                        raise RuntimeError(f"Ollama endpoint returned error {response.status_code}: {error_msg}")
                else:
                    # Different error, raise normally
                    raise RuntimeError(f"Ollama endpoint returned error {response.status_code}: {error_msg}")
            
            # Parse the JSON response (single object when stream=False)
            try:
                response_json = response.json()
            except Exception as e:
                raise RuntimeError(f"Failed to parse Ollama HTTP response as JSON: {str(e)}")
            
            # Extract message content
            # Response format: {"model": "...", "message": {"role": "assistant", "content": "..."}, "done": true, ...}
            if "message" not in response_json:
                raise RuntimeError("Ollama HTTP response missing 'message' field")
            
            msg = response_json["message"]
            content = msg.get("content", "")
            
            # Build result message
            result_message = {
                "role": msg.get("role", "assistant"),
                "content": content or ""
            }
            
            # Check for tool calls
            if "tool_calls" in msg:
                result_message["tool_calls"] = msg["tool_calls"]
                print(f"🌐 Ollama HTTP Response - Found {len(msg.get('tool_calls', []))} tool call(s)")
            else:
                print(f"🌐 Ollama HTTP Response - No tool_calls in response (model may not be making tool calls)")
            
            print(f"🌐 Ollama HTTP Response - Total content length: {len(content)} chars")
            
            if not content:
                print(f"⚠️  Warning: Ollama HTTP returned empty content. Response structure: {list(response_json.keys())}")
            
            return {
                "message": result_message
            }
                
    except httpx.TimeoutException:
        raise RuntimeError(f"Request to Ollama endpoint timed out after {timeout}s")
    except httpx.HTTPStatusError as e:
        # Extract error message from response
        error_text = e.response.text
        try:
            error_json = e.response.json()
            error_msg = error_json.get("error", {}).get("message", error_text) if isinstance(error_json, dict) else error_text
        except:
            error_msg = error_text
        raise RuntimeError(f"Ollama endpoint returned error {e.response.status_code}: {error_msg}")
    except Exception as e:
        raise RuntimeError(f"Failed to communicate with Ollama endpoint: {str(e)}")


async def _openai_chat_http(
    endpoint: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: float = 900.0,
    bearer_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Call an OpenAI-compatible Chat Completions endpoint, including LM Studio.
    """
    if not HAS_HTTPX:
        raise RuntimeError("httpx is not installed. Please install it with: pip install httpx")

    def channel_error_message(error_msg: str) -> RuntimeError:
        return RuntimeError(
            "LM Studio rejected this model's chat template with a Channel Error. "
            "This usually means the selected model does not support the requested chat/tool-calling format. "
            "Try an instruct model with tool/function-calling support, or reduce prior chat history. "
            f"Original error: {error_msg}"
        )

    async def post_chat(client, url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout_value: float) -> Dict[str, Any]:
        response = await client.post(url, json=payload, headers=headers, timeout=timeout_value)
        print(f"🌐 OpenAI-compatible Response - Status: {response.status_code}")
        if response.status_code != 200:
            try:
                error_json = response.json()
                error_msg = error_json.get("error", {}).get("message", str(error_json)) if isinstance(error_json, dict) else str(error_json)
            except Exception:
                error_msg = response.text or f"HTTP {response.status_code}"
            if "channel error" in error_msg.lower():
                raise channel_error_message(error_msg)
            raise RuntimeError(f"OpenAI-compatible endpoint returned error {response.status_code}: {error_msg}")

        response_json = response.json()
        if isinstance(response_json, dict) and response_json.get("error"):
            error_value = response_json.get("error")
            error_msg = error_value.get("message", str(error_value)) if isinstance(error_value, dict) else str(error_value)
            if "channel error" in error_msg.lower():
                raise channel_error_message(error_msg)
            raise RuntimeError(f"OpenAI-compatible endpoint returned error: {error_msg}")
        return response_json

    try:
        httpx_timeout = httpx.Timeout(timeout, connect=10.0, read=timeout, write=30.0, pool=10.0)
        async with httpx.AsyncClient(timeout=httpx_timeout) as client:
            base = endpoint.rstrip("/")
            url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
            payload = {
                "model": model,
                "messages": _openai_compatible_messages(messages),
                "stream": False,
            }
            use_native_tools = bool(tools) and not _is_gemma_model(model)
            if tools and not use_native_tools:
                print(f"⚠️  Native tools disabled for model '{model}' to avoid LM Studio chat template Channel Error")
            if use_native_tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            headers = {"Content-Type": "application/json"}
            api_key = _effective_llm_api_key(bearer_token)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            print(f"🌐 OpenAI-compatible Request - URL: {url}, Model: {model}, Messages: {len(messages)}")
            try:
                response_json = await post_chat(client, url, headers, payload, timeout)
            except RuntimeError as e:
                if use_native_tools and "Channel Error" in str(e):
                    print("⚠️  Retrying LM Studio request without native tools after Channel Error")
                    fallback_payload = dict(payload)
                    fallback_payload.pop("tools", None)
                    fallback_payload.pop("tool_choice", None)
                    response_json = await post_chat(client, url, headers, fallback_payload, timeout)
                else:
                    raise
            choices = response_json.get("choices") or []
            if not choices:
                raise RuntimeError("OpenAI-compatible response missing choices")
            msg = choices[0].get("message") or {}
            result_message = {
                "role": msg.get("role", "assistant"),
                "content": msg.get("content") or "",
            }
            if msg.get("tool_calls"):
                result_message["tool_calls"] = msg["tool_calls"]
                print(f"🌐 OpenAI-compatible Response - Found {len(msg.get('tool_calls', []))} tool call(s)")
            else:
                print("🌐 OpenAI-compatible Response - No tool_calls in response")
            return {"message": result_message}
    except httpx.TimeoutException:
        raise RuntimeError(
            f"OpenAI-compatible model call timed out after {timeout:.1f}s. "
            "The local model did not finish generation in time; try reducing the date range, "
            "asking for fewer plotted points, or increasing the MCP client request timeout."
        )
    except Exception as e:
        raise RuntimeError(f"Failed to communicate with OpenAI-compatible endpoint: {str(e)}")


async def _claude_chat_http(
    endpoint: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: float = 900.0,
    bearer_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Call the Claude Messages API and convert Claude tool_use blocks back into
    the agent loop's OpenAI/Ollama-style tool_calls shape.
    """
    if not HAS_HTTPX:
        raise RuntimeError("httpx is not installed. Please install it with: pip install httpx")

    api_key = _effective_claude_api_key(bearer_token)
    if not api_key:
        raise RuntimeError("Claude API key is required. Set the API token field, ANTHROPIC_API_KEY, or CLAUDE_API_KEY.")

    try:
        httpx_timeout = httpx.Timeout(timeout, connect=10.0, read=timeout, write=30.0, pool=10.0)
        async with httpx.AsyncClient(timeout=httpx_timeout) as client:
            base = (endpoint or DEFAULT_CLAUDE_ENDPOINT).rstrip("/")
            url = f"{base}/messages" if base.endswith("/v1") else f"{base}/v1/messages"
            normalized = _claude_messages(messages)
            payload: Dict[str, Any] = {
                "model": model,
                "messages": normalized["messages"],
                "max_tokens": int(os.getenv("CLAUDE_MAX_TOKENS", "8192")),
            }
            if normalized["system"]:
                payload["system"] = normalized["system"]

            claude_tools = _claude_tools_from_openai_tools(tools)
            if claude_tools:
                payload["tools"] = claude_tools
                payload["tool_choice"] = {"type": "auto"}

            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": DEFAULT_ANTHROPIC_VERSION,
            }

            print(f"🌐 Claude Request - URL: {url}, Model: {model}, Messages: {len(payload['messages'])}")
            response = await client.post(url, json=payload, headers=headers, timeout=timeout)
            print(f"🌐 Claude Response - Status: {response.status_code}")
            if response.status_code != 200:
                try:
                    error_json = response.json()
                    error_value = error_json.get("error", error_json) if isinstance(error_json, dict) else error_json
                    error_msg = error_value.get("message", str(error_value)) if isinstance(error_value, dict) else str(error_value)
                except Exception:
                    error_msg = response.text or f"HTTP {response.status_code}"
                raise RuntimeError(f"Claude endpoint returned error {response.status_code}: {error_msg}")

            response_json = response.json()
            content_blocks = response_json.get("content") or []
            text_parts = []
            tool_calls = []
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text") is not None:
                    text_parts.append(str(block.get("text")))
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block.get("id") or f"toolu_{len(tool_calls) + 1}",
                        "type": "function",
                        "function": {
                            "name": block.get("name") or "",
                            "arguments": block.get("input") or {},
                        },
                    })

            result_message = {
                "role": "assistant",
                "content": "\n".join(text_parts).strip(),
            }
            if tool_calls:
                result_message["tool_calls"] = tool_calls
                print(f"🌐 Claude Response - Found {len(tool_calls)} tool call(s)")
            else:
                print("🌐 Claude Response - No tool_use blocks in response")
            return {"message": result_message}
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Claude model call timed out after {timeout:.1f}s. "
            "Try narrowing the request or increasing the MCP client request timeout."
        )
    except Exception as e:
        raise RuntimeError(f"Failed to communicate with Claude endpoint: {str(e)}")


class AnyLogMCPAgent:
    def __init__(
        self,
        anylog_sse_url: str,
        ollama_model: str = DEFAULT_OLLAMA_MODEL,
        llm_endpoint: Optional[str] = None,
        llm_api_type: Optional[str] = "auto",
        llm_bearer_token: Optional[str] = None
    ):
        self.anylog_sse_url = anylog_sse_url
        self.ollama_model = ollama_model
        self.llm_endpoint = llm_endpoint  # LLM endpoint (e.g., Ollama, LM Studio, or Claude API)
        self.llm_api_type = normalize_llm_api_type(llm_api_type)
        self.llm_bearer_token = llm_bearer_token.strip() if llm_bearer_token and llm_bearer_token.strip() else None
        self.session: Optional[ClientSession] = None
        self.exit_stack: Optional[AsyncExitStack] = None
        self.stdio = None
        self.write = None
        self.cached_tools: List[str] = []  # Cache tools to avoid redundant API calls
        self.cached_ollama_tools: List[Dict[str, Any]] = []

    async def connect(self, timeout: float = 10.0):
        """Connect to AnyLog MCP server via mcp-proxy with timeout"""
        if not HAS_MCP:
            raise RuntimeError("MCP libraries are not installed. Please install them with: pip install mcp")
        
        # Create a new exit stack for this connection
        self.exit_stack = AsyncExitStack()
        
        # Start mcp-proxy as a stdio "server" process that bridges to remote SSE
        server_params = StdioServerParameters(
            command="mcp-proxy",
            args=[self.anylog_sse_url],  # stdio -> remote SSE
            env=None,
        )
        
        # Connect with timeout to prevent hanging
        try:
            stdio_transport = await asyncio.wait_for(
                self.exit_stack.enter_async_context(stdio_client(server_params)),
                timeout=timeout
            )
            self.stdio, self.write = stdio_transport
            self.session = await asyncio.wait_for(
                self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write)),
                timeout=timeout
            )
            await asyncio.wait_for(self.session.initialize(), timeout=timeout)

            cache_entry = _MCP_TOOL_CACHE.get(self.anylog_sse_url)
            if cache_entry:
                self.cached_tools = list(cache_entry.get("tool_names", []))
                self.cached_ollama_tools = list(cache_entry.get("ollama_tools", []))
                print(f"🛠️  Reused {len(self.cached_tools)} cached MCP tools for {self.anylog_sse_url}")
                return self.cached_tools

            # Cache tools for fast status checks and future requests (with timeout)
            tools_resp = await asyncio.wait_for(self.session.list_tools(), timeout=timeout)
            self.cached_tools = [t.name for t in tools_resp.tools]
            self.cached_ollama_tools = mcp_tools_to_ollama_tools(tools_resp.tools)
            _MCP_TOOL_CACHE[self.anylog_sse_url] = {
                "tool_names": list(self.cached_tools),
                "ollama_tools": list(self.cached_ollama_tools),
            }
            return self.cached_tools
        except asyncio.TimeoutError:
            # Clean up on timeout
            try:
                await self.close()
            except Exception:
                pass
            raise RuntimeError(f"Connection timeout after {timeout}s. MCP server may be unreachable or overloaded.")
        except Exception as e:
            try:
                await self.close()
            except Exception:
                pass
            raise RuntimeError(
                f"Could not connect to AnyLog MCP server at {self.anylog_sse_url}. {str(e)}"
            )

    async def health_check(self, timeout: float = 3.0) -> bool:
        """Verify the MCP connection is actually working with timeout"""
        if not self.session:
            return False
        
        try:
            # Try a lightweight operation to verify connection is alive
            # Use a short timeout to avoid blocking
            await asyncio.wait_for(self.session.list_tools(), timeout=timeout)
            return True
        except (asyncio.TimeoutError, Exception) as e:
            # Connection is dead, mark as disconnected
            print(f"Health check failed: {e}")
            return False

    async def ask(
        self, 
        user_prompt: str, 
        conversation_history: Optional[List[Dict[str, str]]] = None,
        timeout: float = 900.0,
        event_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
    ) -> str:
        """Ask a question to the MCP agent using Ollama with timeout and conversation history"""
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Check if we have a way to call LLM (either local Ollama or a custom endpoint)
        if not self.llm_endpoint and not HAS_OLLAMA:
            raise RuntimeError(
                "No LLM available. Either install Ollama locally (pip install ollama) "
                "or provide an LLM endpoint (llm_endpoint parameter)."
            )

        print(f"⏱️  Starting ask() with timeout={timeout}s")
        start_time = asyncio.get_event_loop().time()

        async def emit(event: Dict[str, Any]):
            if event_callback:
                await event_callback(event)
        
        try:
            # Pull MCP tools once per MCP server, then reuse schemas for subsequent requests.
            list_tools_start = asyncio.get_event_loop().time()
            if self.cached_ollama_tools:
                ollama_tools = self.cached_ollama_tools
                print(f"🛠️  Using {len(ollama_tools)} cached MCP tools: {self.cached_tools}")
                await emit({
                    "type": "mcp_response",
                    "request_id": "list-tools",
                    "tool_name": "list_tools",
                    "arguments": {},
                    "response": {
                        "cached": True,
                        "tool_count": len(self.cached_tools),
                        "tools": self.cached_tools,
                    },
                    "elapsed_ms": 0,
                    "total_elapsed_ms": int((asyncio.get_event_loop().time() - start_time) * 1000),
                })
            else:
                print(f"🔍 Fetching MCP tools...")
                await emit({
                    "type": "mcp_request",
                    "request_id": "list-tools",
                    "tool_name": "list_tools",
                    "arguments": {},
                    "iteration": 0,
                    "total_elapsed_ms": int((list_tools_start - start_time) * 1000),
                })
                try:
                    tools_resp = await asyncio.wait_for(self.session.list_tools(), timeout=10.0)
                except Exception as e:
                    await emit({
                        "type": "mcp_error",
                        "request_id": "list-tools",
                        "tool_name": "list_tools",
                        "arguments": {},
                        "error": str(e),
                        "elapsed_ms": int((asyncio.get_event_loop().time() - list_tools_start) * 1000),
                        "total_elapsed_ms": int((asyncio.get_event_loop().time() - start_time) * 1000),
                    })
                    raise
                self.cached_tools = [t.name for t in tools_resp.tools]
                self.cached_ollama_tools = mcp_tools_to_ollama_tools(tools_resp.tools)
                _MCP_TOOL_CACHE[self.anylog_sse_url] = {
                    "tool_names": list(self.cached_tools),
                    "ollama_tools": list(self.cached_ollama_tools),
                }
                ollama_tools = self.cached_ollama_tools
                print(f"🛠️  Loaded {len(ollama_tools)} MCP tools: {[t['function']['name'] for t in ollama_tools]}")
                elapsed = asyncio.get_event_loop().time() - start_time
                await emit({
                    "type": "mcp_response",
                    "request_id": "list-tools",
                    "tool_name": "list_tools",
                    "arguments": {},
                    "response": {
                        "cached": False,
                        "tool_count": len(tools_resp.tools),
                        "tools": [t.name for t in tools_resp.tools],
                    },
                    "elapsed_ms": int((asyncio.get_event_loop().time() - list_tools_start) * 1000),
                    "total_elapsed_ms": int(elapsed * 1000),
                })
                print(f"⏱️  Tool fetching took {elapsed:.2f}s")

            # Build message history with system prompt
            messages: List[Dict[str, Any]] = [
                {
                    "role": "system",
                    "content": (
                        _system_prompt()
                    ),
                },
            ]
            
            # Add conversation history (keep local model chat templates conservative)
            include_history = not (self.llm_api_type == "openai" and _is_gemma_model(self.ollama_model))
            if conversation_history and include_history:
                # Take last 8 messages to keep context manageable and avoid brittle
                # local templates failing with long multi-turn conversations.
                recent_history = conversation_history[-8:]
                for msg in recent_history:
                    # Only include user and assistant messages, skip errors
                    if msg.get("role") in ["user", "assistant"]:
                        messages.append({
                            "role": msg.get("role"),
                            "content": msg.get("content", "")
                        })
            elif conversation_history and not include_history:
                print(f"⚠️  Chat history disabled for model '{self.ollama_model}' in LM Studio compatibility mode")
            
            # Add current user prompt
            messages.append({"role": "user", "content": user_prompt})
            if _compact_tools_enabled(self.llm_api_type):
                ollama_tools = _compact_tool_list(ollama_tools)
                print(f"🛠️  Compact tool set for {self.llm_api_type}: {[t['function']['name'] for t in ollama_tools]}")
            self._has_snapshot = False
            if _snapshot_enabled(self.llm_api_type):
                snapshot = await self._site_snapshot(emit, start_time)
                if snapshot:
                    # Appended to the question, not the system prompt, so the system prompt and
                    # tool schemas stay an identical prefix that Ollama can reuse between questions.
                    messages[-1]["content"] = snapshot + "\n\nQuestion: " + str(messages[-1]["content"])
                    self._has_snapshot = True

            # Agent loop: model decides tool calls; we execute them via MCP; feed results back
            # Wrap entire loop in timeout to prevent hanging
            print(f"🔄 Starting agent loop with {len(messages)} messages...")
            try:
                result = await asyncio.wait_for(
                    self._agent_loop(
                        messages,
                        ollama_tools,
                        event_callback=event_callback,
                        command_start=start_time,
                        loop_timeout=timeout
                    ),
                    timeout=timeout
                )
                elapsed = asyncio.get_event_loop().time() - start_time
                print(f"✅ Agent loop completed in {elapsed:.2f}s")
                return result
            except asyncio.TimeoutError:
                elapsed = asyncio.get_event_loop().time() - start_time
                print(f"❌ Request timed out after {elapsed:.2f}s (limit: {timeout}s)")
                raise RuntimeError(
                    f"Request timed out after {timeout}s. The local model or MCP server did not finish in time. "
                    f"Elapsed time: {elapsed:.2f}s"
                )
        except asyncio.TimeoutError:
            elapsed = asyncio.get_event_loop().time() - start_time
            print(f"❌ Operation timed out after {elapsed:.2f}s")
            raise

    async def _site_snapshot(self, emit, command_start) -> str:
        """Fetch the current site readings through the MCP session itself."""
        results: Dict[str, List[Dict[str, Any]]] = {}
        loop = asyncio.get_event_loop()
        for key, sql in _SNAPSHOT_QUERIES:
            args = {"dbms": _DEFAULT_DBMS, "sql": sql, "mode": "execute"}
            rid = "snapshot-%s" % key
            t0 = loop.time()
            try:
                await emit({"type": "mcp_request", "request_id": rid, "tool_name": "executeQuery",
                            "arguments": args, "iteration": 0,
                            "total_elapsed_ms": int((t0 - command_start) * 1000)})
                res = await asyncio.wait_for(self.session.call_tool("executeQuery", args), timeout=25.0)
                payload = res.model_dump() if hasattr(res, "model_dump") else res
                await emit({"type": "mcp_response", "request_id": rid, "tool_name": "executeQuery",
                            "arguments": args, "response": payload,
                            "elapsed_ms": int((loop.time() - t0) * 1000),
                            "total_elapsed_ms": int((loop.time() - command_start) * 1000)})
                rows = _json_rows(_extract_mcp_result_text(payload).strip())
                if rows is not None:
                    results[key] = rows
            except Exception as exc:
                print(f"⚠️  Snapshot query {key} failed: {exc}")
        text = _snapshot_text(results)
        print(f"📸 Site snapshot: {len(text)} chars from {sorted(results)}")
        return text

    async def _agent_loop(
        self,
        messages: List[Dict[str, Any]],
        ollama_tools: List[Dict[str, Any]],
        event_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        command_start: Optional[float] = None,
        loop_timeout: float = 900.0
    ) -> str:
        """Internal agent loop with timeouts on individual operations"""
        command_start = command_start or asyncio.get_event_loop().time()

        async def emit(event: Dict[str, Any]):
            if event_callback:
                await event_callback(event)

        print(f"🔧 Agent loop starting with {len(ollama_tools)} tools available")
        tool_results: List[Dict[str, Any]] = []
        text_tool_call_signatures = set()
        _nudged_for_tool = False
        for iteration in range(12):  # safety loop cap
            iteration_start = asyncio.get_event_loop().time()
            elapsed_total = iteration_start - command_start
            remaining_timeout = max(30.0, loop_timeout - elapsed_total)
            print(f"🔄 Agent loop iteration {iteration + 1}/12")
            print(f"⏱️  Calling LLM ({self.ollama_model}) with timeout={remaining_timeout:.1f}s...")
            resp = await ollama_chat_async(
                model=self.ollama_model,
                messages=messages,
                tools=ollama_tools,
                stream=False,
                llm_endpoint=self.llm_endpoint,
                llm_api_type=self.llm_api_type,
                llm_bearer_token=self.llm_bearer_token,
                timeout=remaining_timeout,
            )
            iteration_elapsed = asyncio.get_event_loop().time() - iteration_start
            print(f"⏱️  LLM call completed in {iteration_elapsed:.2f}s")

            msg = resp["message"]
            text_tool_calls = _parse_text_tool_calls(msg.get("content", ""))
            if not text_tool_calls and not msg.get("tool_calls"):
                text_tool_calls = _parse_json_tool_calls(msg.get("content", ""))
            if text_tool_calls and not msg.get("tool_calls"):
                msg = {
                    **msg,
                    "content": _strip_text_tool_calls(_strip_json_tool_calls(msg.get("content", ""))),
                    "tool_calls": text_tool_calls,
                    "_text_tool_calls": True,
                }
                print(f"📥 Parsed {len(text_tool_calls)} text tool call(s) from model content")
            messages.append(msg)
            
            # Debug: Log what we received
            print(f"📥 LLM Response - Content length: {len(msg.get('content', ''))}")
            print(f"📥 LLM Response - Has tool_calls: {bool(msg.get('tool_calls'))}")
            if msg.get("tool_calls"):
                print(f"📥 LLM Response - Tool calls: {len(msg.get('tool_calls', []))}")
                for tc in msg.get("tool_calls", []):
                    print(f"   - Tool: {tc.get('function', {}).get('name', 'unknown')}")

            tool_calls = msg.get("tool_calls") or []
            text_tool_call_mode = bool(msg.get("_text_tool_calls"))
            if text_tool_call_mode:
                signatures = {
                    f"{tc.get('function', {}).get('name')}:{json.dumps(tc.get('function', {}).get('arguments') or {}, sort_keys=True, default=str)}"
                    for tc in tool_calls
                }
                if signatures and signatures.issubset(text_tool_call_signatures):
                    fallback_report = _build_tool_result_report(tool_results)
                    if fallback_report:
                        return fallback_report
                text_tool_call_signatures.update(signatures)
            if not tool_calls:
                print(f"⚠️  No tool calls detected. Model returned direct answer (may be too small or not understanding tool usage)")
                content_preview = msg.get('content', '')[:200]
                print(f"   Response preview: {content_preview}...")
                content = msg.get("content", "") or ""
                if not tool_results and not _nudged_for_tool and not getattr(self, "_has_snapshot", False) and re.search(r"\d", content):
                    # A number with no data behind it: make the model fetch it first.
                    _nudged_for_tool = True
                    print("⚠️  Answer contained numbers without any tool call; asking the model to call a tool")
                    messages.append({"role": "user", "content": (
                        "You have not called any tool yet, so you have no data. Call executeQuery now with dbms "
                        "customers and the SQL that answers the question, then answer only from its result.")})
                    continue
                if self.llm_api_type == "openai" and _is_gemma_model(self.ollama_model) and not content.strip():
                    return (
                        "LM Studio accepted the request, but this Gemma model did not return a usable chat response. "
                        "For MCP data questions, select an LM Studio model with native tool/function-calling support, "
                        "or switch back to a tool-capable Ollama model."
                    )
                if content.strip():
                    if _looks_like_tool_markup(content):
                        report = _build_tool_result_report(tool_results)
                        if report:
                            return report
                        return ("The model replied with a tool call it could not complete. "
                                "Please ask again, for example: What is the battery state of charge right now?")
                    return content
                fallback_report = _build_tool_result_report(tool_results)
                if fallback_report:
                    print("⚠️  Model returned empty content after tool calls; returning MCP data report fallback")
                    return fallback_report
                return content

            # Execute each tool call against AnyLog MCP (with timeout per call)
            print(f"🔨 Executing {len(tool_calls)} tool call(s)")
            for tc in tool_calls:
                fn = tc["function"]
                tool_name = fn["name"]
                tool_args = fn.get("arguments") or {}
                print(f"🔨 Calling tool: {tool_name} with args: {tool_args}")
                if isinstance(tool_args, str):
                    try:
                        # Handle empty string or invalid JSON
                        if not tool_args.strip():
                            tool_args = {}
                        else:
                            tool_args = json.loads(tool_args)
                    except (json.JSONDecodeError, ValueError) as e:
                        # If JSON parsing fails, log and use empty dict
                        print(f"⚠️  Warning: Failed to parse tool arguments as JSON for {tool_name}: {e}")
                        print(f"   Raw arguments: {tool_args}")
                        tool_args = {}

                known_tools = {t.get('function', {}).get('name') for t in ollama_tools}
                tool_args, arg_error = _repair_tool_args(tool_name, tool_args if isinstance(tool_args, dict) else {}, known_tools)
                if arg_error:
                    print(f"⚠️  Rejected call {tool_name}: {arg_error}")
                    if text_tool_call_mode:
                        messages.append({"role": "user", "content": arg_error + " Call the tool again with correct arguments."})
                    else:
                        messages.append({"role": "tool", "tool_call_id": tc.get("id") or tool_name,
                                         "tool_name": tool_name, "name": tool_name, "content": arg_error})
                    continue
                try:
                    tool_start = asyncio.get_event_loop().time()
                    request_id = f"{iteration + 1}-{tool_name}-{int(tool_start * 1000)}"
                    await emit({
                        "type": "mcp_request",
                        "request_id": request_id,
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "iteration": iteration + 1,
                        "total_elapsed_ms": int((tool_start - command_start) * 1000),
                    })
                    print(f"⏱️  Calling tool '{tool_name}'...")
                    result = await asyncio.wait_for(
                        self.session.call_tool(tool_name, tool_args),
                        timeout=60.0  # 60s timeout per tool call (increased from 30s)
                    )
                    tool_elapsed = asyncio.get_event_loop().time() - tool_start
                    print(f"✅ Tool '{tool_name}' completed in {tool_elapsed:.2f}s")
                except asyncio.TimeoutError:
                    tool_elapsed = asyncio.get_event_loop().time() - tool_start
                    await emit({
                        "type": "mcp_error",
                        "request_id": request_id,
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "error": f"Tool call '{tool_name}' timed out after 60s.",
                        "elapsed_ms": int(tool_elapsed * 1000),
                        "total_elapsed_ms": int((asyncio.get_event_loop().time() - command_start) * 1000),
                    })
                    print(f"❌ Tool call '{tool_name}' timed out after {tool_elapsed:.2f}s")
                    raise RuntimeError(f"Tool call '{tool_name}' timed out after 60s. The MCP server may be overloaded or unresponsive.")
                except Exception as e:
                    tool_elapsed = asyncio.get_event_loop().time() - tool_start
                    await emit({
                        "type": "mcp_error",
                        "request_id": request_id,
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "error": str(e),
                        "exception": traceback.format_exc(),
                        "elapsed_ms": int(tool_elapsed * 1000),
                        "total_elapsed_ms": int((asyncio.get_event_loop().time() - command_start) * 1000),
                    })
                    raise

                # Feed tool result back to the model
                result_payload = result.model_dump() if hasattr(result, "model_dump") else result
                tool_results.append({
                    "tool_name": tool_name,
                    "arguments": tool_args,
                    "response": result_payload,
                })
                await emit({
                    "type": "mcp_response",
                    "request_id": request_id,
                    "tool_name": tool_name,
                    "arguments": tool_args,
                    "response": result_payload,
                    "elapsed_ms": int(tool_elapsed * 1000),
                    "total_elapsed_ms": int((asyncio.get_event_loop().time() - command_start) * 1000),
                })
                formatted_result = _format_tool_result_for_model(tool_name, result_payload)
                if text_tool_call_mode:
                    messages.append({
                        "role": "user",
                        "content": (
                            f"{formatted_result}\n\n"
                            "Now answer the user's question in one to three plain sentences using these numbers, "
                            "with units and Pacific times. Do not output JSON, code, SQL or a tool call."
                        ),
                    })
                else:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id") or request_id,
                            "tool_name": tool_name,
                            "name": tool_name,
                            "content": formatted_result,
                        }
                    )

        fallback_report = _build_tool_result_report(tool_results)
        if fallback_report:
            return f"Stopped after too many tool-call iterations. Here is the data returned so far:\n\n{fallback_report}"
        return "Stopped (too many tool-call iterations). Try narrowing the question."

    async def close(self, timeout: float = 5.0):
        """Close the MCP connection with timeout"""
        try:
            # Close the exit stack if it exists (with timeout)
            if self.exit_stack is not None:
                try:
                    await asyncio.wait_for(self.exit_stack.aclose(), timeout=timeout)
                except asyncio.TimeoutError:
                    # Force cleanup on timeout
                    print(f"Warning: Connection close timed out after {timeout}s, forcing cleanup")
                except RuntimeError as e:
                    # Handle "Attempted to exit cancel scope in a different task" error
                    # This happens when AsyncExitStack is closed from a different async task
                    # than where it was created. We'll just reset the state.
                    error_msg = str(e).lower()
                    if "different task" in error_msg or "cancel scope" in error_msg:
                        # Can't clean up properly from different task, just reset state
                        pass
                    else:
                        raise
                except Exception:
                    # Other errors - just reset state
                    pass
                finally:
                    self.exit_stack = None
            
            # Reset all state
            self.session = None
            self.stdio = None
            self.write = None
            self.cached_tools = []
            self.cached_ollama_tools = []
        except Exception:
            # Ensure state is reset even if cleanup fails
            self.session = None
            self.exit_stack = None
            self.stdio = None
            self.write = None
            self.cached_tools = []
            self.cached_ollama_tools = []
