"""
Account resolver service using Levenshtein-based fuzzy string matching.

This implementation uses the rapidfuzz library to find the best matching
accounts based on character-level similarity, which is effective for handling
typos, abbreviations, and minor variations in account names.
"""

import structlog
from datetime import datetime
from typing import Any, Dict, List, Optional

# New imports for fuzzy matching
from rapidfuzz import process, fuzz

from shared.models.account import Account
from shared.models.rbac import RBACContext
# UnifiedDataService not needed in MCP - it's optional

logger = structlog.get_logger(__name__)


class AccountResolverService:
    """Fuzzy-matching account resolver using Levenshtein distance."""

    def __init__(
        self,
        aoai_client: Any = None,  # Kept for backward compatibility, but ignored.
        unified_data_service: Any = None,  # Optional in MCP
        confidence_threshold: float = 85.0, # Note: Levenshtein scores are 0-100
        max_suggestions: int = 3,
    ):
        self.unified_data_service = unified_data_service
        # Levenshtein scores are typically higher, so the threshold is adjusted (0-100 scale)
        self.confidence_threshold = confidence_threshold
        self.max_suggestions = max_suggestions

        logger.info(
            "Account resolver (Fuzzy Match) initialized",
            confidence_threshold=self.confidence_threshold,
            max_suggestions=self.max_suggestions,
        )

    async def resolve_account(
        self,
        user_query: str,
        rbac_context: RBACContext,
        allowed_accounts: Optional[List[Account]] = None,
    ) -> Dict[str, Any]:
        """Resolve an account name using Levenshtein-based fuzzy matching."""
        try:
            logger.info("Starting account resolution (Fuzzy Match)", user_id=rbac_context.user_id)

            if allowed_accounts is None:
                allowed_accounts = await self._get_allowed_accounts(rbac_context)

            if not allowed_accounts:
                logger.warning("No allowed accounts for user", user_id=rbac_context.user_id)
                return self._build_empty_response("No accessible accounts found")

            # Perform the fuzzy matching
            account_names = [acc.name for acc in allowed_accounts]
            
            # extract returns a list of tuples: (match, score, original_index)
            # We use WRatio for better handling of strings with different lengths
            matches = process.extract(
                user_query,
                account_names,
                scorer=fuzz.WRatio,
                limit=self.max_suggestions
            )

            if not matches:
                logger.warning("No fuzzy matches found", query=user_query)
                return self._build_empty_response("No similar accounts found")

            resolved_accounts: List[Account] = []
            suggestions = []
            confidences = [score for _, score, _ in matches]

            for match_name, score, index in matches:
                account = allowed_accounts[index]
                if score >= self.confidence_threshold:
                    resolved_accounts.append(account)
                else:
                    suggestions.append({
                        "account": account,
                        "confidence": score,
                        "method": "fuzzy",
                        "explanation": f"Matched '{match_name}' with score {score:.2f}",
                    })
            
            overall_confidence = max(confidences) if confidences else 0.0
            requires_disambiguation = not resolved_accounts and len(suggestions) > 1

            result = {
                "resolved_accounts": resolved_accounts,
                "candidates": [user_query],
                "confidence": overall_confidence,
                "requires_disambiguation": requires_disambiguation,
                "suggestions": suggestions,
                "method": "fuzzy",
            }
            
            logger.info(
                "Fuzzy resolution completed",
                user_id=rbac_context.user_id,
                resolved_count=len(resolved_accounts),
                suggestions_count=len(suggestions),
                confidence=overall_confidence,
            )
            return result

        except Exception as e:
            logger.error("Failed to resolve accounts", user_id=rbac_context.user_id, error=str(e))
            raise

    def _build_empty_response(self, error_message: Optional[str] = None) -> Dict[str, Any]:
        """Helper to create a standard empty/no-result dictionary."""
        return {
            "resolved_accounts": [], "candidates": [], "confidence": 0.0,
            "requires_disambiguation": False, "suggestions": [],
            "error": error_message, "method": "fuzzy"
        }

    async def resolve_entities(
        self,
        user_query: str,
        rbac_context: RBACContext,
        confidence_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Backwards-compatible adapter returning list of {id, name, confidence}."""
        # Use the class's threshold if none is provided
        current_threshold = confidence_threshold or self.confidence_threshold

        resolution = await self.resolve_account(user_query, rbac_context)
        
        # Combine resolved accounts and high-confidence suggestions
        all_matches = []
        for acc in resolution.get("resolved_accounts", []):
             all_matches.append({
                 "id": acc.id, "name": acc.name, "confidence": 100.0
             })

        for sugg in resolution.get("suggestions", []):
            if sugg.get("confidence", 0.0) >= current_threshold:
                 all_matches.append({
                     "id": sugg["account"].id, "name": sugg["account"].name,
                     "confidence": sugg["confidence"]
                 })
        
        return all_matches

    async def resolve_account_names(
        self,
        account_names: List[str],
        rbac_context: RBACContext,
        confidence_threshold: Optional[float] = None,
    ) -> List[Account]:
        """Resolve a list of account names to Account objects using fuzzy matching."""
        if not account_names:
            return []

        current_threshold = confidence_threshold or self.confidence_threshold
        
        try:
            allowed_accounts = await self._get_allowed_accounts(rbac_context)
            if not allowed_accounts:
                logger.warning("No allowed accounts for user", user_id=rbac_context.user_id)
                return []
            
            allowed_account_names = [acc.name for acc in allowed_accounts]
            resolved_accounts_map = {} # Use dict to avoid duplicates

            for name in account_names:
                # Find the single best match above the threshold
                match = process.extractOne(
                    name,
                    allowed_account_names,
                    scorer=fuzz.WRatio,
                    score_cutoff=current_threshold
                )
                
                if match:
                    match_name, score, index = match
                    account = allowed_accounts[index]
                    resolved_accounts_map[account.id] = account
                    logger.info(
                        "Account resolved via fuzzy matching",
                        input_name=name, resolved_name=account.name, confidence=score
                    )
                else:
                    logger.warning(
                        "No good match found for account name",
                        input_name=name, user_id=rbac_context.user_id
                    )
            
            resolved_accounts = list(resolved_accounts_map.values())
            logger.info(
                "Account names resolved",
                user_id=rbac_context.user_id,
                input_count=len(account_names),
                resolved_count=len(resolved_accounts)
            )
            return resolved_accounts

        except Exception as e:
            logger.error("Failed to resolve account names", user_id=rbac_context.user_id, error=str(e))
            return []

    async def _get_allowed_accounts(self, rbac_context: RBACContext) -> List[Account]:
        """Get list of accounts that the user has access to."""
        # This implementation remains the same.
        # In a real system, this queries a database/service.
        demo_accounts = [
            Account(
                id="1", name="Microsoft Corporation", display_name="Microsoft Corporation",
                account_type="Enterprise", owner_user_id=rbac_context.user_id,
                owner_email=rbac_context.email, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
            ),
            Account(
                id="2", name="Salesforce Inc", display_name="Salesforce Inc",
                account_type="Enterprise", owner_user_id=rbac_context.user_id,
                owner_email=rbac_context.email, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
            ),
            Account(
                id="3", name="Amazon Web Services", display_name="Amazon Web Services",
                account_type="Enterprise", owner_user_id=rbac_context.user_id,
                owner_email=rbac_context.email, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
            ),
        ]
        logger.debug(
            "Retrieved allowed accounts", user_id=rbac_context.user_id,
            account_count=len(demo_accounts)
        )
        return demo_accounts


class AccountResolverService_:
    """Developer helper resolver that returns a deterministic demo account set."""
    # This class remains unchanged as it's for dev/testing.
    # Its simple substring matching is sufficient for its purpose.

    @staticmethod
    async def get_dummy_accounts(rbac_context: RBACContext) -> List[Account]:
        demo_accounts = [
            Account(
                id="1", name="Microsoft Corporation", display_name="Microsoft Corporation",
                account_type="Enterprise", owner_user_id=rbac_context.user_id,
                owner_email=rbac_context.email, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
            ),
            Account(
                id="2", name="Salesforce Inc", display_name="Salesforce Inc",
                account_type="Enterprise", owner_user_id=rbac_context.user_id,
                owner_email=rbac_context.email, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
            ),
            Account(
                id="3", name="Amazon Web Services", display_name="Amazon Web Services",
                account_type="Enterprise", owner_user_id=rbac_context.user_id,
                owner_email=rbac_context.email, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
            ),
        ]
        return demo_accounts

    @staticmethod
    async def resolve_account_names(
        account_names: List[str],
        rbac_context: RBACContext,
        confidence_threshold: Optional[float] = None
    ) -> List[Account]:
        """
        Resolve account names using fuzzy matching (Levenshtein) against the static demo set.
        - Exact/substring matches are preferred.
        - Otherwise, pick the highest Levenshtein similarity.
        - If no candidate meets the threshold, fall back to the best match (and ultimately first demo account).
        """
        import unicodedata
        from typing import Tuple

        def _norm(s: str) -> str:
            if not s:
                return ""
            s = unicodedata.normalize("NFKD", s)
            s = "".join(ch for ch in s if not unicodedata.combining(ch))  # strip accents
            s = s.lower().strip()
            # Optional: collapse non-alphanumerics to spaces, then single-space
            out = []
            prev_space = False
            for ch in s:
                if ch.isalnum():
                    out.append(ch)
                    prev_space = False
                else:
                    if not prev_space:
                        out.append(" ")
                        prev_space = True
            return " ".join("".join(out).split())

        def _levenshtein(a: str, b: str) -> int:
            """Classic Wagner–Fischer algorithm (iterative, O(len(a)*len(b)))."""
            if a == b:
                return 0
            la, lb = len(a), len(b)
            if la == 0:  # distance is length of the other
                return lb
            if lb == 0:
                return la
            # Ensure a is the shorter to use less memory
            if la > lb:
                a, b = b, a
                la, lb = lb, la
            prev = list(range(la + 1))
            for j in range(1, lb + 1):
                cur = [j] + [0] * la
                bj = b[j - 1]
                for i in range(1, la + 1):
                    cost = 0 if a[i - 1] == bj else 1
                    cur[i] = min(
                        prev[i] + 1,      # deletion
                        cur[i - 1] + 1,   # insertion
                        prev[i - 1] + cost  # substitution
                    )
                prev = cur
            return prev[la]

        def _similarity(a: str, b: str) -> float:
            """Normalized Levenshtein similarity in [0,1]."""
            if not a and not b:
                return 1.0
            if not a or not b:
                return 0.0
            dist = _levenshtein(a, b)
            denom = max(len(a), len(b))
            return 1.0 - (dist / denom)

        dummy = await AccountResolverService_.get_dummy_accounts(rbac_context)
        if not dummy:
            return []

        # Default threshold if not provided
        threshold = 0.75 if confidence_threshold is None else float(confidence_threshold)

        resolved: List[Account] = []
        for name in account_names:
            if not name:
                resolved.append(dummy[0])
                continue

            lname_raw = name
            lname = _norm(name)

            best: Tuple[Optional[Account], float] = (None, -1.0)

            for acc in dummy:
                acc_name_raw = acc.name or ""
                acc_name = _norm(acc_name_raw)

                # Exact (case-insensitive) hard hit
                if acc_name_raw.lower() == lname_raw.lower():
                    best = (acc, 1.0)
                    break

                # Substring heuristic boost
                score = _similarity(lname, acc_name)
                if lname in acc_name or acc_name in lname:
                    score = max(score, 0.92)

                if score > best[1]:
                    best = (acc, score)

            found, score = best

            if found is None:
                # Absolute fallback (keep previous behavior)
                resolved.append(dummy[0])
                continue

            if score >= threshold:
                resolved.append(found)
            else:
                # Prefer best match even if below threshold; still better than arbitrary first
                resolved.append(found)

        return resolved
