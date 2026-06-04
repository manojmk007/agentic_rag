"""
orchestrator/steps/step9_risk_control.py
==========================================
Step 9 — Risk Control Gate.

Pre-forwarding safety checks:
  - PII detection in context (email, phone, SSN, credit card)
  - Prompt injection detection in query and context
  - Data contamination detection (placeholder/test data)
  - Context coherence validation
  - Tenant isolation (stub for future multi-tenancy)
"""

import re
from typing import Optional

from orchestrator.models.context_models import ContextPackage, RiskAssessment
from orchestrator.config.settings import settings
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)

# ── PII Detection Patterns ───────────────────────────────────

_PII_PATTERNS = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone_us": re.compile(r"\b(\+1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),
    "phone_intl": re.compile(r"\+\d{1,3}[-.\s]?\d{6,14}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "ip_address": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
}

# ── Prompt Injection Patterns ────────────────────────────────

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+)?(?:previous|above|prior)", re.IGNORECASE),
    re.compile(r"forget\s+(?:everything|all)\s+(?:you|i)\s+(?:said|told)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:a|an)\s+", re.IGNORECASE),
    re.compile(r"act\s+as\s+(?:if|though)\s+you\s+are", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"\[INST\]|\[/INST\]|<\|system\|>|<\|user\|>", re.IGNORECASE),
    re.compile(r"(?:do\s+not|don'?t)\s+follow\s+(?:the|your)\s+(?:rules|guidelines)", re.IGNORECASE),
    re.compile(r"reveal\s+(?:your|the)\s+(?:system|initial)\s+prompt", re.IGNORECASE),
    re.compile(r"output\s+(?:your|the)\s+(?:instructions|system\s+prompt)", re.IGNORECASE),
]

# ── Data Contamination Patterns ──────────────────────────────

_CONTAMINATION_PATTERNS = [
    re.compile(r"lorem\s+ipsum", re.IGNORECASE),
    re.compile(r"foo\s*bar\s*baz", re.IGNORECASE),
    re.compile(r"test\s*data\s*placeholder", re.IGNORECASE),
    re.compile(r"TODO|FIXME|HACK|XXX", re.IGNORECASE),
    re.compile(r"<\?(?:php|xml)|<script|javascript:", re.IGNORECASE),
]


@track_latency("step9_risk_control")
async def assess_risk(
    query: str,
    context_package: ContextPackage,
    tenant_id: Optional[str] = None,
) -> RiskAssessment:
    """
    Step 9: Run all safety checks on the query and context package.

    Returns a RiskAssessment indicating whether it's safe to proceed.
    """
    if not settings.risk_control_enabled:
        return RiskAssessment(
            safe=True,
            reasoning="risk_control_disabled",
        )

    flags: list[str] = []
    pii_detected: list[str] = []
    injection_detected = False
    blocked = False
    reasoning_parts: list[str] = []

    # ── Collect all text to scan ─────────────────────────────
    all_text = _collect_text(query, context_package)

    # ── Check 1: PII Detection ───────────────────────────────
    for pii_type, pattern in _PII_PATTERNS.items():
        if pattern.search(all_text):
            pii_detected.append(pii_type)
            flags.append(f"pii_{pii_type}")

    if pii_detected:
        reasoning_parts.append(f"PII detected: {', '.join(pii_detected)}")

    # ── Check 2: Prompt Injection ────────────────────────────
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(query):
            injection_detected = True
            flags.append("prompt_injection_in_query")
            reasoning_parts.append("Prompt injection detected in query")
            blocked = True  # Block injected queries
            break

    if not injection_detected:
        # Also check context for injection (data poisoning)
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(all_text):
                injection_detected = True
                flags.append("prompt_injection_in_context")
                reasoning_parts.append("Prompt injection detected in context data")
                break  # Flag but don't block (context poisoning is less critical)

    # ── Check 3: Data Contamination ──────────────────────────
    for pattern in _CONTAMINATION_PATTERNS:
        if pattern.search(all_text):
            flags.append("data_contamination")
            reasoning_parts.append("Potential test/placeholder data detected in context")
            break

    # ── Check 4: Context Coherence ───────────────────────────
    if context_package.retrieved_evidence:
        coherence_ok = _check_coherence(context_package.retrieved_evidence)
        if not coherence_ok:
            flags.append("low_coherence")
            reasoning_parts.append("Context text appears incoherent or corrupted")

    # ── Check 5: Tenant Isolation (stub) ─────────────────────
    if tenant_id:
        # Future: verify all evidence belongs to this tenant
        reasoning_parts.append(f"tenant_id={tenant_id} (isolation check: stub)")

    # ── Determine safety verdict ─────────────────────────────
    safe = not blocked and not pii_detected

    reasoning = " | ".join(reasoning_parts) if reasoning_parts else "all_checks_passed"

    assessment = RiskAssessment(
        safe=safe,
        flags=flags,
        pii_detected=pii_detected,
        injection_detected=injection_detected,
        blocked=blocked,
        reasoning=reasoning,
    )

    if flags:
        logger.warning(
            "risk_flags_raised",
            flags=flags,
            pii=pii_detected,
            injection=injection_detected,
            blocked=blocked,
        )
    else:
        logger.info("risk_assessment_clear")

    return assessment


def _collect_text(query: str, package: ContextPackage) -> str:
    """Collect all text from query and context package for scanning."""
    parts = [query]

    for turn in package.conversation_context:
        parts.append(str(turn.get("content", "")))

    for evidence in package.retrieved_evidence:
        parts.append(str(evidence.get("text", "")))

    for memory in package.memory_context:
        parts.append(str(memory.get("answer", "")))
        parts.append(str(memory.get("query", "")))

    return " ".join(parts)


def _check_coherence(evidence: list[dict]) -> bool:
    """
    Basic coherence check on evidence text.
    Flags if text appears to be garbage or heavily corrupted.
    """
    for e in evidence[:5]:
        text = e.get("text", "")
        if not text:
            continue

        # Check for excessive special characters
        alpha_ratio = sum(c.isalpha() or c.isspace() for c in text) / max(len(text), 1)
        if alpha_ratio < 0.5:
            return False

        # Check for repeated character sequences
        if any(c * 10 in text for c in "abcdefghijklmnopqrstuvwxyz0123456789"):
            return False

    return True


import time


async def step9_risk_control_node(state: dict) -> dict:
    """LangGraph node for Step 9: Risk Control Gate."""
    t0 = time.perf_counter()
    risk = await assess_risk(state["query"], state["context_package"], state["tenant_id"])
    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "risk": risk,
        "step_timings": {"step9_risk_control": elapsed}
    }


