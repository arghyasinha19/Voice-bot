"""
tests/test_salesforce.py
------------------------
Unit tests for the Salesforce integration layer.

Run with:
    python -m pytest tests/test_salesforce.py -v
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Patch env vars before any module-under-test is imported
# ---------------------------------------------------------------------------
os.environ.setdefault("SF_INSTANCE_URL", "https://test.my.salesforce.com")
os.environ.setdefault("SF_ACCESS_TOKEN", "test_token_abc123")

from src.salesforce.client import (
    SalesforceClient,
    SalesforceAuthError,
    SalesforceAPIError,
    SalesforceNetworkError,
    CreateRecordResponse,
)
from src.salesforce.lead_manager import (
    LeadData,
    LeadIntent,
    classify_intent,
    evaluate_lead_decision,
    LeadManager,
)
from src.salesforce.maya_tool import (
    CollectionState,
    _compute_state,
    _pending_leads,
    capture_lead_interest,
    confirm_lead_creation,
)


# ===========================================================================
# Helpers
# ===========================================================================

def make_params(responses: list) -> MagicMock:
    """Build a mock `params` whose result_callback records all calls."""
    params = MagicMock()
    params.result_callback = AsyncMock(side_effect=lambda msg: responses.append(msg))
    return params


def clear_session(session_id: str):
    _pending_leads.pop(session_id, None)


# ===========================================================================
# 1. CollectionState machine
# ===========================================================================

class TestComputeState:

    def test_no_data_yields_need_name(self):
        lead = LeadData()
        assert _compute_state(lead) == CollectionState.NEED_NAME

    def test_has_last_name_but_no_contact_yields_need_contact(self):
        lead = LeadData(last_name="Sharma")
        assert _compute_state(lead) == CollectionState.NEED_CONTACT

    def test_email_satisfies_contact(self):
        lead = LeadData(last_name="Sharma", email="priya@example.com")
        assert _compute_state(lead) == CollectionState.NEED_CONSENT

    def test_phone_satisfies_contact(self):
        lead = LeadData(last_name="Sharma", phone="+91-98765-43210")
        assert _compute_state(lead) == CollectionState.NEED_CONSENT

    def test_all_data_plus_consent_is_complete(self):
        lead = LeadData(last_name="Sharma", phone="+91-98765-43210", consent_given=True)
        assert _compute_state(lead) == CollectionState.COMPLETE

    def test_first_name_alone_not_enough(self):
        """Only last_name counts — first_name alone still triggers NEED_NAME."""
        lead = LeadData(first_name="Priya")
        assert _compute_state(lead) == CollectionState.NEED_NAME


# ===========================================================================
# 2. Intent Classification
# ===========================================================================

class TestClassifyIntent:

    def test_purchase_label_is_strong_sales(self):
        assert classify_intent("purchase_inquiry") == LeadIntent.STRONG_SALES

    def test_callback_label_is_strong_sales(self):
        assert classify_intent("callback_request") == LeadIntent.STRONG_SALES

    def test_faq_is_informational(self):
        assert classify_intent("faq") == LeadIntent.INFORMATIONAL

    def test_troubleshooting_is_informational(self):
        assert classify_intent("troubleshooting") == LeadIntent.INFORMATIONAL

    def test_soft_interest_label(self):
        assert classify_intent("soft_interest") == LeadIntent.SOFT_INTEREST

    def test_keyword_buy_triggers_strong_sales(self):
        assert classify_intent(None, "I want to buy the V15 Detect") == LeadIntent.STRONG_SALES

    def test_keyword_curious_triggers_soft(self):
        assert classify_intent(None, "I'm curious about the Airwrap") == LeadIntent.SOFT_INTEREST

    def test_unknown_defaults_to_informational(self):
        assert classify_intent("unknown_xyz") == LeadIntent.INFORMATIONAL

    def test_none_defaults_to_informational(self):
        assert classify_intent(None, None) == LeadIntent.INFORMATIONAL


# ===========================================================================
# 3. Decision Gate
# ===========================================================================

class TestEvaluateLeadDecision:

    def _full_lead(self, consent=True) -> LeadData:
        return LeadData(last_name="Sharma", phone="+91-98765-43210", consent_given=consent)

    def test_informational_never_creates(self):
        d = evaluate_lead_decision(LeadIntent.INFORMATIONAL, self._full_lead())
        assert not d.should_create
        assert not d.ask_for_consent

    def test_soft_interest_asks_consent(self):
        d = evaluate_lead_decision(LeadIntent.SOFT_INTEREST, self._full_lead(consent=False))
        assert not d.should_create
        assert d.ask_for_consent

    def test_strong_sales_no_consent_asks_consent(self):
        d = evaluate_lead_decision(LeadIntent.STRONG_SALES, self._full_lead(consent=False))
        assert not d.should_create
        assert d.ask_for_consent

    def test_strong_sales_with_consent_creates(self):
        d = evaluate_lead_decision(LeadIntent.STRONG_SALES, self._full_lead(consent=True))
        assert d.should_create

    def test_missing_last_name_blocks_creation(self):
        lead = LeadData(phone="+91-98765-43210", consent_given=True)
        d = evaluate_lead_decision(LeadIntent.STRONG_SALES, lead)
        assert not d.should_create
        assert any("Last name" in e for e in d.missing_fields)

    def test_missing_contact_blocks_creation(self):
        lead = LeadData(last_name="Sharma", consent_given=True)
        d = evaluate_lead_decision(LeadIntent.STRONG_SALES, lead)
        assert not d.should_create


# ===========================================================================
# 4. Sequential Collection Flow — capture_lead_interest
# ===========================================================================

class TestCaptureLeadInterestFlow:
    """
    Walk through the full NEED_NAME → NEED_CONTACT → NEED_CONSENT progression.
    """

    def setup_method(self):
        self.sid = "test-session-collect"
        clear_session(self.sid)

    def teardown_method(self):
        clear_session(self.sid)

    # -- Turn 1: intent detected, no data yet → NEED_NAME --------------------
    @pytest.mark.asyncio
    async def test_step1_asks_for_name_when_no_data(self):
        responses = []
        params = make_params(responses)

        await capture_lead_interest(
            params,
            intent_label="purchase_inquiry",
            user_text="I want to buy the V15 Detect",
            session_id=self.sid,
        )

        assert len(responses) == 1
        msg = responses[0].lower()
        assert "name" in msg

    # -- Turn 2: user gives name → should move to NEED_CONTACT ---------------
    @pytest.mark.asyncio
    async def test_step2_asks_for_contact_after_name(self):
        responses = []
        params = make_params(responses)

        # Turn 1 — intent, no name
        await capture_lead_interest(
            params,
            intent_label="purchase_inquiry",
            user_text="I want to buy the V15",
            session_id=self.sid,
        )
        responses.clear()

        # Turn 2 — user provides name
        await capture_lead_interest(
            params,
            intent_label="purchase_inquiry",
            user_text="My name is Priya Sharma",
            last_name="Sharma",
            first_name="Priya",
            session_id=self.sid,
        )

        assert len(responses) == 1
        msg = responses[0].lower()
        assert any(word in msg for word in ["phone", "email", "contact", "reach"])

    # -- Turn 3: user gives phone → should move to NEED_CONSENT --------------
    @pytest.mark.asyncio
    async def test_step3_asks_for_consent_after_contact(self):
        responses = []
        params = make_params(responses)

        await capture_lead_interest(params, intent_label="purchase_inquiry",
                                    user_text="I want to buy", session_id=self.sid)
        await capture_lead_interest(params, intent_label="purchase_inquiry",
                                    user_text="Priya Sharma", last_name="Sharma",
                                    first_name="Priya", session_id=self.sid)
        responses.clear()

        # Turn 3 — user provides phone
        await capture_lead_interest(
            params,
            intent_label="purchase_inquiry",
            user_text="My number is 91234 56789",
            phone="+91-91234-56789",
            session_id=self.sid,
        )

        assert len(responses) == 1
        msg = responses[0].lower()
        # Should present their data and ask for consent
        assert any(word in msg for word in ["yes", "shall", "register", "share", "sales team"])

    # -- State merges data across turns --------------------------------------
    @pytest.mark.asyncio
    async def test_data_persists_across_turns(self):
        responses = []
        params = make_params(responses)

        await capture_lead_interest(params, intent_label="purchase_inquiry",
                                    user_text="buy", session_id=self.sid)
        await capture_lead_interest(params, intent_label="purchase_inquiry",
                                    user_text="name", last_name="Gupta",
                                    session_id=self.sid)

        lead = _pending_leads[self.sid]
        assert lead.last_name == "Gupta"

    # -- Informational intent is ignored -------------------------------------
    @pytest.mark.asyncio
    async def test_informational_intent_returns_generic_response(self):
        responses = []
        params = make_params(responses)

        await capture_lead_interest(
            params,
            intent_label="informational",
            user_text="What's the battery life of the V15?",
            session_id=self.sid,
        )

        assert len(responses) == 1
        assert self.sid not in _pending_leads   # no state created

    # -- Pre-filled data skips early steps -----------------------------------
    @pytest.mark.asyncio
    async def test_skips_name_step_if_already_provided(self):
        responses = []
        params = make_params(responses)

        await capture_lead_interest(
            params,
            intent_label="purchase_inquiry",
            user_text="I want to buy please call me back",
            first_name="Ravi",
            last_name="Mehta",      # name already known
            session_id=self.sid,
        )

        assert len(responses) == 1
        msg = responses[0].lower()
        # Should skip NEED_NAME and land on NEED_CONTACT
        assert any(word in msg for word in ["phone", "email", "contact", "reach"])

    @pytest.mark.asyncio
    async def test_skips_to_consent_if_name_and_contact_provided(self):
        responses = []
        params = make_params(responses)

        await capture_lead_interest(
            params,
            intent_label="purchase_inquiry",
            user_text="call me back",
            last_name="Mehta",
            phone="+91-99000-11223",
            session_id=self.sid,
        )

        assert len(responses) == 1
        msg = responses[0].lower()
        assert any(word in msg for word in ["yes", "shall", "register", "share", "sales team"])


# ===========================================================================
# 5. confirm_lead_creation
# ===========================================================================

class TestConfirmLeadCreation:

    def setup_method(self):
        self.sid = "test-session-confirm"
        clear_session(self.sid)

    def teardown_method(self):
        clear_session(self.sid)

    def _seed_complete_lead(self):
        """Put a fully-collected (but not yet consented) lead into state store."""
        lead = LeadData(
            first_name="Priya",
            last_name="Sharma",
            phone="+91-98765-43210",
            product_interest="V15 Detect",
            intent_summary="Wants to purchase V15 Detect",
            consent_given=False,
        )
        _pending_leads[self.sid] = lead
        return lead

    @pytest.mark.asyncio
    async def test_no_pending_lead_returns_guidance(self):
        responses = []
        params = make_params(responses)

        await confirm_lead_creation(params, session_id=self.sid)

        assert "pending" in responses[0].lower() or "name" in responses[0].lower()

    @pytest.mark.asyncio
    async def test_missing_name_in_pending_lead_asks_for_name(self):
        responses = []
        params = make_params(responses)

        _pending_leads[self.sid] = LeadData(phone="+91-98765-43210")  # no last_name

        await confirm_lead_creation(params, session_id=self.sid)

        assert "name" in responses[0].lower()
        # Lead should NOT be popped — still in progress
        assert self.sid in _pending_leads

    @pytest.mark.asyncio
    async def test_missing_contact_in_pending_lead_asks_for_contact(self):
        responses = []
        params = make_params(responses)

        _pending_leads[self.sid] = LeadData(last_name="Sharma")  # no phone/email

        await confirm_lead_creation(params, session_id=self.sid)

        msg = responses[0].lower()
        assert any(word in msg for word in ["phone", "email", "contact"])
        assert self.sid in _pending_leads

    @pytest.mark.asyncio
    async def test_complete_data_creates_lead_in_salesforce(self):
        responses = []
        params = make_params(responses)
        self._seed_complete_lead()

        mock_response = CreateRecordResponse(
            record_id="00Q000000SF1ABC", success=True, errors=[]
        )

        with patch(
            "src.salesforce.maya_tool._lead_manager.process",
            new_callable=AsyncMock,
            return_value=MagicMock(success=True, record_id="00Q000000SF1ABC"),
        ):
            await confirm_lead_creation(
                params,
                session_id=self.sid,
                user_text="yes please go ahead",
            )

        assert len(responses) == 1
        msg = responses[0].lower()
        assert any(word in msg for word in ["registered", "reference", "specialist"])
        # Session state cleaned up
        assert self.sid not in _pending_leads

    @pytest.mark.asyncio
    async def test_salesforce_failure_returns_friendly_error(self):
        responses = []
        params = make_params(responses)
        self._seed_complete_lead()

        with patch(
            "src.salesforce.maya_tool._lead_manager.process",
            new_callable=AsyncMock,
            return_value=MagicMock(success=False, error="Timeout"),
        ):
            await confirm_lead_creation(params, session_id=self.sid)

        assert "sorry" in responses[0].lower() or "problem" in responses[0].lower()
        assert self.sid not in _pending_leads


# ===========================================================================
# 6. SalesforceClient — HTTP layer
# ===========================================================================

class TestSalesforceClient:

    @pytest.mark.asyncio
    async def test_successful_lead_creation(self):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "00Q000000SF0001AAC", "success": True, "errors": []
        }

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_response)

            client = SalesforceClient()
            result = await client.create_record("Lead", {"LastName": "Sharma"})

        assert result.success is True
        assert result.record_id == "00Q000000SF0001AAC"

    @pytest.mark.asyncio
    async def test_auth_error_on_401(self):
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_response)

            client = SalesforceClient()
            with pytest.raises(SalesforceAuthError):
                await client.create_record("Lead", {"LastName": "Sharma"})

    @pytest.mark.asyncio
    async def test_api_error_on_400(self):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = [
            {"errorCode": "REQUIRED_FIELD_MISSING", "message": "LastName required."}
        ]

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_response)

            client = SalesforceClient()
            with pytest.raises(SalesforceAPIError) as exc_info:
                await client.create_record("Lead", {})

        assert exc_info.value.error_code == "REQUIRED_FIELD_MISSING"
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_network_error_exhausts_retries(self):
        import httpx

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

            with patch("asyncio.sleep", new_callable=AsyncMock):
                client = SalesforceClient()
                client.MAX_RETRIES = 2
                with pytest.raises(SalesforceNetworkError):
                    await client.create_record("Lead", {"LastName": "Sharma"})

        assert instance.post.call_count == 2


# ===========================================================================
# 7. LeadManager — payload validation
# ===========================================================================

class TestLeadManagerPayload:

    @pytest.mark.asyncio
    async def test_payload_has_required_salesforce_fields(self):
        captured = {}

        async def mock_create(sobject, payload):
            captured.update(payload)
            return CreateRecordResponse("00QTEST001", True, [])

        mock_client = AsyncMock()
        mock_client.create_record = mock_create

        manager = LeadManager(client=mock_client)
        lead = LeadData(
            first_name="Priya",
            last_name="Sharma",
            phone="+91-98765-43210",
            product_interest="V15 Detect",
            intent_summary="Wants to buy V15.",
            consent_given=True,
        )
        await manager.process("purchase_inquiry", lead)

        assert captured["LastName"] == "Sharma"
        assert captured["FirstName"] == "Priya"
        assert captured["LeadSource"] == "Web"
        assert captured["Status"] == "Open - Not Contacted"
        assert "V15 Detect" in captured["Description"] or "purchase" in captured["Description"].lower()
        assert captured["Phone"] == "+91-98765-43210"

    @pytest.mark.asyncio
    async def test_informational_intent_never_creates(self):
        manager = LeadManager(client=MagicMock())
        lead = LeadData(last_name="Sharma", phone="+91-98765-43210", consent_given=True)
        result = await manager.process("faq", lead, "What are the specs?")
        assert not result.success

    @pytest.mark.asyncio
    async def test_missing_consent_skips_creation(self):
        manager = LeadManager(client=MagicMock())
        lead = LeadData(last_name="Sharma", phone="+91-98765-43210", consent_given=False)
        result = await manager.process("purchase_inquiry", lead)
        assert not result.success
        assert result.decision.ask_for_consent
