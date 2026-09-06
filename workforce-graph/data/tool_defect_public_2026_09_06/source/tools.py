"""Generic utilities only: no fixture oracle, hidden facts, model call or grader import."""

from __future__ import annotations

import copy


def _schema(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


TOOLS = [
    _schema(
        "table_rows",
        "Select already-visible rows by an optional exact field/value; returns raw facts only.",
        {"table": {"type": "string"}, "field": {"type": "string"}, "value": {"type": "string"}},
        ["table"],
    ),
    _schema(
        "integer_math",
        "Sum, subtract, or multiply supplied integers. No access to task answers.",
        {
            "op": {"type": "string", "enum": ["sum", "subtract", "product"]},
            "values": {"type": "array", "items": {"type": "integer"}, "maxItems": 100},
        },
        ["op", "values"],
    ),
    _schema(
        "normalize_text",
        "Strip whitespace on supplied strings and optionally lowercase them.",
        {
            "values": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
            "lowercase": {"type": "boolean"},
        },
        ["values", "lowercase"],
    ),
]


def execute_tool(public: dict, name: str, args: dict):
    if not isinstance(args, dict):
        raise TypeError("arguments must be an object")
    if name == "table_rows":
        if set(args) - {"table", "field", "value"} or "table" not in args:
            raise ValueError("invalid table arguments")
        if ("field" in args) != ("value" in args):
            raise ValueError("field and value must occur together")
        if not isinstance(args["table"], str) or args["table"] not in public["tables"]:
            raise ValueError("unknown visible table")
        rows = public["tables"][args["table"]]
        if "field" in args:
            if not isinstance(args["field"], str) or any(args["field"] not in row for row in rows):
                raise ValueError("unknown field")
            rows = [row for row in rows if str(row[args["field"]]) == str(args["value"])]
        return copy.deepcopy(rows)
    if name == "integer_math":
        if set(args) != {"op", "values"} or not isinstance(args["values"], list):
            raise ValueError("invalid math arguments")
        values = args["values"]
        if not 1 <= len(values) <= 100 or any(
            type(v) is not int or abs(v) > 10**12 for v in values
        ):
            raise ValueError("bounded integers required")
        if args["op"] == "sum":
            return sum(values)
        if args["op"] == "subtract" and len(values) == 2:
            return values[0] - values[1]
        if args["op"] == "product" and len(values) == 2:
            return values[0] * values[1]
        raise ValueError("unsupported operation/arity")
    if name == "normalize_text":
        if set(args) != {"values", "lowercase"} or type(args["lowercase"]) is not bool:
            raise ValueError("invalid normalization arguments")
        if (
            not isinstance(args["values"], list)
            or len(args["values"]) > 100
            or any(not isinstance(v, str) or len(v) > 1000 for v in args["values"])
        ):
            raise ValueError("bounded strings required")
        return [v.strip().lower() if args["lowercase"] else v.strip() for v in args["values"]]
    raise ValueError("unknown tool")
