from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password, verify_password
from app.core.security_config import require_strong_password
from app.models.roles import UserRole
from app.models.user import User
from app.repositories.user_repository import UserRepository


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class PublicRoleForbiddenError(Exception):
    pass


class AccountDisabledError(Exception):
    pass


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)

    def register(
        self, *, email: str, password: str, full_name: str, role: UserRole
    ) -> User:
        if role == UserRole.ADMIN:
            raise PublicRoleForbiddenError("Administrator accounts require a secure bootstrap.")
        require_strong_password(password)
        if self.users.get_by_email(email):
            raise EmailAlreadyRegisteredError(email)
        try:
            return self.users.create(
                email=email,
                hashed_password=hash_password(password),
                full_name=full_name,
                role=role,
            )
        except IntegrityError:
            self.db.rollback()
            raise EmailAlreadyRegisteredError(email)


    def authenticate(self, *, email: str, password: str) -> User:
        user = self.users.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError()
        if not user.is_active:
            raise AccountDisabledError()
        return user

    def update_account(self, *, user: User, full_name: str) -> User:
        return self.users.update_full_name(user=user, full_name=full_name)

    def change_password(
        self, *, user: User, current_password: str, new_password: str
    ) -> User:
        if not verify_password(current_password, user.hashed_password):
            raise InvalidCredentialsError()
        require_strong_password(new_password)
        user.auth_version = (user.auth_version or 0) + 1
        return self.users.update_password(
            user=user, hashed_password=hash_password(new_password)
        )
