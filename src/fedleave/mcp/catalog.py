"""Derive schemas and literal argv from the authoritative Typer/Click registry.

No command signatures live here. Unknown parameter types fail discovery rather
than disappearing. Both Click and Typer's vendored Click metadata are supported.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from typer.main import get_command

from fedleave import __build_commit__, __version__


class CatalogError(ValueError):
    """A CLI parameter cannot be represented faithfully."""


def _value(value):
    # Click's UNSET sentinel is itself an Enum whose value is an opaque object.
    # Handle it before ordinary enums, including with newer external Click.
    if type(value).__name__ in {"Sentinel", "_Sentinel"}:
        return None
    if isinstance(value, Enum):
        return _value(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_value(v) for v in value]
    if callable(value):
        raise CatalogError("Callable defaults need an explicit schema adapter")
    json.dumps(value, allow_nan=False)
    return value


def type_schema(kind) -> dict[str, Any]:
    """Map known Click types without inferring types from help strings."""
    classes = {cls.__name__ for cls in type(kind).__mro__}
    if "Choice" in classes:
        choices = [_value(v) for v in kind.choices]
        result = {"enum": choices, "type": "integer" if all(type(v) is int for v in choices) else "string"}
        if not kind.case_sensitive and result["type"] == "string":
            patterns = [
                "".join(
                    f"[{v.lower()}{v.upper()}]" if v.isalpha() and v.isascii() else re.escape(v) for v in str(choice)
                )
                for choice in choices
            ]
            result = {"type": "string", "pattern": "^(?:" + "|".join(patterns) + ")$", "x-cli-choices": choices}
        return result
    if "Tuple" in classes:
        items = [type_schema(t) for t in kind.types]
        return {"type": "array", "prefixItems": items, "minItems": len(items), "maxItems": len(items)}
    if classes & {"BoolParamType"}:
        result = {"type": "boolean"}
    elif classes & {"IntParamType", "IntRange"}:
        result = {"type": "integer"}
    elif classes & {"FloatParamType", "FloatRange"}:
        result = {"type": "number"}
    elif classes & {"StringParamType", "Path", "TyperPath", "UUIDParameterType", "DateTime"}:
        result = {"type": "string"}
        if "DateTime" in classes:
            result["x-cli-formats"] = list(kind.formats)
    else:
        raise CatalogError(f"Unsupported CLI type: {type(kind).__module__}.{type(kind).__name__}")
    if not getattr(kind, "clamp", False):
        for attr, closed, opened in [("min", "minimum", "exclusiveMinimum"), ("max", "maximum", "exclusiveMaximum")]:
            limit = getattr(kind, attr, None)
            if limit is not None:
                result[opened if getattr(kind, f"{attr}_open", False) else closed] = limit
    return result


@dataclass
class Parameter:
    key: str
    scope: tuple[str, ...]
    click: Any
    schema: dict[str, Any]

    @property
    def option(self):
        return hasattr(self.click, "is_flag")

    def inventory(self):
        p = self.click
        return {
            "name": self.key,
            "cli_name": p.name,
            "scope": list(self.scope),
            "aliases": list(p.opts),
            "secondary_aliases": list(p.secondary_opts),
            "type": type(p.type).__name__,
            "schema": self.schema,
            "default": _value(p.default),
            "required": p.required,
            "multiple": p.multiple,
            "nargs": p.nargs,
            "is_flag": getattr(p, "is_flag", False),
            "is_eager": p.is_eager,
            "callback": bool(p.callback),
            "prompt": getattr(p, "prompt", None),
            "help": getattr(p, "help", None),
        }


def parameter(p, scope, key) -> Parameter:
    schema = type_schema(p.type)
    if getattr(p, "count", False):
        schema = {"type": "integer", "minimum": 0}
    elif getattr(p, "is_flag", False):
        if not getattr(p, "is_bool_flag", False):
            raise CatalogError(f"Nonboolean flag needs an adapter: {key}")
        schema = {"type": "boolean"}
    elif p.nargs != 1 and schema.get("type") != "array":
        schema = {"type": "array", "items": schema}
        if p.nargs != -1:
            schema.update(minItems=p.nargs, maxItems=p.nargs)
    if p.multiple:
        schema = {"type": "array", "items": schema}
        if p.required:
            schema["minItems"] = 1
    default = _value(p.default)
    if default is not None and not p.required:
        schema["default"] = default
    elif default is None and not p.required:
        schema = {"anyOf": [schema, {"type": "null"}], "default": None}
    schema["description"] = getattr(p, "help", None) or f"CLI {p.name}"
    schema["x-cli-options"] = list(p.opts) if hasattr(p, "is_flag") else []
    schema["x-cli-secondary-options"] = list(p.secondary_opts)
    return Parameter(key, scope, p, schema)


def tool_base(path):
    return "fedleave_" + "_".join(re.sub(r"[^a-zA-Z0-9_]", "_", part).lower() for part in path)


@dataclass
class Command:
    name: str
    path: tuple[str, ...]
    parameters: list[Parameter]
    description: str
    schema: dict[str, Any]
    special: str | None = None

    def values(self, supplied):
        """Validate strict JSON types; defaults are CLI metadata, not new rules."""
        if not isinstance(supplied, dict):
            raise CatalogError("Arguments must be a JSON object")

        def finite(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise CatalogError("Non-finite numbers are not CLI inputs")
            if isinstance(value, dict):
                for item in value.values():
                    finite(item)
            elif isinstance(value, (tuple, list)):
                for item in value:
                    finite(item)

        finite(supplied)
        errors = sorted(Draft202012Validator(self.schema).iter_errors(supplied), key=lambda e: str(e.path))
        if errors:
            # jsonschema messages may contain sensitive argument values.
            error = errors[0]
            raise CatalogError(f"Invalid arguments at {'.'.join(map(str, error.path)) or '<root>'}: {error.validator}")
        result = {p.key: _value(p.click.default) for p in self.parameters}
        result.update(supplied)
        return result

    def argv(self, supplied) -> list[str]:
        self.values(supplied)
        aliases = supplied.get("_cli_aliases", {})
        chunks = {self.path[:i]: [] for i in range(len(self.path) + 1)}
        positional = {scope: [] for scope in chunks}
        for p in self.parameters:
            if p.key not in supplied:
                continue
            value = supplied[p.key]
            if value is None:
                continue
            c = p.click
            if not p.option:
                positional[p.scope].extend(_literal(v) for v in _flatten(value))
                continue
            spelling = aliases.get(p.key, c.opts[0])
            if getattr(c, "count", False):
                if value > 10000:
                    raise CatalogError("Flag repetition exceeds the invocation size limit")
                chunks[p.scope].extend([spelling] * value)
            elif c.is_flag:
                if spelling in c.secondary_opts:
                    if value:
                        raise CatalogError(f"Secondary alias for {p.key} requires false")
                    chunks[p.scope].append(spelling)
                elif value:
                    chunks[p.scope].append(spelling)
                elif c.secondary_opts:
                    chunks[p.scope].append(c.secondary_opts[0])
                elif c.default is True:
                    raise CatalogError(f"CLI cannot express false for {p.key}")
            else:
                values = value if c.multiple else [value]
                for item in values:
                    flat = [_literal(v) for v in _flatten(item)]
                    # --option=value prevents a leading dash becoming another option.
                    chunks[p.scope].append(f"{spelling}={flat[0]}")
                    chunks[p.scope].extend(flat[1:])
        if self.special:
            chunks[()][0:0] = [self.special]
        argv = []
        for i in range(len(self.path) + 1):
            scope = self.path[:i]
            argv.extend(chunks[scope])
            if positional[scope]:
                argv.append("--")
                argv.extend(positional[scope])
            if i < len(self.path):
                argv.append(self.path[i])
        return argv

    def inventory(self):
        from .policy import classification

        return {
            "path": list(self.path),
            "tool": self.name,
            "special": self.special,
            "parameters": [p.inventory() for p in self.parameters],
            "json_capable": any("--json" in p.click.opts for p in self.parameters),
            "classification": classification(self.path, self.special),
        }


def _flatten(value):
    if isinstance(value, (list, tuple)):
        return [v for part in value for v in _flatten(part)]
    return [value]


def _literal(value):
    result = str(value)
    if "\0" in result:
        raise CatalogError("NUL is not a CLI argument")
    return result


def discover(root=None) -> dict[str, Command]:
    if root is None:
        from fedleave.cli import app

        root = get_command(app)
    discovered = []

    def walk(command, path, parents):
        params = list(command.params)
        # Click's automatically registered --help is also an execution surface.
        context = command.context_class(command, info_name=command.name)
        help_option = command.get_help_option(context)
        if help_option is not None and not any(p.name == help_option.name for p in params):
            params.append(help_option)
        lineage = parents + [(path, params)]
        children = getattr(command, "commands", {})
        if not children or getattr(command, "invoke_without_command", False):
            generated = []
            names = [p.name for _, ps in lineage for p in ps]
            for scope, ps in lineage:
                for p in ps:
                    key = p.name
                    if names.count(key) > 1:
                        key = "__".join((*scope, key)) if scope else f"root__{key}"
                    generated.append(parameter(p, scope, key))
            properties = {p.key: p.schema for p in generated}
            alias_properties = {
                p.key: {"enum": list(p.click.opts) + list(p.click.secondary_opts)} for p in generated if p.option
            }
            properties["_cli_aliases"] = {
                "type": "object",
                "properties": alias_properties,
                "additionalProperties": False,
                "description": "Optional exact registered option spellings, keyed by logical parameter name.",
            }
            schema = {"type": "object", "properties": properties, "additionalProperties": False}
            required = [p.key for p in generated if p.click.required]
            if required:
                eager = [
                    {"required": [p.key], "properties": {p.key: {"const": True}}}
                    for p in generated
                    if p.click.is_eager and getattr(p.click, "is_bool_flag", False)
                ]
                schema["anyOf"] = [{"required": required}] + eager
            Draft202012Validator.check_schema(schema)
            discovered.append(
                Command(
                    tool_base(path or ("root",)),
                    path,
                    generated,
                    command.help or command.short_help or "FedLeave CLI command",
                    schema,
                )
            )
        for name, child in sorted(children.items()):
            walk(child, path + (name,), lineage)

    walk(root, (), [])
    # The eager version callback is executable without a leaf command.
    for p in root.params:
        if "--version" in p.opts:
            discovered.append(
                Command(
                    "fedleave_version",
                    (),
                    [],
                    "Show the FedLeave CLI version.",
                    {"type": "object", "properties": {}, "additionalProperties": False},
                    "--version",
                )
            )
    groups = {}
    for command in discovered:
        groups.setdefault(command.name, []).append(command)
    result = {}
    for base, commands in groups.items():
        for command in commands:
            if len(commands) > 1 or len(base) > 64:
                digest = hashlib.sha256(json.dumps(command.path).encode()).hexdigest()[:12]
                command.name = f"{base[:50]}_{digest}"
            if command.name in result:
                raise CatalogError(f"Tool name collision: {command.name}")
            result[command.name] = command
    return dict(sorted(result.items()))


def inventory(catalog=None):
    records = [c.inventory() for c in (discover() if catalog is None else catalog).values()]
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {
        "cli_version": __version__,
        "build_commit": __build_commit__,
        "fingerprint": hashlib.sha256(canonical.encode()).hexdigest(),
        "tool_count": len(records),
        "parameter_count": sum(len(r["parameters"]) for r in records),
        "tools": records,
    }
