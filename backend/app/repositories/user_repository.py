import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.roles import UserRole


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def create(
        self, *, email: str, hashed_password: str, full_name: str, role: UserRole
    ) -> User:
        user = User(
            email=email.lower(),
            hashed_password=hashed_password,
            full_name=full_name,
            role=role,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_full_name(self, *, user: User, full_name: str) -> User:
        user.full_name = full_name
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_password(self, *, user: User, hashed_password: str) -> User:
        user.hashed_password = hashed_password
        self.db.commit()
        self.db.refresh(user)
        return user
