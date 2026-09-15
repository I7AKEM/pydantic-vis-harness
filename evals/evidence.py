"""Small provenance helpers shared by the existing evaluation runners."""

from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def provenance(cases_path: Path, models: dict, repeats: int = 1) -> dict:
    def git(*args):
        result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    dependencies = {}
    for package in ('pydantic', 'pydantic-ai', 'pydantic-evals', 'duckdb'):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError:
            dependencies[package] = None
    prompts = {}
    for name in ('analyst', 'designer', 'profiler'):
        path = ROOT / 'vis_agent' / name / 'rulebook.md'
        if path.exists():
            prompts[name] = path.read_text(encoding='utf-8')
    return {'created_at': datetime.now(timezone.utc).isoformat(), 'models': models, 'repeats': repeats,
            'cases_sha256': hashlib.sha256(cases_path.read_bytes()).hexdigest(),
            'git_revision': git('rev-parse', 'HEAD'), 'git_dirty': git('status', '--porcelain'),
            'dependencies': dependencies, 'prompts': prompts,
            'token_usage': None, 'cost': None,
            'unavailable': 'Token usage and monetary cost are null unless reported by the provider.'}
