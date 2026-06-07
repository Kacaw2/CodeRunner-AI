"""Guard for the single-registry end state (Task 2).

Task 2 established ``domain.base.DomainBase`` as the sole ``DeclarativeBase``
and bound Flask-SQLAlchemy to it via ``SQLAlchemy(model_class=DomainBase)``.
Flask's ``db.Model`` must therefore share one registry and one metadata with
``DomainBase`` -- no second registry exists.
"""


def test_flask_and_domain_share_one_registry():
    from app.core.extensions import db
    from domain.base import DomainBase

    assert db.Model.registry is DomainBase.registry
    assert db.Model.metadata is DomainBase.metadata
