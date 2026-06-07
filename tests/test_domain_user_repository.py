"""TDD spec for the domain User repository (Task 3).

These tests exercise the pure-SQLAlchemy-2.0 ``SyncUserRepository`` against the
project's in-memory SQLite test database (built from ``DomainBase.metadata`` via
the shared ``db_session`` fixture). They pin three behaviours:

1. create-then-fetch by id / username / username-or-email round-trips,
2. the repository never commits on its own — the caller owns the transaction.
"""

from domain.models.user import User, UserRole
from domain.repositories.users import SyncUserRepository


def test_create_then_fetch_by_id(db_session):
    repo = SyncUserRepository(db_session)
    user = User(
        username="repo_alice",
        password="hashed",
        email="alice@example.com",
        role=UserRole.STUDENT,
    )
    repo.add(user)
    db_session.flush()

    fetched = repo.get_by_id(user.id)
    assert fetched is not None
    assert fetched.id == user.id
    assert fetched.username == "repo_alice"
    assert fetched.role is UserRole.STUDENT


def test_fetch_by_username(db_session):
    repo = SyncUserRepository(db_session)
    user = User(
        username="repo_bob",
        password="hashed",
        email="bob@example.com",
        role=UserRole.TEACHER,
    )
    repo.add(user)
    db_session.flush()

    fetched = repo.get_by_username("repo_bob")
    assert fetched is not None
    assert fetched.id == user.id
    assert fetched.role is UserRole.TEACHER

    assert repo.get_by_username("does_not_exist") is None


def test_fetch_by_username_or_email(db_session):
    repo = SyncUserRepository(db_session)
    user = User(
        username="repo_carol",
        password="hashed",
        email="carol@example.com",
        role=UserRole.STUDENT,
    )
    repo.add(user)
    db_session.flush()

    by_username = repo.get_by_username_or_email("repo_carol")
    by_email = repo.get_by_username_or_email("carol@example.com")

    assert by_username is not None
    assert by_email is not None
    assert by_username.id == user.id == by_email.id

    assert repo.get_by_username_or_email("missing@example.com") is None


def test_repository_does_not_autocommit(db_session):
    """The repository only stages/reads; the caller controls the transaction.

    After ``add`` + ``flush`` (no commit), rolling back the session must discard
    the row entirely — proving the repository never committed behind our back.
    """
    repo = SyncUserRepository(db_session)
    user = User(
        username="repo_dave",
        password="hashed",
        email="dave@example.com",
        role=UserRole.STUDENT,
    )
    repo.add(user)
    db_session.flush()
    assert repo.get_by_username("repo_dave") is not None

    db_session.rollback()

    assert repo.get_by_username("repo_dave") is None
