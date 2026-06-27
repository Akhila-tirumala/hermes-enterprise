"""
Tenant management CLI
Usage:
  python manage_tenant.py create --name "Acme Corp" --slug "acme-corp"
  python manage_tenant.py list
  python manage_tenant.py delete --slug "acme-corp"
"""
import argparse
import os
import subprocess
import sys
from app.database import SessionLocal, init_db, engine
from app.models import Tenant, User, UserRole
from app.auth import hash_password
from sqlalchemy import text

HERMES_IMAGE = os.getenv("HERMES_IMAGE", "hermes_enterprise-hermes-agent")
DATA_DIR = os.getenv("TENANT_DATA_DIR", "/workspace/tenants")


def create_tenant(name: str, slug: str, admin_email: str, admin_password: str):
    db = SessionLocal()

    # ── 1. Check not already exists ──────────────────────────────────────
    if db.query(Tenant).filter(Tenant.slug == slug).first():
        print(f"✗ Tenant '{slug}' already exists")
        db.close()
        sys.exit(1)

    # ── 2. Create tenant record ───────────────────────────────────────────
    tenant = Tenant(name=name, slug=slug)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    print(f"✓ Tenant record created: {slug} ({tenant.id})")

    # ── 3. Create admin user for this tenant ──────────────────────────────
    user = User(
        email=admin_email,
        hashed_password=hash_password(admin_password),
        role=UserRole.admin,
        tenant_id=tenant.id,
    )
    db.add(user)
    db.commit()
    print(f"✓ Admin user created: {admin_email}")

    # ── 4. Create isolated storage folders ───────────────────────────────
    folders = [
        f"{DATA_DIR}/{slug}/memories",
        f"{DATA_DIR}/{slug}/skills",
        f"{DATA_DIR}/{slug}/logs",
        f"{DATA_DIR}/{slug}/sessions",
    ]
    for folder in folders:
        os.makedirs(folder, exist_ok=True)
    print(f"✓ Storage folders created: {DATA_DIR}/{slug}/")

    # ── 5. Spin up a dedicated Hermes container ───────────────────────────
    container_name = f"hermes_{slug.replace('-', '_')}"
    port = _get_next_port(db)

    cmd = [
        "docker", "run", "-d", "--tty", "--interactive",
        "--name", container_name,
        "--network", "hermes_enterprise_default",
        "--restart", "unless-stopped",
        "--env-file", "/home/user11/hermes_enterprise/app/.env",
        "-e", f"TENANT_ID={tenant.id}",
        "-e", f"TENANT_SLUG={slug}",
        "-v", f"/home/user11/hermes_enterprise/data/tenants/{slug}/memories:/workspace/memories",
        "-v", f"/home/user11/hermes_enterprise/data/tenants/{slug}/skills:/workspace/skills",
        "-v", f"/home/user11/hermes_enterprise/data/tenants/{slug}/logs:/workspace/logs",
        "-v", f"/home/user11/hermes_enterprise/app/config.yaml:/workspace/config.yaml:ro",
        HERMES_IMAGE,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"✗ Failed to start container: {result.stderr}")
        db.close()
        sys.exit(1)

    container_id = result.stdout.strip()[:12]
    print(f"✓ Hermes container started: {container_name} ({container_id})")

    # ── 6. Save container info to tenant record ───────────────────────────
    tenant.container_name = container_name
    db.commit()

    db.close()
    print(f"\n{'='*50}")
    print(f"Tenant '{name}' is ready!")
    print(f"  Slug:      {slug}")
    print(f"  Container: {container_name}")
    print(f"  Admin:     {admin_email} / {admin_password}")
    print(f"{'='*50}")
    print("IMPORTANT: Change the admin password after first login!")


def list_tenants():
    db = SessionLocal()
    tenants = db.query(Tenant).all()
    if not tenants:
        print("No tenants found.")
        db.close()
        return

    print(f"\n{'Slug':<20} {'Name':<25} {'Active':<8} {'Container'}")
    print("-" * 70)
    for t in tenants:
        container = getattr(t, 'container_name', 'N/A') or 'N/A'
        print(f"{t.slug:<20} {t.name:<25} {str(t.is_active):<8} {container}")
    db.close()


def delete_tenant(slug: str):
    db = SessionLocal()
    tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
    if not tenant:
        print(f"✗ Tenant '{slug}' not found")
        db.close()
        sys.exit(1)

    # Stop and remove container
    container_name = f"hermes_{slug.replace('-', '_')}"
    subprocess.run(["docker", "stop", container_name], capture_output=True)
    subprocess.run(["docker", "rm", container_name], capture_output=True)
    print(f"✓ Container removed: {container_name}")

    # Deactivate tenant (keep data)
    tenant.is_active = False
    db.commit()
    print(f"✓ Tenant deactivated: {slug}")
    print("  Data folders preserved at: "
          f"/home/user11/hermes_enterprise/data/tenants/{slug}/")
    db.close()


def _get_next_port(db):
    """Find next available port starting from 8100."""
    count = db.query(Tenant).count()
    return 8100 + count


# ── CLI ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Hermes tenant manager")
subparsers = parser.add_subparsers(dest="command")

# create
p_create = subparsers.add_parser("create", help="Create a new tenant")
p_create.add_argument("--name",  required=True, help="Company name e.g. 'Acme Corp'")
p_create.add_argument("--slug",  required=True, help="URL-safe slug e.g. 'acme-corp'")
p_create.add_argument("--email", default=None,  help="Admin email (default: admin@<slug>.com)")
p_create.add_argument("--password", default="changeme123", help="Admin password")

# list
subparsers.add_parser("list", help="List all tenants")

# delete
p_delete = subparsers.add_parser("delete", help="Deactivate a tenant")
p_delete.add_argument("--slug", required=True, help="Tenant slug to deactivate")

args = parser.parse_args()

init_db()

if args.command == "create":
    email = args.email or f"admin@{args.slug}.com"
    create_tenant(args.name, args.slug, email, args.password)

elif args.command == "list":
    list_tenants()

elif args.command == "delete":
    delete_tenant(args.slug)

else:
    parser.print_help()
