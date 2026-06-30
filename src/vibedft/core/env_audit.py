"""Runtime environment audit for QE calculations.

Checks hardware, software, and Slurm environment before submitting jobs.
Produces a structured audit report that can be integrated into evidence packs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    # Fallback: try system python site-packages
    try:
        import sys
        for p in ("/usr/lib/python3/dist-packages", "/usr/lib/python3.12/site-packages"):
            if p not in sys.path and os.path.isdir(p):
                sys.path.insert(0, p)
        import psutil
        HAS_PSUTIL = True
    except ImportError:
        HAS_PSUTIL = False


# ── Data structures ──


@dataclass
class AuditItem:
    """Single audit check result."""
    category: str           # "hardware", "software", "scheduler", "pseudo"
    check: str              # e.g. "cpu_physical_vs_logical"
    status: str             # "pass", "warn", "fail", "skip"
    expected: str | None = None
    found: str | None = None
    risk: str = "info"      # "critical", "warning", "info"
    detail: str = ""


@dataclass
class AuditReport:
    """Complete environment audit report."""
    hostname: str = ""
    items: list[AuditItem] = field(default_factory=list)

    @property
    def passed(self) -> list[AuditItem]:
        return [i for i in self.items if i.status == "pass"]

    @property
    def warnings(self) -> list[AuditItem]:
        return [i for i in self.items if i.status == "warn"]

    @property
    def failures(self) -> list[AuditItem]:
        return [i for i in self.items if i.status == "fail"]

    @property
    def critical(self) -> list[AuditItem]:
        return [i for i in self.items if i.risk == "critical"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "summary": {
                "passed": len(self.passed),
                "warnings": len(self.warnings),
                "failures": len(self.failures),
                "critical": len(self.critical),
            },
            "items": [
                {
                    "category": i.category,
                    "check": i.check,
                    "status": i.status,
                    "expected": i.expected,
                    "found": i.found,
                    "risk": i.risk,
                    "detail": i.detail,
                }
                for i in self.items
            ],
        }


# ── Check functions ──


def _check_cpu(report: AuditReport) -> None:
    """Check CPU physical vs logical core count, warn on HT."""
    if not HAS_PSUTIL:
        report.items.append(AuditItem(
            "hardware", "cpu_physical_count", "skip",
            detail="psutil not installed",
        ))
        return

    logical = psutil.cpu_count(logical=True)
    physical = psutil.cpu_count(logical=False)

    report.items.append(AuditItem(
        "hardware", "cpu_logical_count", "pass",
        expected="any", found=str(logical),
        detail=f"{logical} logical CPUs available",
    ))

    if physical and logical and logical > physical:
        report.items.append(AuditItem(
            "hardware", "cpu_hyperthreading", "warn",
            expected=f"{physical} physical cores",
            found=f"{logical} logical CPUs (HT enabled)",
            risk="warning",
            detail=f"Hyperthreading detected: {physical} physical cores → "
                   f"{logical} logical CPUs. Use --ntasks={physical} to avoid "
                   f"cache thrashing and ~40% performance penalty in QE.",
        ))
    else:
        report.items.append(AuditItem(
            "hardware", "cpu_hyperthreading", "pass",
            detail="No hyperthreading detected (or physical=logical)",
        ))

    # CPU model
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if "model name" in line:
                    model = line.split(":", 1)[1].strip()
                    report.items.append(AuditItem(
                        "hardware", "cpu_model", "pass",
                        found=model,
                    ))
                    break
    except Exception:
        pass


def _check_memory(report: AuditReport) -> None:
    """Check total and available memory."""
    if not HAS_PSUTIL:
        return

    mem = psutil.virtual_memory()
    total_gb = mem.total / (1024**3)
    avail_gb = mem.available / (1024**3)

    report.items.append(AuditItem(
        "hardware", "memory_total", "pass",
        found=f"{total_gb:.1f} GB",
    ))

    if avail_gb < 4:
        report.items.append(AuditItem(
            "hardware", "memory_available", "fail",
            expected="> 4 GB",
            found=f"{avail_gb:.1f} GB",
            risk="critical",
            detail="Insufficient memory for QE calculations.",
        ))
    elif avail_gb < 16:
        report.items.append(AuditItem(
            "hardware", "memory_available", "warn",
            expected="> 16 GB recommended",
            found=f"{avail_gb:.1f} GB",
            risk="warning",
        ))
    else:
        report.items.append(AuditItem(
            "hardware", "memory_available", "pass",
            found=f"{avail_gb:.1f} GB available",
        ))


def _check_disk(report: AuditReport, work_dir: str = "/tmp") -> None:
    """Check disk space in working directory."""
    try:
        usage = shutil.disk_usage(work_dir)
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)

        if free_gb < 10:
            report.items.append(AuditItem(
                "hardware", "disk_space", "fail",
                expected="> 10 GB",
                found=f"{free_gb:.1f} GB free",
                risk="critical",
                detail=f"Low disk space in {work_dir}. QE outputs may fill disk.",
            ))
        elif free_gb < 50:
            report.items.append(AuditItem(
                "hardware", "disk_space", "warn",
                expected="> 50 GB recommended",
                found=f"{free_gb:.1f} GB free of {total_gb:.1f} GB",
                risk="warning",
            ))
        else:
            report.items.append(AuditItem(
                "hardware", "disk_space", "pass",
                found=f"{free_gb:.1f} GB free of {total_gb:.1f} GB",
            ))
    except Exception as e:
        report.items.append(AuditItem(
            "hardware", "disk_space", "skip",
            detail=str(e),
        ))


def _check_qe_binary(report: AuditReport, qe_bin: str | None = None) -> None:
    """Check QE binary availability and version."""
    if qe_bin is None:
        pw_path = shutil.which("pw.x")
        if not pw_path:
            candidates = []
            for env_name in ("VIBEDFT_QE_BIN", "QE_BIN"):
                env_value = os.environ.get(env_name)
                if env_value:
                    candidates.append(os.path.join(env_value, "pw.x"))
            candidates.append("/usr/local/bin/pw.x")
            for candidate in candidates:
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    pw_path = candidate
                    break
    else:
        pw_path = os.path.join(qe_bin, "pw.x") if os.path.isdir(qe_bin) else qe_bin

    if not pw_path or not os.path.isfile(pw_path):
        report.items.append(AuditItem(
            "software", "qe_binary", "fail",
            expected="pw.x found in PATH or specified",
            found="not found",
            risk="critical",
            detail="QE pw.x binary not found. Install QE or specify QE_BIN.",
        ))
        return

    if not os.access(pw_path, os.X_OK):
        report.items.append(AuditItem(
            "software", "qe_binary_executable", "fail",
            found=pw_path,
            risk="critical",
            detail=f"{pw_path} exists but is not executable.",
        ))
        return

    report.items.append(AuditItem(
        "software", "qe_binary_path", "pass",
        found=pw_path,
    ))

    # Get version
    try:
        result = subprocess.run(
            [pw_path, "--version"], capture_output=True, text=True, timeout=30,
        )
        for line in result.stdout.splitlines() + result.stderr.splitlines():
            if "PWSCF" in line or "Quantum ESPRESSO" in line or "v." in line:
                report.items.append(AuditItem(
                    "software", "qe_version", "pass",
                    found=line.strip(),
                ))
                break
        else:
            report.items.append(AuditItem(
                "software", "qe_version", "warn",
                detail="Could not parse version from pw.x --version output",
            ))
    except Exception as e:
        report.items.append(AuditItem(
            "software", "qe_version", "warn",
            detail=f"Failed to run pw.x --version: {e}",
        ))


def _check_mkl_libs(report: AuditReport) -> None:
    """Check MKL library availability."""
    ld_paths = os.environ.get("LD_LIBRARY_PATH", "").split(":") + [
        "/opt/intel/oneapi/mkl/2026.0/lib",
        "/usr/lib", "/usr/lib64",
    ]

    mkl_libs = ["libmkl_core", "libmkl_intel_lp64", "libmkl_intel_thread"]
    found_libs = []
    missing_libs = []

    for lib in mkl_libs:
        for suffix in [".so.3", ".so.2", ".so"]:
            lib_name = f"{lib}{suffix}"
            lib_path = None
            for ld_path in ld_paths:
                candidate = os.path.join(ld_path, lib_name)
                if os.path.isfile(candidate):
                    lib_path = candidate
                    break
            if lib_path:
                found_libs.append(lib_name)
                break
        else:
            missing_libs.append(lib)

    if missing_libs:
        report.items.append(AuditItem(
            "software", "mkl_libraries", "fail",
            expected=", ".join(mkl_libs),
            found=f"missing: {', '.join(missing_libs)}",
            risk="critical",
            detail="MKL libraries not found. QE will not start.",
        ))
    else:
        report.items.append(AuditItem(
            "software", "mkl_libraries", "pass",
            found=f"found: {', '.join(found_libs)}",
        ))


def _check_mpi(report: AuditReport) -> None:
    """Check MPI availability."""
    mpi_versions = []

    # Check Intel MPI
    mpi_root = os.environ.get("I_MPI_ROOT", "")
    if mpi_root and os.path.isdir(mpi_root):
        mpi_versions.append(f"Intel MPI at {mpi_root}")

    # Check mpirun
    mpirun = shutil.which("mpirun")
    if mpirun:
        try:
            result = subprocess.run(
                [mpirun, "--version"], capture_output=True, text=True, timeout=10,
            )
            first_line = result.stdout.splitlines()[0] if result.stdout else result.stderr.splitlines()[0] if result.stderr else ""
            mpi_versions.append(first_line.strip() if first_line else f"mpirun at {mpirun}")
        except Exception:
            mpi_versions.append(f"mpirun at {mpirun} (version unknown)")

    if mpi_versions:
        report.items.append(AuditItem(
            "software", "mpi_available", "pass",
            found=" | ".join(mpi_versions),
        ))
    else:
        report.items.append(AuditItem(
            "software", "mpi_available", "fail",
            expected="mpirun or Intel MPI available",
            found="not found",
            risk="critical",
            detail="MPI not found. QE parallel execution will not work.",
        ))


def _check_slurm_partition(report: AuditReport, partition: str = "debug") -> None:
    """Check Slurm partition limits."""
    if not shutil.which("scontrol"):
        report.items.append(AuditItem(
            "scheduler", "slurm_available", "skip",
            detail="scontrol not found — not running under Slurm",
        ))
        return

    try:
        result = subprocess.run(
            ["scontrol", "show", "partition", partition],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            report.items.append(AuditItem(
                "scheduler", "slurm_partition", "fail",
                expected=f"partition '{partition}' exists",
                found="not found or inaccessible",
            ))
            return

        output = result.stdout
        data: dict[str, str] = {}
        for line in output.splitlines():
            for field in line.split():
                if "=" in field:
                    k, v = field.split("=", 1)
                    data[k.strip()] = v.strip()

        max_cpus = data.get("TotalCPUs", "unknown")
        report.items.append(AuditItem(
            "scheduler", "slurm_total_cpus", "pass",
            found=f"{max_cpus} CPUs in partition '{partition}'",
        ))

        max_time = data.get("MaxTime", "unknown")
        report.items.append(AuditItem(
            "scheduler", "slurm_max_time", "pass",
            found=max_time,
        ))

        oversub = data.get("OverSubscribe", "NO")
        if oversub == "NO":
            report.items.append(AuditItem(
                "scheduler", "slurm_oversubscribe", "pass",
                detail="Oversubscription disabled — safe",
            ))
        else:
            report.items.append(AuditItem(
                "scheduler", "slurm_oversubscribe", "warn",
                detail="Oversubscription enabled — risk of resource contention",
            ))

        # Check for thread binding support
        select_type = data.get("SelectTypeParameters", "NONE")
        if select_type == "NONE":
            report.items.append(AuditItem(
                "scheduler", "slurm_core_binding", "warn",
                expected="CR_Core or CR_CPU",
                found="NONE (no core binding)",
                risk="warning",
                detail="Slurm has no core binding configured. Add --cpu-bind=cores "
                       "to srun for better MPI process pinning.",
            ))

    except Exception as e:
        report.items.append(AuditItem(
            "scheduler", "slurm_partition", "skip",
            detail=str(e),
        ))


def _check_pseudopotentials(
    report: AuditReport, pseudo_dir: str = "/tmp/khfcl2/pseudo",
) -> None:
    """Check pseudopotential files exist in the specified directory."""
    if not os.path.isdir(pseudo_dir):
        report.items.append(AuditItem(
            "pseudo", "pseudo_dir", "fail",
            expected=pseudo_dir,
            found="directory not found",
            risk="critical",
            detail=f"Pseudopotential directory {pseudo_dir} does not exist.",
        ))
        return

    upf_files = list(Path(pseudo_dir).glob("*.UPF"))
    if not upf_files:
        report.items.append(AuditItem(
            "pseudo", "pseudo_files", "warn",
            expected=".UPF files found",
            found=f"no UPF files in {pseudo_dir}",
        ))
    else:
        names = [f.name for f in upf_files]
        report.items.append(AuditItem(
            "pseudo", "pseudo_files", "pass",
            found=f"{len(upf_files)} files: {', '.join(sorted(names)[:5])}",
        ))


def _check_env_vars(report: AuditReport) -> None:
    """Check key environment variables for consistency."""
    checks = {
        "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", "not set"),
        "MKL_NUM_THREADS": os.environ.get("MKL_NUM_THREADS", "not set"),
        "I_MPI_PIN_DOMAIN": os.environ.get("I_MPI_PIN_DOMAIN", "not set"),
    }

    for var, val in checks.items():
        if val == "not set":
            report.items.append(AuditItem(
                "environment", f"env_{var.lower()}", "warn",
                expected="set",
                found="not set",
                risk="warning",
                detail=f"{var} not set — may cause oversubscription or poor performance.",
            ))
        else:
            report.items.append(AuditItem(
                "environment", f"env_{var.lower()}", "pass",
                found=val,
            ))


# ── Main entry point ──


def run_environment_audit(
    case_dir: str | Path | None = None,
    qe_bin: str | None = None,
    pseudo_dir: str | None = None,
    slurm_partition: str = "debug",
) -> AuditReport:
    """Run a full environment audit.

    Args:
        case_dir: Optional case directory for pseudo discovery.
        qe_bin: Path to QE bin directory or pw.x binary.
        pseudo_dir: Path to pseudopotential directory.
        slurm_partition: Slurm partition name.

    Returns:
        AuditReport with all check results.
    """
    import platform

    report = AuditReport(hostname=platform.node())

    # High priority
    _check_cpu(report)
    _check_memory(report)
    _check_disk(report)
    _check_qe_binary(report, qe_bin)
    _check_mkl_libs(report)
    _check_mpi(report)

    # Medium priority
    _check_slurm_partition(report, slurm_partition)
    if pseudo_dir:
        _check_pseudopotentials(report, pseudo_dir)
    elif case_dir:
        # Try to discover pseudo_dir from case inputs
        from vibedft.core.qa import discover_input_files
        discovered = discover_input_files(case_dir)
        for si in discovered:
            try:
                from vibedft.parsers.qe_input_parser import parse_qe_input
                qe = parse_qe_input(si.path)
                pd = qe.get_param("control", "pseudo_dir", "")
                if pd:
                    _check_pseudopotentials(report, str(pd))
                    break
            except Exception:
                continue

    # Low priority
    _check_env_vars(report)

    return report
