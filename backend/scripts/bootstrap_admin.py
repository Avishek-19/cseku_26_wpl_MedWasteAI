"""One-time server-side admin bootstrap. NEVER expose via public API.

From backend/: python scripts/bootstrap_admin.py
Requires BOOTSTRAP_ADMIN_EMAIL in local environment, and an interactive password.
"""
from getpass import getpass
from pathlib import Path
import os, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.core.security_config import require_strong_password
from app.models.roles import UserRole
from app.models.user import User


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Provision an authorized administrator from the server console")
    parser.add_argument("--additional-admin", action="store_true", help="Provision a separate administrator for independent receipt review")
    args = parser.parse_args()
    email=os.environ.get('BOOTSTRAP_ADMIN_EMAIL','').strip().lower()
    if '@' not in email or len(email)>254:
        raise SystemExit('Set BOOTSTRAP_ADMIN_EMAIL to a dedicated authorized admin email before running')
    password=getpass('New administrator password (not echoed): ')
    confirm=getpass('Confirm password: ')
    if password!=confirm:raise SystemExit('Password confirmation mismatch')
    require_strong_password(password)
    with SessionLocal() as db:
        existing=db.scalar(select(User.id).where(User.role==UserRole.ADMIN).limit(1))
        if existing and not args.additional_admin:raise SystemExit('Admin already exists; use --additional-admin to provision a separate authorized reviewer')
        if db.scalar(select(User.id).where(User.email==email).limit(1)):
            raise SystemExit('Email is already registered; use a new dedicated email')
        db.add(User(email=email,hashed_password=hash_password(password),
            full_name='Authorized Platform Administrator',role=UserRole.ADMIN,
            is_verified=True,is_active=True))
        db.commit()
    print('Administrator account provisioned through local server bootstrap (no password shown).')

if __name__=='__main__':main()
