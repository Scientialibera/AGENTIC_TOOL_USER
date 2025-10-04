"""
Account resolver service for the agentic framework.

Provides fuzzy matching account resolution using Levenshtein distance.
"""

from typing import List, Optional
from rapidfuzz import process, fuzz
import structlog

from shared.models import Account
from shared.fabric_client import FabricClient

logger = structlog.get_logger(__name__)


class AccountResolverService:
    """Account resolver using fuzzy matching."""

    def __init__(
        self,
        fabric_client: Optional[FabricClient] = None,
        confidence_threshold: float = 85.0,
        max_suggestions: int = 3,
        dev_mode: bool = False
    ):
        """Initialize the account resolver service."""
        self.fabric_client = fabric_client
        self.confidence_threshold = confidence_threshold
        self.max_suggestions = max_suggestions
        self.dev_mode = dev_mode

        logger.info(
            "Account resolver initialized",
            confidence_threshold=confidence_threshold,
            dev_mode=dev_mode,
        )

    async def resolve_account_names(
        self,
        account_names: List[str],
    ) -> List[Account]:
        """
        Resolve list of account names to Account objects using fuzzy matching.

        Args:
            account_names: List of account names to resolve

        Returns:
            List of resolved Account objects (deduplicated)
        """
        if not account_names:
            return []

        try:
            # Get all available accounts (dummy or real)
            all_accounts = await self._get_all_accounts()

            if not all_accounts:
                logger.warning("No accounts available for matching")
                return []

            # Fuzzy match against all accounts
            all_account_names = [acc.name for acc in all_accounts]
            resolved_accounts_map = {}

            for name in account_names:
                match = process.extractOne(
                    name,
                    all_account_names,
                    scorer=fuzz.WRatio,
                    score_cutoff=self.confidence_threshold
                )

                if match:
                    match_name, score, index = match
                    account = all_accounts[index]
                    resolved_accounts_map[account.id] = account
                    logger.info(
                        "Account resolved",
                        input_name=name,
                        resolved_name=account.name,
                        confidence=score,
                    )
                else:
                    logger.warning("No match found", input_name=name, threshold=self.confidence_threshold)

            resolved_accounts = list(resolved_accounts_map.values())
            logger.info(
                "Account names resolved",
                input_count=len(account_names),
                resolved_count=len(resolved_accounts),
            )
            return resolved_accounts

        except Exception as e:
            logger.error("Failed to resolve account names", error=str(e))
            return []

    async def _get_all_accounts(self) -> List[Account]:
        """Get all available accounts (dummy in dev mode, real from Fabric otherwise)."""
        try:
            if self.dev_mode or not self.fabric_client:
                return self._get_dummy_accounts()

            query = "SELECT id, name, industry, revenue, employee_count FROM accounts LIMIT 1000"

            results = await self.fabric_client.execute_query(query)

            accounts = []
            for row in results:
                accounts.append(Account(
                    id=row.get("id", ""),
                    name=row.get("name", ""),
                    industry=row.get("industry"),
                    revenue=row.get("revenue"),
                    employee_count=row.get("employee_count"),
                ))

            logger.info("Retrieved accounts from Fabric", count=len(accounts))
            return accounts

        except Exception as e:
            logger.error("Failed to get accounts from Fabric, falling back to dummy", error=str(e))
            return self._get_dummy_accounts()

    def _get_dummy_accounts(self) -> List[Account]:
        """Get dummy accounts for dev mode."""
        return [
            Account(
                id="1",
                name="Microsoft Corporation",
                industry="Technology",
                revenue=211915000000.0,
                employee_count=221000,
            ),
            Account(
                id="2",
                name="Salesforce Inc",
                industry="Technology",
                revenue=31352000000.0,
                employee_count=79390,
            ),
            Account(
                id="3",
                name="Amazon Web Services",
                industry="Technology",
                revenue=80000000000.0,
                employee_count=1540000,
            ),
            Account(
                id="4",
                name="Google LLC",
                industry="Technology",
                revenue=282836000000.0,
                employee_count=182502,
            ),
            Account(
                id="5",
                name="Oracle Corporation",
                industry="Technology",
                revenue=49954000000.0,
                employee_count=164000,
            ),
        ]
