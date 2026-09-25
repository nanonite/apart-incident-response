"""Sandboxed repository root for lifecycle-sensitive registration tests (not a test).

Committed collection outputs and later epic-126 artifacts make real-tree
freshness/absence assertions fail by design (registered output-collision
refusals) and can perturb prior-ID source evidence for older locks. This
helper builds a temporary root containing exactly the inputs the locked
registration recorded at lock time — a ``src`` symlink plus symlinks to every
recorded prior-scan source, the registration file itself, plus caller-supplied
extra pinned inputs — while that registration's own journal/report outputs
are absent. Cleanup is the caller's ``tearDownModule`` responsibility.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path


def build_recorded_sandbox(real_root: Path, registration_rel: str, *,
                           extra_files: tuple[str, ...] = ()) -> Path:
    registration_path = real_root / registration_rel
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    sources = registration["manifest"]["disjointness"]["prior_instance_ids"]["sources"]

    sandbox = Path(tempfile.mkdtemp(prefix="lifecycle-sandbox-"))
    (sandbox / "src").symlink_to(real_root / "src", target_is_directory=True)

    def link(relative: str) -> None:
        target = real_root / relative
        destination = sandbox / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            return
        try:
            destination.symlink_to(target)
        except OSError:
            try:
                destination.write_bytes(target.read_bytes())
            except OSError:
                destination.write_bytes(b"")

    for relative in sources:
        link(relative)
    link(registration_rel)
    for relative in extra_files:
        link(relative)
    return sandbox


def build_v6_sandbox(real_root: Path) -> Path:
    return build_recorded_sandbox(
        real_root, "runs/epic-126/jev-coverage-manifest-preregistration-v6.json")


def destroy_sandbox(sandbox: Path) -> None:
    shutil.rmtree(sandbox, ignore_errors=True)
