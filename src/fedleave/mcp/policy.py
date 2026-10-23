"""Full CLI authority by default, with optional trusted launch-time restrictions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fedleave.config import get_default_data_dir
from fedleave.storage_guard import same_file


class PolicyError(ValueError):
    """A visible tool invocation exceeds the administrator's permissions."""


# This is a side-effect review of CLI implementations, never tool definitions.
# Unknown additions execute in full_access; restricted profiles require review.
CLASSIFICATIONS = {
    "carryover-reconcile": "conditional",
    "snapshot": "read",
    "accrual-change": "write",
    "activity": "read",
    "add": "write",
    "balance": "read",
    "check-for-updates": "network",
    "compare-leave-balances": "read",
    "correct": "write",
    "expiration-extend": "write",
    "expirations": "read",
    "export-data": "file_output",
    "force-balance": "high_impact",
    "help": "read",
    "holidays": "conditional",
    "import-data": "import",
    "import-wms-http": "import",
    "init": "write",
    "list": "read",
    "month": "read",
    "pay-period": "read",
    "pay-periods": "read",
    "reconcile": "write",
    "rollover": "conditional",
    "set-day": "write",
    "starting-balance set": "write",
    "types": "read",
    "use-or-loose": "read",
    "use-or-lose": "read",
    "validate": "conditional",
    "void": "high_impact",
    "years": "read",
}


def classification(path, special=None):
    kind = "read" if special == "--version" else CLASSIFICATIONS.get(" ".join(path), "unclassified")
    return {
        "kind": kind,
        "startup_migration_possible": False,
        "interactive": path == ("validate",),
        "conditional": kind == "conditional",
    }


def effects(command, values):
    # Catalog fields may be scope-qualified. Side-effect rules use the nearest
    # applicable CLI parameter's logical name, independently of alias spelling.
    values = {**values, **{p.click.name: values.get(p.key) for p in command.parameters}}
    kind = classification(command.path, command.special)["kind"]
    result = {
        "write": kind in {"write", "high_impact", "import", "unclassified"},
        "high_impact": kind in {"high_impact", "unclassified"},
        "network": kind in {"network", "unclassified"},
        "file_output": kind in {"file_output", "unclassified"},
        "import": kind in {"import", "unclassified"},
    }
    if command.special or any(
        p.click.is_eager
        and values.get(p.key)
        and ("--help" in p.click.opts or (p.scope == () and "--version" in p.click.opts))
        for p in command.parameters
    ):
        return dict.fromkeys(result, False)
    if command.path == ("validate",):
        result["write"] = bool(values.get("apply"))
    elif command.path in {("rollover",), ("carryover-reconcile",)}:
        result["write"] = result["high_impact"] = not values.get("preview", False)
    elif command.path == ("holidays",):
        action = values.get("action")
        result["write"] = action != "list"
        result["import"] = action == "import-ics"
    elif command.path == ("import-data",):
        result["high_impact"] = bool(values.get("overwrite"))
    elif command.path == ("init",):
        result["write"] = not values.get("preview", False)
        result["network"] = (
            not values.get("preview", False)
            and not values.get("from_year")
            and values.get("holiday_source") == "opm_ics"
        )
    elif command.path == ("correct",):
        result["write"] = not values.get("preview", False)
    return result


def within(path: Path, root: Path):
    return path == root or path.is_relative_to(root)


def canonical(path):
    return Path(path).expanduser().resolve()


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["full_access", "read_only", "unattended", "confirm_writes"] = "full_access"
    data_dir: Path = Field(default_factory=get_default_data_dir)
    allowed_data_dirs: tuple[Path, ...] = ()
    file_read_roots: tuple[Path, ...] = ()
    file_write_roots: tuple[Path, ...] = ()
    allowed_tools: tuple[str, ...] | None = None
    denied_tools: tuple[str, ...] = ()
    allow_high_impact: bool = False
    allow_imports: bool = False
    allow_file_output: bool = False
    allow_network: bool = False
    executable: Path | None = None
    timeout_seconds: float = Field(default=60, gt=0, le=3600)
    lock_timeout_seconds: float = Field(default=30, ge=0, le=3600)
    max_output_bytes: int = Field(default=1024 * 1024, ge=1024, le=16 * 1024 * 1024)
    audit_log: Path | None = None

    @model_validator(mode="after")
    def unambiguous_full_access(self):
        # Reject even explicit false/empty restrictions: there is no partially
        # restricted full_access profile. Runtime limits/logging remain optional.
        restrictive = self.model_fields_set & {
            "data_dir",
            "allowed_data_dirs",
            "file_read_roots",
            "file_write_roots",
            "allowed_tools",
            "denied_tools",
            "allow_high_impact",
            "allow_imports",
            "allow_file_output",
            "allow_network",
        }
        if self.mode == "full_access" and restrictive:
            raise ValueError(f"full_access is incompatible with restrictive fields: {', '.join(sorted(restrictive))}")
        return self

    @classmethod
    def load(cls, path: Path | None):
        if path is None:
            return cls()
        content = json.loads(path.read_text(encoding="utf-8"))
        # Historically, an explicit policy without a mode selected read_only.
        # Preserve that meaning; only policy-free launches change their default.
        if isinstance(content, dict):
            content.setdefault("mode", "read_only")
        return cls.model_validate_json(json.dumps(content, allow_nan=False), strict=True)

    def authorize(self, command, supplied, *, protected=()):
        values = command.values(supplied)
        effect = effects(command, values)
        if self.mode == "full_access":
            # CLI validation/locking remain authoritative. Do not canonicalize,
            # pin a datastore, scan it, or impose MCP filesystem restrictions.
            return dict(supplied), None, effect
        if classification(command.path, command.special)["kind"] == "unclassified":
            raise PolicyError("Command has no reviewed side-effect classification")
        if command.path == ("holidays",) and values.get("action") not in {"generate", "list", "import-ics"}:
            raise PolicyError("Unclassified holidays action; use generate, list, or import-ics")
        if command.name in self.denied_tools or (
            self.allowed_tools is not None and command.name not in self.allowed_tools
        ):
            raise PolicyError("Tool denied by trusted configuration")
        if effect["write"] or effect["file_output"]:
            if self.mode == "read_only":
                raise PolicyError("read_only policy denies this modifying invocation")
            if self.mode == "confirm_writes":
                raise PolicyError(
                    "confirm_writes denies writes: configure verified client controls or unattended mode locally"
                )
        for effect_name, permission in [
            ("high_impact", self.allow_high_impact),
            ("import", self.allow_imports),
            ("file_output", self.allow_file_output),
            ("network", self.allow_network),
        ]:
            if effect[effect_name] and not permission:
                raise PolicyError(f"Trusted configuration denies {effect_name} operations")
        data_parameters = [p for p in command.parameters if p.click.name == "data_dir"]
        selections = [canonical(values[p.key]) for p in data_parameters if values.get(p.key) is not None]
        if len(set(selections)) > 1:
            raise PolicyError("Conflicting data directories across command scopes are not authorized")
        base = selections[0] if selections else canonical(self.data_dir)
        allowed = [canonical(p) for p in (self.data_dir, *self.allowed_data_dirs)]
        if base not in allowed:
            raise PolicyError("data_dir is not an authorized datastore")
        protected_paths = [canonical(p) for p in protected if p is not None]
        for item in protected_paths:
            if within(item, base):
                raise PolicyError("Datastore overlaps protected configuration or executable files")
        # Reject escaping symlinks, including ancestors of not-yet-created files.
        for folder, directories, files in os.walk(base, followlinks=False):
            for name in [*directories, *files]:
                path = Path(folder) / name
                if not within(path.resolve(), base):
                    raise PolicyError("Datastore contains a path escaping its authorized directory")
                if any(same_file(path.resolve(), p) for p in protected_paths):
                    raise PolicyError("Datastore aliases a protected file")
        result = dict(supplied)
        for p in data_parameters:
            result[p.key] = str(base)
        for p in command.parameters:
            c = p.click
            if c.name == "data_dir" or values.get(p.key) is None:
                continue
            classes = {t.__name__ for t in type(c.type).__mro__}
            is_path = bool(classes & {"Path", "TyperPath", "File"}) or c.name in {"input", "output", "file"}
            if not is_path:
                continue
            roots = self.file_write_roots if c.name == "output" else self.file_read_roots

            def vet_file(value):
                if isinstance(value, list):
                    return [vet_file(item) for item in value]
                path = canonical(value)
                if not roots or not any(within(path, canonical(root)) for root in roots):
                    raise PolicyError(f"{p.key} is outside authorized file roots")
                if any(same_file(path, item) or within(item, path) for item in protected_paths):
                    raise PolicyError("File access targets protected configuration or executables")
                if c.name == "output" and any(within(path, store) for store in allowed):
                    raise PolicyError("Export cannot overwrite a datastore; use a separate export directory")
                return str(path)

            result[p.key] = vet_file(values[p.key])
        return result, base, effect

    def child_environment(self, base, effect):
        env = os.environ.copy()
        # Never inherit stale guards or datastore pinning from another connector.
        # In full_access the CLI must migrate/maintain data exactly as usual.
        for key in tuple(env):
            if key.startswith("FEDLEAVE_MCP_"):
                del env[key]
        if self.mode != "full_access":
            env.update(
                FEDLEAVE_MCP_DATA_DIR=str(base),
                FEDLEAVE_MCP_READ_ONLY="1" if self.mode != "unattended" else "0",
                FEDLEAVE_MCP_WRITE_ROOTS=json.dumps([str(base)] + [str(canonical(p)) for p in self.file_write_roots]),
            )
        if self.mode != "full_access" or "lock_timeout_seconds" in self.model_fields_set:
            env["FEDLEAVE_LOCK_TIMEOUT"] = str(self.lock_timeout_seconds)
        # These cannot be overridden through tools/call arguments.
        env.update(
            PYTHONIOENCODING="utf-8",
            TYPER_STANDARD_TRACEBACK="1",
            _TYPER_STANDARD_TRACEBACK="1",
            NO_COLOR="1",
            TERM="dumb",
        )
        # Authorized unattended reads retain normal CLI maintenance behavior.
        # Other modes enforce the write guard even on nominal read commands.
        return env
