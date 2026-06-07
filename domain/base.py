from sqlalchemy.orm import DeclarativeBase


class DomainBase(DeclarativeBase):
    """The only mapped-class registry in the application."""
