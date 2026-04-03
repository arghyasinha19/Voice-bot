"""
salesforce/maya_tool.py
-----------------------
Pipecat-compatible tool definitions for Salesforce Lead creation in Maya's pipeline.

Conversation Flow (strict sequential collection):
  ┌─────────────────────────────────────────────────────────────────────┐
  │ 1. Maya detects sales/callback intent                               │
  │    → calls capture_lead_interest(intent_label, user_text, ...)      │
  │                                                                     │
  │ 2. Tool checks collection state for this session:                   │
  │    NEED_NAME     → Maya asks: "May I have your name?"               │
  │    NEED_CONTACT  → Maya asks: "Your phone number or email, please?" │
  │    NEED_CONSENT  → Maya asks: "Shall I register you?" (say yes/no)  │
  │                                                                     │
  │ 3. As user provides each piece, Maya calls capture_lead_interest    │
  │    again with the newly extracted field(s).                         │
  │                                                                     │
  │ 4. Once data complete + user says "yes"                             │
  │    → Maya calls confirm_lead_creation(session_id)                   │
  │    → Lead is created in Salesforce                                  │
  └─────────────────────────────────────────────────────────────────────┘

Register in pipeline.py:
    from src.salesforce.maya_tool import (
        capture_lead_interest,
        confirm_lead_creation,
        SALESFORCE_LEAD_TOOLS,
    )
    llm.register_direct_function(capture_lead_interest)
    llm.register_direct_function(confirm_lead_creation)
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional

from loguru import logger

from .lead_manager import LeadData, LeadManager, classify_intent


# ---------------------------------------------------------------------------
# Collection State Machine
# ---------------------------------------------------------------------------

class CollectionState(str, Enum):
    """
    Tracks where we are in the sequential data collection flow.
    Transitions: NEED_NAME → NEED_CONTACT → NEED_CONSENT → COMPLETE
    """
    NEED_NAME    = "need_name"      # Still waiting for the user's name
    NEED_CONTACT = "need_contact"   # Have name, still need email or phone
    NEED_CONSENT = "need_consent"   # Have name + contact, waiting for explicit yes/no
    COMPLETE     = "complete"       # Lead created — terminal state


def _compute_state(lead: LeadData) -> CollectionState:
    """Derive the correct collection state purely from the lead's current data."""
    # Accept either first_name OR last_name — many users give only one name
    has_name = bool(lead.first_name or lead.last_name)
    if not has_name:
        return CollectionState.NEED_NAME
    if not lead.is_contact_reachable():
        return CollectionState.NEED_CONTACT
    if not lead.consent_given:
        return CollectionState.NEED_CONSENT
    return CollectionState.COMPLETE


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_lead_manager = LeadManager()

# In-flight lead store keyed by session_id.
# Production deployments should use Redis or attach state to the transport session.
_pending_leads: Dict[str, LeadData] = {}


# ---------------------------------------------------------------------------
# Session Control
# ---------------------------------------------------------------------------

def clear_session_data(session_id: str):
    """
    Call this when a session ends to purge any incomplete lead data 
    from memory, preventing memory leaks and data pollution.
    """
    if session_id in _pending_leads:
        logger.debug(f"[clear_session_data] Purging stale lead data for session {session_id}")
        _pending_leads.pop(session_id, None)


# ---------------------------------------------------------------------------
# Tool 1: capture_lead_interest
# ---------------------------------------------------------------------------

async def capture_lead_interest(params, **kwargs):
    """
    Call this tool when the user shows purchase intent or requests a callback.
    This tool drives the ENTIRE collection flow — call it repeatedly as the user
    provides each piece of information (name, then contact details).
    Do NOT call this for general product questions or troubleshooting.
    """
    try:
        # ── Extract all arguments from kwargs ────────────────────────────────────
        intent_label:     str           = kwargs.get("intent_label", "")
        user_text:        str           = kwargs.get("user_text", "")
        first_name:       Optional[str] = kwargs.get("first_name")
        last_name:        Optional[str] = kwargs.get("last_name")
        company:          Optional[str] = kwargs.get("company")
        email:            Optional[str] = kwargs.get("email")
        phone:            Optional[str] = kwargs.get("phone")
        product_interest: Optional[str] = kwargs.get("product_interest")
        session_id:       str           = kwargs.get("session_id", "default")

        logger.info(
            f"[capture_lead_interest] session={session_id} intent='{intent_label}' "
            f"name='{first_name} {last_name}' email='{email}' phone='{phone}'"
        )

        # ── Gate: skip for pure informational intent ─────────────────────────────
        intent = classify_intent(intent_label, user_text)
        from .lead_manager import LeadIntent
        if intent == LeadIntent.INFORMATIONAL:
            await params.result_callback(
                "I'm happy to answer any questions about Dyson products. "
                "Just let me know what you'd like to know!"
            )
            return

        # ── Retrieve or initialise pending lead ──────────────────────────────────
        lead = _pending_leads.get(session_id)

        if lead is None:
            lead = LeadData(consent_given=False)
            _pending_leads[session_id] = lead

        # ── Merge newly extracted fields into the lead (never overwrite with None) ─
        if first_name:
            lead.first_name = first_name
        if last_name:
            lead.last_name = last_name
        if company:
            lead.company = company
        if email:
            lead.email = email
        if phone:
            lead.phone = phone
        if product_interest:
            lead.product_interest = product_interest
        if user_text:
            lead.intent_summary = user_text   # keep most recent context

        # ── Determine next step using the state machine ──────────────────────────
        state = _compute_state(lead)
        logger.debug(f"[capture_lead_interest] session={session_id} → state={state.value}")

        if state == CollectionState.NEED_NAME:
            # Priority 1: get a name before anything else
            product_str = f" about the {lead.product_interest}" if lead.product_interest else ""
            await params.result_callback(
                f"I'd be happy to connect you with a Dyson specialist{product_str}! "
                "To get started, may I have your name please?"
            )
            return {"status": "collecting_name", "session_id": session_id}

        elif state == CollectionState.NEED_CONTACT:
            # Priority 2: name collected — now get a contact channel
            first = lead.first_name or lead.last_name
            await params.result_callback(
                f"Thank you, {first}! "
                "Could I get your phone number or email address so our team can reach you?"
            )
            return {"status": "collecting_contact", "session_id": session_id}

        elif state == CollectionState.NEED_CONSENT:
            # Priority 3: have name + contact — ask for explicit consent
            first = lead.first_name or lead.last_name
            contact_preview = lead.email or lead.phone
            await params.result_callback(
                f"Perfect, {first}! I have your contact as {contact_preview}. "
                "Would you like me to share these details with our Dyson sales team "
                "so they can reach out to you? Just say yes or no."
            )
            return {"status": "waiting_for_consent", "session_id": session_id}

        else:
            # Shouldn't normally reach here — state is COMPLETE but consent not set
            await params.result_callback("I already have your registration on file. Is there anything else I can help you with?")
            return {"status": "complete_already", "session_id": session_id}

    except Exception as e:
        logger.error(f"Maya Tool Error: capture_lead_interest failed: {e}")
        await params.result_callback(
            "I'm actually having a little trouble with my lead registry at the moment. "
            "But I can still assist with any of your Dyson product questions!"
        )
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Tool 2: confirm_lead_creation
# ---------------------------------------------------------------------------

async def confirm_lead_creation(params, **kwargs):
    """
    Call this tool ONLY when the user explicitly says yes to being contacted
    (e.g. 'yes', 'sure', 'go ahead', 'please do').
    This finalises lead creation in Salesforce. All required data (name + contact)
    must already have been collected via capture_lead_interest before calling this.
    """

    session_id: str           = kwargs.get("session_id", "default")
    user_text:            Optional[str] = kwargs.get("user_text")
    conversation_summary: Optional[str] = kwargs.get("conversation_summary")

    try:
        logger.info(f"[confirm_lead_creation] session={session_id}")

        lead = _pending_leads.get(session_id)

        # ── Guard: no pending lead ───────────────────────────────────────────────
        if lead is None:
            logger.warning(f"[confirm_lead_creation] No pending lead for session {session_id}")
            await params.result_callback(
                "I don't have a pending registration for this session. "
                "Could you tell me your name and how you'd like to be contacted?"
            )
            return

        # ── Guard: re-validate data completeness ─────────────────────────────────
        # This is a safety net; data should be complete before consent was offered.
        state = _compute_state(lead)

        if state == CollectionState.NEED_NAME:
            logger.warning(f"[confirm_lead_creation] Name still missing — session={session_id}")
            await params.result_callback(
                "Before I register you, could I get your name please?"
            )
            return

        if state == CollectionState.NEED_CONTACT:
            logger.warning(f"[confirm_lead_creation] Contact still missing — session={session_id}")
            first = lead.first_name or lead.last_name
            await params.result_callback(
                f"Thanks, {first}! I still need your phone number or email address to register you."
            )
            return

        # ── All checks passed: mark consent and create lead ──────────────────────
        lead.consent_given = True

        result = await _lead_manager.process(
            intent_label="strong_sales",
            lead=lead,
            user_text=user_text,
            conversation_summary=conversation_summary,
        )

        # Clean up session state regardless of outcome
        _pending_leads.pop(session_id, None)

        if result.success:
            first = lead.first_name or lead.last_name or "there"
            
            if result.is_duplicate:
                logger.info(f"[confirm_lead_creation] Duplicate found — session={session_id}")
                await params.result_callback(
                    f"It looks like you're already in our system, {first}! "
                    "Not to worry — I've updated your interest, and a specialist will be in touch soon. "
                    "Is there anything else I can help you with today?"
                )
                return {"status": "success_duplicate", "session_id": session_id}
            else:
                logger.success(f"[confirm_lead_creation] Lead created — SF ID: {result.record_id} | session={session_id}")
                await params.result_callback(
                    f"Wonderful, {first}! Your details have been registered with our Dyson sales team. "
                    f"Your reference number is {result.record_id}. "
                    "A specialist will be in touch shortly. "
                    "Is there anything else I can help you with today?"
                )
                return {"status": "success_created", "session_id": session_id, "record_id": result.record_id}
        else:
            logger.error(f"[confirm_lead_creation] Failed — {result.error} | session={session_id}")
            await params.result_callback(
                "I'm sorry, I encountered a problem registering your details. "
                "Please call our Dyson India helpline or visit dyson.in for assistance."
            )
            return {"status": "error", "error": result.error}
    except Exception as e:
        logger.error(f"Maya Tool Error: confirm_lead_creation failed: {e}")
        # Clean up problematic session state
        _pending_leads.pop(session_id, None)
        await params.result_callback(
            "I'm sorry, I encountered a problem during registration. "
            "Please visit dyson.in or contact our support team directly for help. "
            "Is there anything else I can assist you with today?"
        )
        return {"status": "exception", "message": str(e)}


# ---------------------------------------------------------------------------
# Tool schema definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

CAPTURE_LEAD_TOOL = {
    "type": "function",
    "function": {
        "name": "capture_lead_interest",
        "description": (
            "Call this tool when the user shows purchase intent, requests a callback, "
            "or asks to speak with the Dyson sales team. Also call it again each time "
            "the user provides their name or contact details during the collection flow. "
            "Do NOT call for general product questions or troubleshooting queries."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "intent_label": {
                    "type": "string",
                    "description": (
                        "Classified intent. One of: 'purchase_inquiry', 'callback_request', "
                        "'sales_request', 'soft_interest', 'informational'."
                    ),
                },
                "user_text": {
                    "type": "string",
                    "description": "The raw user utterance that triggered or continued this flow.",
                },
                "first_name": {
                    "type": "string",
                    "description": "User's first name if mentioned in the conversation.",
                },
                "last_name": {
                    "type": "string",
                    "description": "User's last name or surname if mentioned.",
                },
                "company": {
                    "type": "string",
                    "description": "Company or organisation name, if provided.",
                },
                "email": {
                    "type": "string",
                    "description": "User's email address if provided.",
                },
                "phone": {
                    "type": "string",
                    "description": "User's phone number if provided.",
                },
                "product_interest": {
                    "type": "string",
                    "description": "The specific Dyson product the user is interested in.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Unique session identifier for this conversation.",
                },
            },
            "required": ["intent_label", "user_text", "session_id"],
        },
    },
}

CONFIRM_LEAD_TOOL = {
    "type": "function",
    "function": {
        "name": "confirm_lead_creation",
        "description": (
            "Call this tool ONLY when the user explicitly agrees to be contacted "
            "by the Dyson sales team (e.g. 'yes', 'sure', 'go ahead', 'please do'). "
            "Only call this AFTER capture_lead_interest has confirmed that name and "
            "contact details are already collected. This finalises the Salesforce lead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The same session_id used in capture_lead_interest.",
                },
                "user_text": {
                    "type": "string",
                    "description": "The user's consent utterance (e.g. 'yes, go ahead').",
                },
                "conversation_summary": {
                    "type": "string",
                    "description": "A concise 1-2 sentence summary of the entire conversation so far (products discussed, specific interests, user needs).",
                },
            },
            "required": ["session_id", "user_text", "conversation_summary"],
        },
    },
}

# Convenience list for bulk registration in pipeline.py
SALESFORCE_LEAD_TOOLS = [CAPTURE_LEAD_TOOL, CONFIRM_LEAD_TOOL]
