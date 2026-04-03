"""
salesforce/lead_manager.py
--------------------------
Conversation decision logic + Lead domain model.

Responsibilities:
  - Classify user intent from Maya's extracted entities/intent output.
  - Gate lead creation behind explicit consent and minimum data checks.
  - Build and submit the Lead payload to Salesforce.
  - Return structured results that Maya's pipeline can act on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from .client import SalesforceClient, CreateRecordResponse, SalesforceAPIError
from src.utils.stats_tracker import stats_tracker


# ---------------------------------------------------------------------------
# Enumerations & Domain Model
# ---------------------------------------------------------------------------

class LeadIntent(str, Enum):
    """
    Classification of the user's intent extracted from the conversation.

    INFORMATIONAL  – User just wants info (product specs, pricing, store locations).
                     No lead is created.

    SOFT_INTEREST  – User has shown mild interest but no explicit purchase signal.
                     Maya should ask for consent before capturing details.

    STRONG_SALES   – User has explicitly asked to be contacted, showed purchase
                     intent, requested a demo, or asked about buying.
                     Lead creation path is activated after consent.

    CALLBACK       – User explicitly requested a callback / follow-up call.
                     Treated as STRONG_SALES.
    """

    INFORMATIONAL = "informational"
    SOFT_INTEREST = "soft_interest"
    STRONG_SALES  = "strong_sales"
    CALLBACK      = "callback"


@dataclass
class LeadData:
    """Entities extracted from the conversation that map to Salesforce Lead fields."""

    # --- Required fields ---
    last_name: Optional[str] = None
    company: Optional[str] = None           # Defaults to "Individual" if not provided

    # --- Contact (at least one required) ---
    email: Optional[str] = None
    phone: Optional[str] = None

    # --- Optional enrichment ---
    first_name: Optional[str] = None
    product_interest: Optional[str] = None  # e.g. "V15 Detect", "Airwrap"
    intent_summary: Optional[str] = None    # Free-text intent description for Description field

    # --- Consent state (managed by pipeline, not extracted) ---
    consent_given: bool = False

    def is_contact_reachable(self) -> bool:
        """At least email or phone must be present."""
        return bool(self.email) or bool(self.phone)

    def has_minimum_fields(self) -> bool:
        """Minimum data required: (FirstName or LastName) + Company + one contact channel."""
        return (
            bool(self.first_name or self.last_name)
            and bool(self.company or True)   # company defaults to "Individual"
            and self.is_contact_reachable()
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        # Accept either first_name or last_name (single-name users are common)
        if not self.first_name and not self.last_name:
            errors.append("At least a first name or last name is required.")
        if not self.is_contact_reachable():
            errors.append("At least an email address or phone number is required.")
        return errors


# ---------------------------------------------------------------------------
# Intent Classification Rules
# ---------------------------------------------------------------------------

# Keywords that signal strong purchase / sales intent
_STRONG_INTENT_KEYWORDS: frozenset[str] = frozenset({
    "buy", "purchase", "order", "pricing", "price", "cost",
    "demo", "demonstration", "trial", "representative", "callback",
    "call me", "contact me", "reach me", "sales team", "speak to someone",
    "interested in buying", "want to buy", "looking to purchase",
    "sign up", "get a quote", "quotation",
})

# Keywords that signal soft interest (browsing, exploring)
_SOFT_INTENT_KEYWORDS: frozenset[str] = frozenset({
    "interested", "curious", "wondering", "thinking about", "considering",
    "tell me more", "more information", "learn more", "explore",
    "compare", "which one", "recommend",
})


def classify_intent(
    intent_label: Optional[str],
    user_text: Optional[str] = None,
) -> LeadIntent:
    """
    Determine LeadIntent from Maya's extracted intent label and/or raw utterance.

    Args:
        intent_label: Structured intent from the NLU layer (e.g. "purchase_inquiry").
        user_text:    The raw user utterance (used as fallback keyword match).

    Returns:
        LeadIntent enum value.
    """
    label = (intent_label or "").lower().strip()
    text  = (user_text or "").lower()

    # Explicit intent labels from the NLU layer
    if label in ("purchase_inquiry", "buy_intent", "sales_request", "callback_request",
                 "strong_sales", "callback"):
        return LeadIntent.STRONG_SALES
    if label in ("product_inquiry", "soft_interest", "browse"):
        return LeadIntent.SOFT_INTEREST
    if label in ("faq", "troubleshooting", "general_info", "informational"):
        return LeadIntent.INFORMATIONAL

    # Fallback: keyword scanning of the raw utterance
    if any(kw in text for kw in _STRONG_INTENT_KEYWORDS):
        return LeadIntent.STRONG_SALES
    if any(kw in text for kw in _SOFT_INTENT_KEYWORDS):
        return LeadIntent.SOFT_INTEREST

    # Default: treat as informational
    return LeadIntent.INFORMATIONAL


# ---------------------------------------------------------------------------
# Decision Gate
# ---------------------------------------------------------------------------

@dataclass
class LeadDecision:
    """Result of the lead creation decision gate."""

    should_create: bool
    reason: str
    ask_for_consent: bool = False        # True → Maya should ask user for consent
    missing_fields: list[str] = field(default_factory=list)


def evaluate_lead_decision(intent: LeadIntent, lead: LeadData) -> LeadDecision:
    """
    Decide whether to create a Salesforce Lead.

    Rules:
    ┌─────────────────────────────────────────────────────────────────────────┐
    │ Intent          │ Action                                                │
    ├─────────────────────────────────────────────────────────────────────────┤
    │ INFORMATIONAL   │ No lead. Just answer the query.                       │
    │ SOFT_INTEREST   │ No lead yet. Ask user for consent first.              │
    │ STRONG_SALES    │ If consent given + data sufficient → create lead.      │
    │ CALLBACK        │ Same as STRONG_SALES.                                 │
    └─────────────────────────────────────────────────────────────────────────┘
    """
    if intent == LeadIntent.INFORMATIONAL:
        return LeadDecision(
            should_create=False,
            reason="Informational intent — no lead required.",
        )

    if intent == LeadIntent.SOFT_INTEREST:
        return LeadDecision(
            should_create=False,
            ask_for_consent=True,
            reason="Soft interest detected — awaiting explicit consent from user.",
        )

    # STRONG_SALES or CALLBACK
    if not lead.consent_given:
        return LeadDecision(
            should_create=False,
            ask_for_consent=True,
            reason="Strong interest detected — consent not yet obtained.",
        )

    validation_errors = lead.validation_errors()
    if validation_errors:
        return LeadDecision(
            should_create=False,
            reason="Minimum data requirements not met.",
            missing_fields=validation_errors,
        )

    return LeadDecision(
        should_create=True,
        reason="Strong intent + consent given + minimum data present.",
    )


# ---------------------------------------------------------------------------
# Lead Manager
# ---------------------------------------------------------------------------

@dataclass
class LeadCreationResult:
    success: bool
    record_id: Optional[str] = None
    is_duplicate: bool = False     # True → Salesforce detected existing matching record
    error: Optional[str] = None
    decision: Optional[LeadDecision] = None


class LeadManager:
    """
    Orchestrates the full lead lifecycle:
      1. Classify intent.
      2. Evaluate the decision gate.
      3. Build the Salesforce payload.
      4. Submit via SalesforceClient.

    Usage:
        manager = LeadManager()
        result = await manager.process(
            intent_label="purchase_inquiry",
            lead=LeadData(
                first_name="Priya",
                last_name="Sharma",
                company="Individual",
                phone="+91-98765-43210",
                product_interest="Dyson V15 Detect",
                intent_summary="Customer wants to buy V15 Detect and requested a callback.",
                consent_given=True,
            ),
            user_text="I want to buy the V15 Detect, please call me back",
        )
    """

    def __init__(self, client: Optional[SalesforceClient] = None) -> None:
        self._client = client or SalesforceClient()

    async def process(
        self,
        intent_label: Optional[str],
        lead: LeadData,
        user_text: Optional[str] = None,
        conversation_summary: Optional[str] = None,
    ) -> LeadCreationResult:
        """
        Main entry point: evaluate intent → gate → create Salesforce Lead.

        Args:
            intent_label: Structured intent string from Maya's NLU (can be None).
            lead:         Populated LeadData object from entity extraction.
            user_text:    Raw user utterance, used for keyword fallback.

        Returns:
            LeadCreationResult with outcome details.
        """
        intent = classify_intent(intent_label, user_text)
        logger.info(f"LeadManager: Classified intent as '{intent.value}'")

        decision = evaluate_lead_decision(intent, lead)
        logger.info(f"LeadManager: Decision → create={decision.should_create} | {decision.reason}")

        if not decision.should_create:
            return LeadCreationResult(
                success=False,
                error=decision.reason,
                decision=decision,
            )

        try:
            payload = self._build_payload(lead, intent, conversation_summary)
            logger.debug(f"LeadManager: Submitting Lead payload: {payload}")

            response: CreateRecordResponse = await self._client.create_record(
                "Lead", payload
            )

            # 3. Audit Logging (Background/Performance-safe)
            stats_tracker.log_lead_audit({
                "session_id": lead.session_id if hasattr(lead, "session_id") else "unknown",
                "record_id": response.record_id,
                "name": f"{lead.first_name or ''} {lead.last_name or ''}".strip(),
                "email": lead.email,
                "phone": lead.phone,
                "product": lead.product_interest,
                "summary": conversation_summary or lead.intent_summary
            })

            return LeadCreationResult(
                success=True,
                record_id=response.record_id,
                decision=decision,
            )

        except SalesforceAPIError as exc:
            if exc.error_code == "DUPLICATES_DETECTED":
                logger.warning(f"LeadManager: Duplicate lead detected for {lead.email or lead.phone}")
                return LeadCreationResult(
                    success=True,      # Treat as soft success, since the user is in the system
                    is_duplicate=True,
                    decision=decision,
                )
            
            logger.error(f"LeadManager: Salesforce API error — {exc}")
            return LeadCreationResult(
                success=False,
                error=str(exc),
                decision=decision,
            )

        except Exception as exc:
            logger.error(f"LeadManager: Lead creation failed — {exc}")
            return LeadCreationResult(
                success=False,
                error=str(exc),
                decision=decision,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_payload(self, lead: LeadData, intent: LeadIntent, conversation_summary: Optional[str] = None) -> Dict[str, Any]:
        """Map LeadData fields to the Salesforce Lead sObject schema."""

        company = lead.company or "Individual"

        # Build the Description with rich context
        description_parts = [
            f"Intent: {intent.value.replace('_', ' ').title()}",
        ]
        
        if conversation_summary:
            description_parts.append(f"Conversation Summary: {conversation_summary}")
        elif lead.intent_summary:
            description_parts.append(f"Summary: {lead.intent_summary}")
        if lead.product_interest:
            description_parts.append(f"Product of Interest: {lead.product_interest}")
        description_parts.append("Source: Dyson Voice Bot (Maya)")

        # Salesforce requires LastName. Fall back to first_name if last_name absent.
        last_name  = lead.last_name or lead.first_name or "Unknown"
        first_name = lead.first_name if lead.last_name else None

        payload: Dict[str, Any] = {
            "LastName":    last_name,
            "Company":     company,
            "LeadSource":  "Web",
            "Status":      "Open - Not Contacted",
            "Description": " | ".join(description_parts),
        }

        if first_name:
            payload["FirstName"] = first_name

        # Contact channels
        if lead.email:
            payload["Email"] = self._sanitize_email(lead.email)
        if lead.phone:
            payload["Phone"] = self._sanitize_phone(lead.phone)

        # Product interest → Industry or custom field (safe default: Industry)
        if lead.product_interest:
            payload["Industry"] = "Technology"      # Salesforce default picklist
            # If your org has a custom field, replace with:
            # payload["Product_Interest__c"] = lead.product_interest

        return payload

    @staticmethod
    def _sanitize_email(email: str) -> str:
        """Strip surrounding whitespace; basic format guard."""
        email = email.strip()
        if not re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError(f"Invalid email format: '{email}'")
        return email

    @staticmethod
    def _sanitize_phone(phone: str) -> str:
        """Normalise phone number to digits + allowed punctuation."""
        # Keep digits, spaces, +, -, (, )
        cleaned = re.sub(r"[^\d\s+\-()]", "", phone).strip()
        if len(re.sub(r"\D", "", cleaned)) < 7:
            raise ValueError(f"Phone number too short: '{phone}'")
        return cleaned
