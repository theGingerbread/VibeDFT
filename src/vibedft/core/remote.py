"""Remote execution lifecycle for VibeDFT cases.

Encodes remote host profiles, generates safe scp/rsync transfer commands,
Slurm submission wrappers, and monitors job status.  All remote execution
goes through Slurm — direct DFT binary execution on login nodes is forbidden.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Remote profile model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RemoteHost:
    """A remote HPC host with its paths, constraints, and preferences."""

    name: str
    host: str
    user: str
    root: str
    qe_bin_dir: str
    intel_setvars: str
    preferred_for: list[str] = field(default_factory=list)
    notes: str = ""
    partition: str = "debug"
    max_ntasks: int = 32
    max_concurrent: int = 1
    deprecated_routes: list[str] = field(default_factory=list)

    @property
    def remote_case_root(self) -> str:
        """Default remote path for VibeDFT cases."""
        return f"{self.root}/VibeDFT"


@dataclass
class RemoteRegistry:
    """Collection of known remote hosts loaded from profiles/remotes.yaml."""

    hosts: dict[str, RemoteHost] = field(default_factory=dict)

    @classmethod
    def from_project_root(cls, project_root: Path | str) -> "RemoteRegistry":
        root = Path(project_root)
        remotes_file = root / "config" / "remotes.yaml"
        if not remotes_file.is_file():
            return cls()

        with remotes_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        hosts = {}
        for name, cfg in data.get("remotes", {}).items():
            hosts[name] = RemoteHost(
                name=name,
                host=cfg.get("host", name),
                user=cfg.get("user", name),
                root=cfg.get("root", ""),
                qe_bin_dir=cfg.get("qe_bin_dir", ""),
                intel_setvars=cfg.get("intel_setvars", ""),
                preferred_for=cfg.get("preferred_for", []),
                notes=cfg.get("notes", ""),
                partition=cfg.get("constraints", {}).get("partition", "debug"),
                max_ntasks=cfg.get("constraints", {}).get("max_ntasks", 32),
                max_concurrent=cfg.get("constraints", {}).get("max_concurrent", 1),
                deprecated_routes=cfg.get("deprecated_routes", []),
            )
        return cls(hosts=hosts)

    def get(self, name: str) -> RemoteHost:
        if name not in self.hosts:
            raise KeyError(f"Unknown remote host: {name}. Known: {list(self.hosts)}")
        return self.hosts[name]


# ---------------------------------------------------------------------------
# Transfer exclusions (heavy outputs that should never be transferred)
# ---------------------------------------------------------------------------

HEAVY_OUTPUT_EXCLUDES = [
    "--exclude='out/'",
    "--exclude='out_scf/'",
    "--exclude='out_nscf/'",
    "--exclude='*.save/'",
    "--exclude='_ph0/'",
    "--exclude='*.wfc*'",
    "--exclude='CHGCAR'",
    "--exclude='WAVECAR'",
    "--exclude='elph_dir/'",
    "--exclude='*.xml'",
    "--exclude='*.igk*'",
    "--exclude='*.bfgs'",
]

# DFT binaries that must never appear in remote commands outside Slurm scripts
FORBIDDEN_DIRECT_COMMANDS = [
    "pw.x <",
    "ph.x <",
    "dos.x <",
    "bands.x <",
    "q2r.x <",
    "matdyn.x <",
    "lambda.x <",
    "projwfc.x <",
    "fs.x <",
    "mpirun",
]


# ---------------------------------------------------------------------------
# Transfer plan generation
# ---------------------------------------------------------------------------


@dataclass
class RemotePlan:
    """A sequence of transfer and Slurm operations for a case."""

    case_dir: Path
    host: RemoteHost
    steps: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Remote Plan: {self.case_dir.name} → {self.host.name} ({self.host.host})",
            f"Remote root: {self.host.remote_case_root}",
            "",
        ]
        for i, step in enumerate(self.steps, 1):
            icon = {"push": "⬆", "submit": "▶", "status": "🔍", "pull": "⬇"}.get(
                step.get("action", "?"), "·"
            )
            lines.append(f"  {i}. {icon} [{step.get('action', '?').upper()}] {step.get('description', '')}")
            if step.get("command"):
                lines.append(f"     $ {step['command']}")
        return "\n".join(lines)

    def markdown_log_rows(self) -> str:
        """Generate log rows for logs/calculation.md."""
        rows = []
        for step in self.steps:
            action = step.get("action", "?")
            desc = step.get("description", "")
            cmd = step.get("command", "")
            rows.append(
                f"| pending | {action} | `{cmd}` | pending | {desc} |"
            )
        return "\n".join(rows)


def build_remote_plan(
    case_dir: Path | str,
    host: RemoteHost,
    *,
    case_id: str | None = None,
) -> RemotePlan:
    """Build a transfer and Slurm plan for a case directory.

    The plan includes:
    1. Push input files to remote (rsync with heavy-output excludes)
    2. Submit via sbatch
    3. Check status via squeue/sacct
    4. Pull results back (rsync with excludes)
    """
    d = Path(case_dir).resolve()
    cid = case_id or d.name
    remote_case = f"{host.remote_case_root}/{cid}"

    plan = RemotePlan(case_dir=d, host=host)

    # Step 1: Push inputs (include a post-push script to flatten input/*.in to case root)
    excludes = " ".join(HEAVY_OUTPUT_EXCLUDES)
    ssh_target = f"{host.user}@{host.host}"
    rc_q = shlex.quote(remote_case)   # remote-case path, quoted for remote shell
    remote_dest = f"{host.user}@{host.host}:{remote_case}/"
    flatten_cmd = (
        f"ssh {shlex.quote(ssh_target)} "
        f"\"cd {rc_q} && if [ -d input ]; then for f in input/*.in; do [ -f \\\"\\$f\\\" ] && cp \\\"\\$f\\\" .; done; fi\""
    )
    plan.steps.append(
        {
            "action": "push",
            "description": f"Transfer inputs to {host.name} (+ flatten input/*.in to root)",
            "command": (
                f"rsync -avz {excludes} "
                f"{shlex.quote(str(d) + '/')} {shlex.quote(remote_dest.rstrip('/') + '/')} && "
                f"{flatten_cmd}"
            ),
            "local_path": str(d),
            "remote_path": remote_dest,
            "post_push": "Input files in input/ are copied to case root for Slurm compatibility.",
        }
    )

    # Step 2: Submit Slurm job
    plan.steps.append(
        {
            "action": "submit",
            "description": "Submit Slurm job on remote",
            "command": (
                f"ssh {shlex.quote(ssh_target)} "
                f"\"cd {rc_q} && sbatch job.slurm\""
            ),
            "remote_dir": remote_case,
            "scheduler": "slurm",
            "forbidden": "Direct DFT execution on login node is FORBIDDEN. Use sbatch.",
        }
    )

    # Step 3: Monitor
    user_q = shlex.quote(host.user)
    plan.steps.append(
        {
            "action": "status",
            "description": "Check Slurm job status",
            "command": (
                f"ssh {shlex.quote(ssh_target)} "
                f"\"squeue -u {user_q} && sacct -u {user_q} --format=JobID,State,ExitCode\""
            ),
            "poll_advice": (
                "Poll until terminal state (COMPLETED/FAILED/TIMEOUT/CANCELLED). "
                "Do not proceed until job completes."
            ),
        }
    )

    # Step 4: Pull results
    plan.steps.append(
        {
            "action": "pull",
            "description": f"Retrieve results from {host.name}",
            "command": (
                f"rsync -avz {excludes} "
                f"{shlex.quote(ssh_target + ':' + remote_case + '/output/')} "
                f"{shlex.quote(str(d) + '/output/')}"
            ),
            "remote_path": f"{ssh_target}:{remote_case}/output/",
            "local_path": str(d / "output"),
            "warning": "Pull outputs BEFORE any local post-processing.",
        }
    )

    return plan


# ---------------------------------------------------------------------------
# Safety enforcement
# ---------------------------------------------------------------------------


def validate_no_direct_dft_execution(plan: RemotePlan) -> list[str]:
    """Check that no remote command directly executes DFT binaries.

    Returns a list of violation messages (empty = clean).
    """
    violations = []
    for step in plan.steps:
        cmd = step.get("command", "")
        # Allow sbatch wrapper scripts — only flag literal binary execution
        if step.get("action") == "submit":
            continue  # sbatch is the correct path
        for forbidden in FORBIDDEN_DIRECT_COMMANDS:
            if forbidden in cmd:
                violations.append(
                    f"Step '{step.get('action')}': "
                    f"Direct DFT binary '{forbidden}' found in command. "
                    f"All DFT execution must go through Slurm sbatch."
                )
    return violations


# ---------------------------------------------------------------------------
# Log integration
# ---------------------------------------------------------------------------


def append_remote_log(
    case_dir: Path | str,
    step_action: str,
    command: str,
    status: str,
    notes: str = "",
) -> None:
    """Append a remote lifecycle row to the case calculation log."""
    d = Path(case_dir)
    log_path = d / "logs" / "calculation.md"
    if not log_path.is_file():
        return

    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    row = f"| {timestamp} | {step_action} | `{command}` | {status} | {notes} |\n"

    content = log_path.read_text(encoding="utf-8")
    # Insert before the Final Status section
    if "## Final Status" in content:
        content = content.replace("## Final Status", row + "\n## Final Status")
    else:
        content += "\n" + row

    log_path.write_text(content, encoding="utf-8")
