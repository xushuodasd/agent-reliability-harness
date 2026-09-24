"""Explicit single-attempt budget bridge; not enabled by the live CLI."""
from __future__ import annotations

import json
import math
import re
import urllib.error
from dataclasses import dataclass
from fractions import Fraction

from .budget_ledger import MAX_INTEGER, BudgetLedger
from .provider_http import HttpResponse, Transport, _usage_counts


class BudgetedTransportError(RuntimeError):
    """Safe, non-retryable budget/transport failure without provider payloads."""


def _ceil(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


@dataclass(frozen=True)
class AttemptBudget:
    token_ceiling: int
    input_usd_per_million: str
    output_usd_per_million: str

    def __post_init__(self):
        if type(self.token_ceiling) is not int or not 1 <= self.token_ceiling <= MAX_INTEGER:
            raise ValueError('token ceiling must be a bounded positive integer')
        for rate in (self.input_usd_per_million, self.output_usd_per_million):
            if (not isinstance(rate, str) or len(rate) > 64
                    or re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', rate) is None):
                raise ValueError('rate must be a nonnegative decimal string of at most 64 characters')
        if self.reserved_nanousd > MAX_INTEGER:
            raise ValueError('reservation cost exceeds ledger integer range')

    @property
    def reserved_nanousd(self) -> int:
        return _ceil(self.token_ceiling * max(Fraction(self.input_usd_per_million),
                                             Fraction(self.output_usd_per_million)) * 1000)

    def cost_nanousd(self, prompt: int, completion: int) -> int:
        return _ceil((prompt * Fraction(self.input_usd_per_million)
                      + completion * Fraction(self.output_usd_per_million)) * 1000)


def send_budgeted(request, timeout: float, *, ledger: BudgetLedger, request_id: str,
                  episode_id: str, operation: str, budget: AttemptBudget,
                  transport: Transport) -> bytes | HttpResponse:
    """Reserve durably, invoke one non-retrying transport, settle before delivery."""
    try:
        valid_timeout = type(timeout) in (int, float) and math.isfinite(timeout) and timeout > 0
    except OverflowError:
        valid_timeout = False
    if not valid_timeout:
        raise ValueError('timeout must be finite and positive')
    try:
        admitted = ledger.reserve(request_id, episode_id, operation,
                                  tokens=budget.token_ceiling, nanousd=budget.reserved_nanousd)
    except Exception:
        raise BudgetedTransportError('reservation failed; no send authorized') from None
    if not admitted:
        raise BudgetedTransportError('request already reserved; resend denied')
    try:
        response = transport(request, timeout)
        if isinstance(response, HttpResponse):
            if type(response.status) is not int or not 200 <= response.status < 300:
                raise ValueError('unsuccessful HTTP status')
            body = response.body
        else:
            body = response
        payload = json.loads(body)
        prompt, completion, total = _usage_counts(payload.get('usage'))
        if prompt is None or completion is None or total is None:
            raise ValueError('usage incomplete')
        actual_cost = budget.cost_nanousd(prompt, completion)
        ledger.settle(request_id, tokens=total, nanousd=actual_cost)
    except BaseException as exc:
        try:
            ledger.mark_unknown(request_id)
        except Exception:
            pass  # Keep the durable pending hold when a write cannot be confirmed.
        if not isinstance(exc, Exception):
            raise
        if isinstance(exc, urllib.error.HTTPError):
            try:
                exc.close()
            except Exception:
                pass  # Cleanup must not expose provider error text or enable fallback.
        raise BudgetedTransportError('attempt failed; usage or settlement unconfirmed; do not retry') from None
    if total > budget.token_ceiling or actual_cost > budget.reserved_nanousd:
        raise BudgetedTransportError('recorded usage exceeds reservation; further requests blocked')
    return response
