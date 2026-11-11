# type: ignore
import os
import shlex
from pathlib import Path

from invoke import task

# One org-agnostic image; each org is a service in the stek repo (own data dir and host).
# This repo builds, pushes and restarts the image — services, secrets and routing live in stek.
#
# A registry on the VPS itself keeps a push small (the wheel, ~2 MB) and the pull
# on the host. `docker save | ssh docker load` sent all 213 MB every time.
# Log in to the registry once on both machines: write here, read on the VPS.
REGISTRY = os.getenv("ODAS_DEPLOY_REGISTRY", "")  # e.g. registry.example.nl/team
IMAGE = f"{REGISTRY}/odas" if REGISTRY else "odas"
VPS = os.getenv("ODAS_DEPLOY_VPS", "")  # ssh alias from your ~/.ssh/config
STACK = os.getenv("ODAS_DEPLOY_STACK", "/srv/stack")  # the compose dir on the VPS


@task
def venv(c):
    """Sync dependencies."""
    c.run("uv sync --group dev")


@task
def format(c):
    """Format code."""
    c.run("uv run ruff format src tests tools")


@task
def lint(c):
    """Run linters."""
    c.run("uv run ruff check src tests tools")
    c.run("uv run ruff format --check src tests tools")
    c.run("uv run mypy src tools tests")  # tests are the spec: they get the same rigour


@task
def test(c):
    """Run tests with coverage."""
    c.run("uv run pytest --cov=src --cov-report=term-missing -n auto")
    c.run("node --test 'tests/js/*.test.cjs'")


@task
def ci(c):
    """Run lint and tests."""
    lint(c)
    test(c)
    print("All checks passed!")


def _load_env() -> None:
    """Put .env in the environment, the way start_dev.sh and get_data.sh do.

    Without this a bare `inv check` falls back to the repo root and reports a
    missing schema instead of checking the dir the developer configured.
    """
    path = Path(".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        os.environ.setdefault(key.strip(), os.path.expanduser(value.strip().strip("\"'")))


@task
def check(c):
    """Validate the zaken database; fail if any zaak has problems."""
    _load_env()  # only here: pytest picks its own ODAS_DATA_DIR per test.
    c.run("uv run odas check")


def _latest_tag(c) -> str:
    result = c.run("git describe --tags --abbrev=0", hide=True, warn=True)
    return result.stdout.strip() if result.ok else "v0.0.0"


@task(help={"part": "patch, minor, or major"})
def bump(c, part):
    """Tag a new semver release (git tag is the source of truth)."""
    if part not in ("patch", "minor", "major"):
        raise SystemExit("Usage: inv bump <patch|minor|major>")

    if c.run("git status --porcelain", hide=True).stdout.strip():
        raise SystemExit("Working tree is dirty. Commit or stash changes first.")

    c.run("git fetch --tags", hide=True)
    major, minor, patch = (int(x) for x in _latest_tag(c).lstrip("v").split("."))
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1

    tag = f"v{major}.{minor}.{patch}"
    c.run(f"git tag {tag}")
    c.run(f"git push origin {tag}")
    print(f"Tagged and pushed {tag}.")


def _version(c) -> str:
    return _latest_tag(c).lstrip("v")


@task
def version(c):
    """Print the current version (latest git tag)."""
    print(_version(c))


def _image_tag(c) -> str:
    """The exact commit that is built: `2.3.0`, or `2.3.0-103-gb1b7c65-dirty`.

    One host runs several orgs off one image. A tag that names the commit lets a
    stack move on its own: `latest` moved them all at once, and the second stack
    only found out at its next restart.
    """
    result = c.run("git describe --tags --dirty", hide=True, warn=True)
    return result.stdout.strip().lstrip("v") if result.ok else "0.0.0"


@task(pre=[ci])
def build_image(c):
    """Build the runtime image, tagged with the commit it was built from."""
    tag = _image_tag(c)
    c.run(f"docker build --network=host -t {IMAGE}:{tag} .")
    print(f"Built {IMAGE}:{tag}")


@task(help={"service": "Cycle one service only, e.g. odas-demo"})
def deploy(c, service=""):
    """Build the image, push it to the registry, and restart the odas services.

    Two tags are pushed: the commit tag stays behind for a rollback, and `latest`
    is the tag the stek compose files read. `up -d` recreates a service when the
    pulled image differs, so the services are cycled, not restarted.
    """
    if not (REGISTRY and VPS):
        raise SystemExit("Set ODAS_DEPLOY_REGISTRY and ODAS_DEPLOY_VPS first.")
    build_image(c)
    tag = _image_tag(c)
    c.run(f"docker tag {IMAGE}:{tag} {IMAGE}:latest")

    print(f"Pushing {IMAGE}:{tag}...")
    c.run(f"docker push {IMAGE}:{tag}", pty=True)
    c.run(f"docker push {IMAGE}:latest", pty=True)

    # Every odas service in stek is named `odas-*`, so a new org needs no edit here.
    all_odas = "$(docker compose config --services | grep '^odas-')"
    pick = shlex.quote(service) if service else all_odas
    remote = f"cd {STACK} && S={pick} && docker compose pull $S && docker compose up -d $S"
    c.run(f"ssh -t {VPS} {shlex.quote(remote)}", pty=True)
    print(f"Deployed {IMAGE}:{tag} as latest.")


@task
def clean(c):
    """Preview files to delete (safe mode)."""
    c.run("git clean -nfdx")
    if input("Delete? [y/N] ").lower() == "y":
        c.run("git clean -fdx")
