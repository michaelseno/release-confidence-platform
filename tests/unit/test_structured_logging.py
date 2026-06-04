import json
import logging
from decimal import Decimal

from packages.core.logging import StructuredLogger


class CapturingLogger(logging.Logger):
    def __init__(self):
        super().__init__("capturing-logger")
        self.messages: list[str] = []

    def log(self, level, msg, *args, **kwargs):  # noqa: ARG002
        self.messages.append(msg)


def test_structured_logger_serializes_decimal_fields():
    logger = CapturingLogger()

    record = StructuredLogger(logger=logger).log(
        "auditFinalization_transition_requested",
        execution_count=Decimal("13"),
        nested={"zero_count": Decimal("0")},
    )

    assert record["execution_count"] == 13
    assert record["nested"]["zero_count"] == 0
    emitted = json.loads(logger.messages[0])
    assert emitted["execution_count"] == 13
    assert emitted["nested"]["zero_count"] == 0
