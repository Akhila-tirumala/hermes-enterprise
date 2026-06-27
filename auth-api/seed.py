from app.database import SessionLocal, init_db
from app.models import Tenant, User, UserRole
from app.auth import hash_password

init_db()
db = SessionLocal()

tenant = db.query(Tenant).filter(Tenant.slug == "default").first()
if not tenant:
    tenant = Tenant(name="Default Org", slug="default")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    print(f"✓ Tenant created: {tenant.slug}")
else:
    print(f"  Tenant already exists: {tenant.slug}")

admin = db.query(User).filter(User.email == "admin@example.com").first()
if not admin:
    admin = User(
        email="admin@example.com",
        hashed_password=hash_password("changeme123"),
        role=UserRole.admin,
        tenant_id=tenant.id,
    )
    db.add(admin)
    db.commit()
    print("✓ Admin user created: admin@example.com / changeme123")
else:
    print("  Admin already exists")

db.close()
print("\nDone! Change the admin password after first login.")
