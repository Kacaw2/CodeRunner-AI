"""Target guard for the single-registry end state (Task 2).

The ``domain/`` package does not exist yet, so this test is a strict
expected-failure: importing ``domain.base`` raises ``ModuleNotFoundError``
inside the test body, which ``xfail(strict=True)`` records as an expected
failure and the suite stays green. After Task 2 establishes
``domain.base.DomainBase`` sharing one registry/metadata with Flask's
``db.Model``, this will flip to a real (xpass -> failing-strict) signal and
must be un-xfailed.
"""

import pytest


@pytest.mark.xfail(strict=True, reason="domain.base.DomainBase not established until Task 2")
def test_flask_and_domain_share_one_registry():
    from app.core.extensions import db
    from domain.base import DomainBase

    assert db.Model.registry is DomainBase.registry
    assert db.Model.metadata is DomainBase.metadata
