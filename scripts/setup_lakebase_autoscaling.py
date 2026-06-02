"""Provision Lakebase Autoscaling project, branch, and schema.

Idempotent — safe to run on every deploy. Creates project/branch only if missing,
runs schema SQL using IF NOT EXISTS / ADD COLUMN IF NOT EXISTS (no data overwrite).

Usage:
    uv run python3 scripts/setup_lakebase_autoscaling.py \
        --profile LPT_FREE_EDITION \
        --project-id airport-digital-twin \
        --branch production

Outputs the endpoint host on the last line (for deploy.sh to capture).
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def run_cli(args: list[str], profile: str) -> dict | list | str:
    """Run a databricks CLI command and return parsed JSON output."""
    cmd = ["databricks"] + args + ["--profile", profile, "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"CLI failed: {' '.join(cmd)}\n{result.stderr}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout.strip()


def project_exists(project_id: str, profile: str) -> bool:
    """Check if a Lakebase project exists."""
    result = subprocess.run(
        ["databricks", "postgres", "get-project", f"projects/{project_id}",
         "--profile", profile, "-o", "json"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def create_project(project_id: str, profile: str) -> dict:
    """Create a new Lakebase Autoscaling project."""
    print(f"  Creating Lakebase project: {project_id}", file=sys.stderr)
    result = subprocess.run(
        ["databricks", "postgres", "create-project", project_id,
         "--profile", profile, "-o", "json"],
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create project: {result.stderr}")
    return json.loads(result.stdout)


def branch_exists(project_id: str, branch: str, profile: str) -> bool:
    """Check if a branch exists."""
    result = subprocess.run(
        ["databricks", "postgres", "get-branch",
         f"projects/{project_id}/branches/{branch}",
         "--profile", profile, "-o", "json"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def create_branch(project_id: str, branch: str, profile: str):
    """Create a new branch via the Databricks Python SDK."""
    print(f"  Creating branch: {branch}", file=sys.stderr)
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.postgres import Branch, BranchSpec

    w = WorkspaceClient(profile=profile)
    w.postgres.create_branch(
        parent=f"projects/{project_id}",
        branch_id=branch,
        branch=Branch(spec=BranchSpec(no_expiry=True)),
    )


def wait_for_endpoint(project_id: str, branch: str, profile: str, timeout: int = 120) -> str:
    """Wait for the primary endpoint to be ACTIVE and return its host."""
    parent = f"projects/{project_id}/branches/{branch}"
    deadline = time.time() + timeout

    while time.time() < deadline:
        result = subprocess.run(
            ["databricks", "postgres", "list-endpoints", parent,
             "--profile", profile, "-o", "json"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            endpoints = json.loads(result.stdout)
            for ep in endpoints:
                status = ep.get("status", {})
                if status.get("current_state") == "ACTIVE":
                    host = status.get("hosts", {}).get("host", "")
                    if host:
                        return host
        time.sleep(5)
        print("  Waiting for endpoint to become ACTIVE...", file=sys.stderr)

    raise TimeoutError(f"Endpoint not ACTIVE after {timeout}s")


def get_user_email(profile: str) -> str:
    """Get current user email from CLI."""
    result = subprocess.run(
        ["databricks", "current-user", "me", "--profile", profile, "-o", "json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get current user: {result.stderr}")
    return json.loads(result.stdout).get("userName", "")


def generate_credential(endpoint_name: str, profile: str) -> str:
    """Generate OAuth token for Lakebase connection."""
    result = subprocess.run(
        ["databricks", "postgres", "generate-database-credential",
         "--profile", profile,
         "--json", json.dumps({"endpoint": endpoint_name})],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to generate credential: {result.stderr}")
    return json.loads(result.stdout)["token"]


def _split_sql(sql: str) -> list[str]:
    """Split SQL on semicolons, respecting $$-quoted function bodies."""
    stmts = []
    current = []
    in_dollar = False
    for line in sql.split("\n"):
        stripped = line.strip()
        if stripped.startswith("--") and not current:
            continue
        if "$$" in line:
            count = line.count("$$")
            if count % 2 == 1:
                in_dollar = not in_dollar
        current.append(line)
        if not in_dollar and stripped.endswith(";"):
            stmt = "\n".join(current).strip()
            if stmt and stmt != ";":
                stmts.append(stmt.rstrip(";"))
            current = []
    if current:
        stmt = "\n".join(current).strip()
        if stmt and stmt != ";":
            stmts.append(stmt.rstrip(";"))
    # Filter out comment-only fragments
    return [s for s in stmts if any(l.strip() and not l.strip().startswith("--") for l in s.split("\n"))]


def run_schema_sql(host: str, user: str, token: str, schema_file: Path):
    """Run schema SQL against Lakebase. All statements are idempotent.

    Executes each statement individually so that non-critical failures
    (e.g. COMMENT ON a table owned by another role) don't abort the whole schema.
    """
    import psycopg2

    conn = psycopg2.connect(
        host=host, port=5432, dbname="databricks_postgres",
        user=user, password=token, sslmode="require",
    )
    conn.autocommit = True
    cur = conn.cursor()

    sql = schema_file.read_text()
    statements = _split_sql(sql)

    skipped = 0
    for stmt in statements:
        try:
            cur.execute(stmt)
        except psycopg2.errors.InsufficientPrivilege:
            # Non-critical: COMMENT ON or ALTER on tables owned by another role
            skipped += 1
            conn.rollback()  # reset transaction state after error
        except psycopg2.errors.DuplicateObject:
            # Index/constraint already exists
            skipped += 1
            conn.rollback()

    if skipped:
        print(f"  Note: {skipped} statement(s) skipped (insufficient privilege or duplicate)", file=sys.stderr)

    # Report created tables
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' ORDER BY table_name"
    )
    tables = [row[0] for row in cur.fetchall()]
    print(f"  Schema applied: {len(tables)} table(s) in public schema", file=sys.stderr)

    # Grant public access (so app SP can read/write without explicit role)
    for grant_sql in [
        "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO PUBLIC",
        "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO PUBLIC",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO PUBLIC",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO PUBLIC",
    ]:
        try:
            cur.execute(grant_sql)
        except psycopg2.errors.InsufficientPrivilege:
            conn.rollback()

    cur.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Provision Lakebase Autoscaling")
    parser.add_argument("--profile", required=True, help="Databricks CLI profile")
    parser.add_argument("--project-id", required=True, help="Lakebase project ID")
    parser.add_argument("--branch", default="production", help="Branch name")
    parser.add_argument("--schema-sql", default="scripts/lakebase_schema.sql",
                        help="Path to schema SQL file")
    args = parser.parse_args()

    schema_path = Path(args.schema_sql)
    if not schema_path.exists():
        print(f"ERROR: Schema file not found: {schema_path}", file=sys.stderr)
        sys.exit(1)

    # Step 1: Ensure project exists
    if project_exists(args.project_id, args.profile):
        print(f"  Project '{args.project_id}' exists", file=sys.stderr)
    else:
        create_project(args.project_id, args.profile)
        print(f"  Project '{args.project_id}' created", file=sys.stderr)

    # Step 2: Ensure branch exists
    if args.branch == "production":
        print(f"  Branch 'production' (default, auto-created)", file=sys.stderr)
    elif branch_exists(args.project_id, args.branch, args.profile):
        print(f"  Branch '{args.branch}' exists", file=sys.stderr)
    else:
        create_branch(args.project_id, args.branch, args.profile)

    # Step 3: Wait for endpoint
    print(f"  Checking endpoint status...", file=sys.stderr)
    host = wait_for_endpoint(args.project_id, args.branch, args.profile)
    print(f"  Endpoint ACTIVE: {host}", file=sys.stderr)

    # Step 4: Run schema migration
    endpoint_name = f"projects/{args.project_id}/branches/{args.branch}/endpoints/primary"
    user = get_user_email(args.profile)
    token = generate_credential(endpoint_name, args.profile)
    run_schema_sql(host, user, token, schema_path)

    # Output host on stdout (captured by deploy.sh)
    print(host)


if __name__ == "__main__":
    main()
