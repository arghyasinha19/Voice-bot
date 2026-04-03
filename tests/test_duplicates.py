import asyncio
import os
import sys
from unittest.mock import MagicMock, AsyncMock

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from salesforce.lead_manager import LeadManager, LeadData, LeadIntent, SalesforceAPIError

async def test_duplicate_handling():
    print("--- Testing Duplicate Handling Logic ---")
    
    # 1. Mock SalesforceClient to raise DUPLICATES_DETECTED
    mock_client = MagicMock()
    mock_client.create_record = AsyncMock(side_effect=SalesforceAPIError(
        status_code=400,
        error_code="DUPLICATES_DETECTED",
        message="Use one of these records?"
    ))
    
    manager = LeadManager(client=mock_client)
    
    # 2. Prepare LeadData
    lead = LeadData(
        first_name="Test",
        last_name="Duplicate",
        email="duplicate@example.com",
        consent_given=True
    )
    
    # 3. Process
    result = await manager.process(
        intent_label="strong_sales",
        lead=lead,
        user_text="Yes please"
    )
    
    # 4. Assertions
    print(f"Result Success: {result.success}")
    print(f"Result Is Duplicate: {result.is_duplicate}")
    
    assert result.success is True
    assert result.is_duplicate is True
    print("Logic Test: PASS ✅")

if __name__ == "__main__":
    asyncio.run(test_duplicate_handling())
