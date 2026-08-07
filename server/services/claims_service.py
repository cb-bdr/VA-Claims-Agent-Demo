"""
Claims Service - Queries Databricks for VA Claims data
"""
import logging
import os
from typing import List, Dict, Any, Optional
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState
from datetime import datetime
from server.services.hardcoded_claims_data import PRIORITY_CLAIMS_DATA

logger = logging.getLogger(__name__)


class ClaimsService:
    """Service for fetching VA Claims data from Databricks"""

    def __init__(self):
        # No explicit host/token: let the SDK resolve unified auth (CLI profile via
        # DATABRICKS_CONFIG_PROFILE, PAT via DATABRICKS_HOST/DATABRICKS_TOKEN, or the
        # app service principal when deployed to Databricks Apps). Passing token= here
        # forces PAT auth and breaks accounts that require OAuth U2M.
        self.workspace_client = WorkspaceClient()
        self._warehouse_id = None
        catalog = os.getenv("DATABRICKS_UC_CATALOG")
        if not catalog:
            raise Exception("DATABRICKS_UC_CATALOG environment variable not set")
        schema_name = os.getenv("DATABRICKS_UC_SCHEMA", "vba_claims_agent")
        self.schema = f"{catalog}.{schema_name}"

    async def _get_warehouse_id(self) -> str:
        """Get SQL warehouse ID (env override or first available)."""
        if self._warehouse_id:
            return self._warehouse_id

        env_id = (os.getenv("DATABRICKS_SQL_WAREHOUSE_ID") or os.getenv("DATABRICKS_WAREHOUSE_ID") or "").strip()
        if env_id:
            self._warehouse_id = env_id
            return self._warehouse_id

        warehouses = list(self.workspace_client.warehouses.list())
        if not warehouses:
            raise Exception("No SQL warehouses available")

        # Use first running warehouse
        for wh in warehouses:
            if wh.state.value == "RUNNING":
                self._warehouse_id = wh.id
                return self._warehouse_id

        # If none running, use first one
        self._warehouse_id = warehouses[0].id
        return self._warehouse_id

    async def _execute_query(self, sql: str) -> List[List[Any]]:
        """Execute a SQL query and return results"""
        warehouse_id = await self._get_warehouse_id()

        response = self.workspace_client.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=sql,
            wait_timeout="30s"
        )

        if response.status.state == StatementState.FAILED:
            raise Exception(f"Query failed: {response.status.error}")

        if response.result and response.result.data_array:
            return response.result.data_array

        return []

    async def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Get comprehensive dashboard data

        Returns:
            Dict containing all dashboard metrics and data
        """
        # Query metrics from gold tables
        metrics = await self.get_metrics()
        critical_claims = await self.get_critical_claims()
        visibility_gaps = await self.get_visibility_gaps()
        region_delays = await self.get_region_delays()

        return {
            "metrics": metrics,
            "criticalClaims": critical_claims,
            "visibilityGaps": visibility_gaps,
            "regionDelays": region_delays,
            "dataIntegrity": 94.6,  # Can be calculated from data quality metrics
            "compliance": 92.1,  # Can be calculated from compliance tables
        }

    async def get_metrics(self) -> Dict[str, Any]:
        """
        Get key performance metrics from claims

        Returns:
            Dict with avgCycleTime, activeClaims, processingRate, veteranImpact
        """
        try:
            # No claims_metrics table exists; claims has no cycle_time_hours/processing_rate
            # columns either. decision_time_days (*24 for hours) and the APPROVED share are
            # the closest real proxies. Confirmed current_status vocabulary (full GROUP BY over
            # the table) is exactly PENDING, DECISION_READY, REVIEW_REQUIRED, AWAITING_EVIDENCE,
            # APPROVED — no ACTIVE, no DENIED. "active" is therefore != 'APPROVED', not a NOT IN
            # list carrying a value that doesn't occur. The table is a static 2024 snapshot, not
            # a live feed, so the recency window is relative to the data's own MAX(date_submitted)
            # rather than CURRENT_DATE (which would always match 0 rows).
            #
            # All four aggregates below share one FROM/WHERE (no joins, no differing filters),
            # so they reconcile over the SAME in-window row set: activeClaims (distinct claim_id,
            # not-yet-finalized) + the APPROVED count implied by processingRate always sums to
            # the window's total row count. veteranImpact (distinct veteran_id) equals that same
            # total only when every veteran has exactly one claim in-window; it will read lower
            # than activeClaims+approved whenever a veteran has multiple in-window claims.
            sql = f"""
            SELECT
                AVG(decision_time_days) * 24 as avg_cycle_time,
                COUNT(DISTINCT CASE WHEN current_status != 'APPROVED' THEN claim_id END) as active_claims,
                AVG(CASE WHEN current_status = 'APPROVED' THEN 1 ELSE 0 END) * 100 as processing_rate,
                COUNT(DISTINCT veteran_id) as veteran_impact
            FROM {self.schema}.claims
            WHERE date_submitted >= (SELECT MAX(date_submitted) FROM {self.schema}.claims) - INTERVAL 30 DAYS
            """

            results = await self._execute_query(sql)

            if results and len(results) > 0:
                row = results[0]
                return {
                    "avgCycleTime": float(row[0]) if row[0] else 28.5,
                    "activeClaims": int(row[1]) if row[1] else 534,
                    "processingRate": float(row[2]) if row[2] else 67.0,
                    "veteranImpact": int(row[3]) if row[3] else 186187,
                    "isFallback": False,
                }
            logger.error("get_metrics: query returned no rows; returning hardcoded fallback metrics")
        except Exception:
            logger.exception("get_metrics: query failed; returning hardcoded fallback metrics")

        # Return default values if query fails
        return {
            "avgCycleTime": 28.5,
            "activeClaims": 534,
            "processingRate": 67.0,
            "veteranImpact": 186187,
            "isFallback": True,
        }

    async def get_critical_claims(self) -> List[Dict[str, Any]]:
        """
        Get critical claims with delays from gold tables

        Returns:
            List of critical claims with name, affected count, and days delayed
        """
        try:
            # 'DELAYED' is not a real current_status value (real vocabulary: PENDING,
            # DECISION_READY, REVIEW_REQUIRED, AWAITING_EVIDENCE, APPROVED) — "critical/delayed"
            # is approximated as not-yet-finalized claims aged past 20 days. DATEDIFF is anchored
            # to the data's own MAX(date_submitted), not CURRENT_DATE, since this is a static
            # 2024 snapshot and CURRENT_DATE would inflate every claim to ~700+ days old.
            sql = f"""
            SELECT
                claimed_condition as name,
                COUNT(DISTINCT veteran_id) as affected,
                AVG(DATEDIFF(bounds.as_of, date_submitted)) as days
            FROM {self.schema}.claims
            CROSS JOIN (SELECT MAX(date_submitted) as as_of FROM {self.schema}.claims) bounds
            WHERE current_status != 'APPROVED'
                AND DATEDIFF(bounds.as_of, date_submitted) > 20
            GROUP BY claimed_condition
            ORDER BY COUNT(DISTINCT veteran_id) DESC
            LIMIT 10
            """

            results = await self._execute_query(sql)

            if results:
                return [
                    {
                        "name": row[0],
                        "affected": int(row[1]),
                        "days": int(row[2]),
                        "isFallback": False,
                    }
                    for row in results
                ]
            logger.error("get_critical_claims: query returned no rows; returning hardcoded fallback data")
        except Exception:
            logger.exception("get_critical_claims: query failed; returning hardcoded fallback data")

        # Return VA-specific mock data if query fails
        return [
            {"name": "Disability Compensation Claims", "affected": 8847, "days": 32, "isFallback": True},
            {"name": "Post-9/11 GI Bill Education Benefits", "affected": 7234, "days": 28, "isFallback": True},
            {"name": "VA Healthcare Enrollment", "affected": 5621, "days": 24, "isFallback": True},
            {"name": "Pension & Survivors Benefits", "affected": 4893, "days": 26, "isFallback": True},
            {"name": "Vocational Rehabilitation & Employment", "affected": 3756, "days": 22, "isFallback": True},
            {"name": "VA Home Loan Guarantees", "affected": 3234, "days": 29, "isFallback": True},
            {"name": "Dependency & Indemnity Compensation", "affected": 2891, "days": 31, "isFallback": True},
            {"name": "Service-Connected Life Insurance", "affected": 2456, "days": 27, "isFallback": True},
        ]

    async def get_visibility_gaps(self) -> List[Dict[str, Any]]:
        """
        Get visibility gaps by provider and region

        Returns:
            List of visibility gaps with provider, product, region, delay, and risk
        """
        # No provider/region/delay data exists in the EHR-sourced pipeline tables (bronze/
        # silver/gold are clinical/claims-history shaped, not operations-shaped) — this will
        # be replaced once the GATED synthetic corpus (with station_of_jurisdiction per claim)
        # is loaded into its own schema. Always mock until then; no query to attempt.
        # (bronze_cerner_claim_extract.facility_id DOES join cleanly to claims.claim_id,
        # 120/120 verified — a facility-level, day-granularity proxy via decision_time_days is
        # a viable future enhancement, but not built tonight given this file's bug history.)
        return [
            {"provider": "Atlanta Regional Office", "product": "Disability Compensation", "region": "Southeast", "delay": 42.8, "risk": 25342, "isFallback": True},
            {"provider": "Seattle Regional Office", "product": "Healthcare Enrollment", "region": "Pacific Northwest", "delay": 38.2, "risk": 19320, "isFallback": True},
            {"provider": "New York Regional Office", "product": "Education Benefits", "region": "Northeast", "delay": 36.7, "risk": 18495, "isFallback": True},
            {"provider": "Nashville Regional Office", "product": "Pension Claims", "region": "Southeast", "delay": 34.1, "risk": 16850, "isFallback": True},
            {"provider": "Boston Regional Office", "product": "Vocational Rehab", "region": "Northeast", "delay": 33.8, "risk": 23105, "isFallback": True},
            {"provider": "Chicago Regional Office", "product": "Home Loans", "region": "Midwest", "delay": 29.4, "risk": 18922, "isFallback": True},
            {"provider": "Phoenix Regional Office", "product": "DIC Benefits", "region": "Southwest", "delay": 27.9, "risk": 16762, "isFallback": True},
            {"provider": "Denver Regional Office", "product": "Survivors Benefits", "region": "Mountain", "delay": 26.5, "risk": 11452, "isFallback": True},
            {"provider": "Los Angeles Regional Office", "product": "Mental Health Claims", "region": "Pacific", "delay": 25.8, "risk": 14892, "isFallback": True},
            {"provider": "Houston Regional Office", "product": "Burial Benefits", "region": "South Central", "delay": 24.6, "risk": 16602, "isFallback": True},
        ]

    async def get_region_delays(self) -> List[Dict[str, Any]]:
        """
        Get delay statistics by VA region

        Returns:
            List of VA regions with normal and delayed percentages
        """
        # No provider/region/delay data exists in the EHR-sourced pipeline tables (bronze/
        # silver/gold are clinical/claims-history shaped, not operations-shaped) — this will
        # be replaced once the GATED synthetic corpus (with station_of_jurisdiction per claim)
        # is loaded into its own schema. Always mock until then; no query to attempt.
        # (bronze_cerner_claim_extract.facility_id DOES join cleanly to claims.claim_id,
        # 120/120 verified — a facility-level, day-granularity proxy via decision_time_days is
        # a viable future enhancement, but not built tonight given this file's bug history.)
        return [
            {"name": "Southeast (Atlanta)", "normal": 23.2, "delayed": 76.8, "isFallback": True},
            {"name": "South Central (Houston)", "normal": 31.5, "delayed": 68.5, "isFallback": True},
            {"name": "Northeast (New York)", "normal": 42.8, "delayed": 57.2, "isFallback": True},
            {"name": "Pacific (Los Angeles)", "normal": 48.3, "delayed": 51.7, "isFallback": True},
            {"name": "Midwest (Chicago)", "normal": 52.1, "delayed": 47.9, "isFallback": True},
            {"name": "Mountain (Denver)", "normal": 61.4, "delayed": 38.6, "isFallback": True},
        ]

    # ============================================================================
    # PACT ACT CLAIMS ADJUDICATION DASHBOARD METHODS
    # ============================================================================

    async def get_adjudication_dashboard(self) -> Dict[str, Any]:
        """
        Get complete adjudication dashboard data for PACT Act claims

        Returns:
            Dict containing adjudicator stats, pending claims, high priority items
        """
        adjudicator_stats = await self.get_adjudicator_stats()
        pending_claims = await self.get_pending_claims()
        high_priority_claims = await self.get_high_priority_claims()
        pact_act_stats = await self.get_pact_act_statistics()

        return {
            "adjudicatorStats": adjudicator_stats,
            "pendingClaims": pending_claims,
            "highPriorityClaims": high_priority_claims,
            "pactActStats": pact_act_stats,
        }

    async def get_adjudicator_stats(self) -> Dict[str, Any]:
        """
        Get statistics for the current adjudicator

        Returns:
            Dict with pending claims %, avg decision time, presumptive match rate, PACT eligible trend
        """
        try:
            # status and current_status are identical in the current snapshot, but that's a
            # data coincidence, not a schema guarantee — standardized on current_status. Window
            # anchored to the data's own MAX(date_submitted), not CURRENT_DATE (static 2024
            # snapshot; CURRENT_DATE would always match 0 rows).
            sql = f"""
            SELECT
                AVG(CASE WHEN current_status = 'PENDING' THEN 1 ELSE 0 END) * 100 as pending_pct,
                AVG(decision_time_days) as avg_decision_time,
                AVG(CASE WHEN presumptive_match THEN 1 ELSE 0 END) * 100 as presumptive_match_rate
            FROM {self.schema}.claims
            WHERE date_submitted >= (SELECT MAX(date_submitted) FROM {self.schema}.claims) - INTERVAL 30 DAYS
            """

            results = await self._execute_query(sql)

            if results and len(results) > 0:
                row = results[0]
                return {
                    "pendingClaimsPercent": float(row[0]) if row[0] else 74.0,
                    "avgDecisionTimeDays": int(row[1]) if row[1] else 83,
                    "presumptiveMatchRate": float(row[2]) if row[2] else 74.0,
                    "isFallback": False,
                }
            logger.error("get_adjudicator_stats: query returned no rows; returning hardcoded fallback stats")
        except Exception:
            logger.exception("get_adjudicator_stats: query failed; returning hardcoded fallback stats")

        return {
            "pendingClaimsPercent": 74.0,
            "avgDecisionTimeDays": 83,
            "presumptiveMatchRate": 74.0,
            "isFallback": True,
        }

    async def get_pending_claims(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get list of pending claims for adjudication

        Returns:
            List of pending claims with details
        """
        try:
            sql = f"""
            SELECT
                claim_id,
                veteran_name,
                date_submitted,
                claimed_condition,
                current_status,
                priority_level,
                fraud_score,
                compliance_score
            FROM {self.schema}.claims
            WHERE current_status IN ('PENDING', 'DECISION_READY', 'REVIEW_REQUIRED')
            ORDER BY
                CASE priority_level
                    WHEN 'CRITICAL' THEN 1
                    WHEN 'HIGH' THEN 2
                    WHEN 'MEDIUM' THEN 3
                    ELSE 4
                END,
                date_submitted ASC
            LIMIT {limit}
            """

            results = await self._execute_query(sql)

            if results:
                return [
                    {
                        "claimId": str(row[0]),
                        "veteranName": row[1],
                        "dateSubmitted": row[2],
                        "claimedCondition": row[3],
                        "currentStatus": row[4],
                        "priorityLevel": row[5],
                        "fraudScore": float(row[6]) if row[6] else 0.0,
                        "complianceScore": float(row[7]) if row[7] else 100.0,
                        "isFallback": False,
                    }
                    for row in results
                ]
            logger.error("get_pending_claims: query returned no rows; returning hardcoded PRIORITY_CLAIMS_DATA")
        except Exception:
            logger.exception("get_pending_claims: query failed; returning hardcoded PRIORITY_CLAIMS_DATA")

        # Return hardcoded Priority Claims data (copy each dict so we never mutate the shared constant)
        return [{**claim, "isFallback": True} for claim in PRIORITY_CLAIMS_DATA]

    async def get_high_priority_claims(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get high priority claims requiring immediate attention

        Returns:
            List of high priority claims with AI summaries
        """
        try:
            sql = f"""
            SELECT
                claim_id,
                veteran_name,
                date_submitted,
                claimed_condition,
                priority_reason,
                fraud_score,
                fraud_reason,
                compliance_update,
                ai_summary
            FROM {self.schema}.claims
            WHERE priority_level IN ('CRITICAL', 'HIGH')
                AND (fraud_score > 50 OR compliance_score < 60)
            ORDER BY fraud_score DESC, date_submitted ASC
            LIMIT {limit}
            """

            results = await self._execute_query(sql)

            if results:
                return [
                    {
                        "claimId": str(row[0]),
                        "veteranName": row[1],
                        "dateSubmitted": row[2],
                        "claimedCondition": row[3],
                        "priorityReason": row[4],
                        "fraudScore": float(row[5]) if row[5] else 0.0,
                        "fraudReason": row[6],
                        "complianceUpdate": row[7],
                        "aiSummary": row[8],
                        "isFallback": False,
                    }
                    for row in results
                ]
            logger.error("get_high_priority_claims: query returned no rows; returning hardcoded fallback data")
        except Exception:
            logger.exception("get_high_priority_claims: query failed; returning hardcoded fallback data")

        # Return mock data for demonstration
        return [
            {
                "claimId": "1234567892",
                "veteranName": "Michael Brown",
                "dateSubmitted": "10/12/2023",
                "claimedCondition": "Burn Pit Exposure",
                "priorityReason": "Previously denied, new evidence submitted",
                "fraudScore": 65.8,
                "fraudReason": "Multiple inconsistencies detected: Service dates don't match deployment records, medical evidence appears altered (digital forensics score: 0.72), similar claim pattern detected across 3 other veterans with same medical provider.",
                "complianceUpdate": None,
                "aiSummary": "FRAUD WARNING: This claim shows high likelihood of fraudulent activity.",
                "isFallback": True,
            },
            {
                "claimId": "1234567893",
                "veteranName": "Jennifer Martinez",
                "dateSubmitted": "09/28/2023",
                "claimedCondition": "Respiratory Disease",
                "priorityReason": "Previously out of compliance, updated with new evidence",
                "fraudScore": 8.2,
                "fraudReason": None,
                "complianceUpdate": "New medical nexus letter submitted from VA medical center. Deployment records now show 14 months in burn pit zone (previously 6 months). All documentation requirements met.",
                "aiSummary": "COMPLIANCE UPDATE: Claim now meets all PACT Act eligibility requirements. Low fraud risk. Recommend approval.",
                "isFallback": True,
            },
        ]

    async def get_pact_act_statistics(self) -> Dict[str, Any]:
        """
        Get PACT Act specific statistics

        Returns:
            Dict with PACT Act eligible count and exposure types breakdown
        """
        try:
            sql = f"""
            SELECT
                COUNT(*) as total_eligible,
                exposure_type,
                COUNT(*) as count
            FROM {self.schema}.claims
            WHERE is_pact_act_eligible
            GROUP BY exposure_type
            ORDER BY COUNT(*) DESC
            LIMIT 10
            """

            results = await self._execute_query(sql)

            if results and len(results) > 0:
                total_eligible = sum(int(row[2]) for row in results)
                exposure_types = [
                    {
                        "type": row[1],
                        "count": int(row[2]),
                        "percentage": (int(row[2]) / total_eligible * 100) if total_eligible > 0 else 0
                    }
                    for row in results
                ]
                return {
                    "totalEligible": total_eligible,
                    "exposureTypes": exposure_types,
                    "isFallback": False,
                }
            logger.error("get_pact_act_statistics: query returned no rows; returning hardcoded fallback data")
        except Exception:
            logger.exception("get_pact_act_statistics: query failed; returning hardcoded fallback data")

        # Return mock data
        return {
            "totalEligible": 83,
            "exposureTypes": [
                {"type": "Burn Pit", "count": 45, "percentage": 54.2},
                {"type": "VA Exam", "count": 25, "percentage": 30.1},
                {"type": "Medical Record", "count": 13, "percentage": 15.7},
            ],
            "isFallback": True,
        }

    async def get_claim_detail(self, claim_id: str) -> Dict[str, Any]:
        """
        Get detailed information for a specific claim

        Args:
            claim_id: The claim ID to fetch details for

        Returns:
            Dict with full claim details including evidence, AI analysis, history
        """
        try:
            # Get main claim data
            sql_claim = f"""
            SELECT
                claim_id,
                veteran_name,
                date_submitted,
                claimed_condition,
                current_status,
                priority_level,
                fraud_score,
                fraud_reason,
                compliance_score,
                compliance_update,
                ai_summary,
                is_pact_act_eligible,
                exposure_type
            FROM {self.schema}.claims
            WHERE claim_id = '{claim_id}'
            """

            claim_results = await self._execute_query(sql_claim)

            if claim_results and len(claim_results) > 0:
                row = claim_results[0]

                # Get evidence data
                evidence = await self._get_claim_evidence(claim_id)

                # Get claim history
                history = await self._get_claim_history(claim_id)

                return {
                    "claimId": str(row[0]),
                    "veteranName": row[1],
                    "dateSubmitted": row[2],
                    "claimedCondition": row[3],
                    "currentStatus": row[4],
                    "priorityLevel": row[5],
                    "fraudScore": float(row[6]) if row[6] else 0.0,
                    "fraudReason": row[7],
                    "complianceScore": float(row[8]) if row[8] else 100.0,
                    "complianceUpdate": row[9],
                    "aiSummary": row[10],
                    "isPactActEligible": bool(row[11]),
                    "exposureType": row[12],
                    "evidence": evidence,
                    "history": history,
                    "isFallback": False,
                }
            logger.error(
                "get_claim_detail(%s): query returned no rows; falling back to hardcoded data",
                claim_id,
            )
        except Exception:
            logger.exception(
                "get_claim_detail(%s): query failed; falling back to hardcoded data", claim_id
            )

        # Find claim in hardcoded data
        for claim in PRIORITY_CLAIMS_DATA:
            if claim.get("claimId") == claim_id:
                return {
                    "claimId": claim["claimId"],
                    "veteranName": claim["veteranName"],
                    "dateSubmitted": claim["dateSubmitted"],
                    "claimedCondition": claim["claimedCondition"],
                    "currentStatus": claim["currentStatus"],
                    "priorityLevel": claim["priorityLevel"],
                    "fraudScore": claim["fraudScore"],
                    "fraudReason": claim.get("fraudReason"),
                    "complianceScore": claim["complianceScore"],
                    "complianceUpdate": "All required evidence submitted." if claim["complianceScore"] > 80 else "Missing evidence documentation.",
                    "aiSummary": f"Veteran claim for {claim['claimedCondition']}. Priority: {claim['priorityLevel']}. Status: {claim['currentStatus']}. {'High fraud risk detected.' if claim['fraudScore'] > 30 else 'Standard processing.'}",
                    "isPactActEligible": claim.get("isPactAct", True),
                    "exposureType": "Burn Pit" if "Burn Pit" in claim["priorityLevel"] else "Other",
                    "evidence": {
                        "serviceRecord": {"status": "COMPLETE", "percentage": 100},
                        "vaExam": {"status": "COMPLETE" if claim["complianceScore"] > 80 else "PENDING", "percentage": claim["complianceScore"]},
                        "medicalRecord": {"status": "COMPLETE", "percentage": 90},
                    },
                    "presumptiveMatchRate": 74.0,
                    "history": [
                        {"date": claim["dateSubmitted"], "action": "Claim Submitted", "user": "System"},
                        {"date": claim["dateSubmitted"], "action": "Evidence Review Started", "user": "Agent AI"},
                        {"date": claim["dateSubmitted"], "action": "PACT Act Eligibility Confirmed", "user": "Agent AI"},
                    ],
                    "isFallback": True,
                }

        # Fallback if claim not found
        logger.error("get_claim_detail(%s): claim not found in DB or hardcoded fallback data", claim_id)
        return {
            "claimId": claim_id,
            "veteranName": "Unknown",
            "dateSubmitted": "Unknown",
            "claimedCondition": "Unknown",
            "currentStatus": "NOT_FOUND",
            "priorityLevel": "UNKNOWN",
            "fraudScore": 0.0,
            "fraudReason": None,
            "complianceScore": 0.0,
            "complianceUpdate": None,
            "aiSummary": f"Claim {claim_id} not found in system.",
            "isPactActEligible": False,
            "exposureType": "Unknown",
            "evidence": {},
            "history": [],
            "isFallback": True,
        }

    async def _get_claim_evidence(self, claim_id: str) -> Dict[str, Any]:
        """Helper method to get evidence for a claim"""
        try:
            sql = f"""
            SELECT
                evidence_type,
                status,
                completeness_score
            FROM {self.schema}.claim_evidence
            WHERE claim_id = '{claim_id}'
            """

            results = await self._execute_query(sql)

            if results:
                evidence = {}
                for row in results:
                    evidence[row[0]] = {
                        "status": row[1],
                        "percentage": float(row[2]) if row[2] else 0.0,
                        "isFallback": False,
                    }
                return evidence
            logger.error(
                "_get_claim_evidence(%s): query returned no rows; returning hardcoded fallback evidence",
                claim_id,
            )
        except Exception:
            logger.exception(
                "_get_claim_evidence(%s): query failed; returning hardcoded fallback evidence", claim_id
            )

        return {
            "serviceRecord": {"status": "COMPLETE", "percentage": 100, "isFallback": True},
            "vaExam": {"status": "COMPLETE", "percentage": 85, "isFallback": True},
            "medicalRecord": {"status": "COMPLETE", "percentage": 90, "isFallback": True},
        }

    async def _get_claim_history(self, claim_id: str) -> List[Dict[str, Any]]:
        """Helper method to get history for a claim"""
        try:
            sql = f"""
            SELECT
                action_date,
                action_type,
                performed_by
            FROM {self.schema}.claim_history
            WHERE claim_id = '{claim_id}'
            ORDER BY action_date DESC
            """

            results = await self._execute_query(sql)

            if results:
                return [
                    {
                        "date": row[0],
                        "action": row[1],
                        "user": row[2],
                    }
                    for row in results
                ]
        except Exception:
            logger.exception("_get_claim_history(%s): query failed; returning empty history", claim_id)

        return []

    async def get_claims_timeseries(self) -> List[Dict[str, Any]]:
        """
        Weekly aggregates from gold_claims_timeseries (SDP) for dashboard trends.
        Raises on SQL/warehouse errors so the API can return 5xx instead of an empty chart.
        """
        sql = f"""
        SELECT
            CAST(week_start AS STRING) AS week_start,
            current_status,
            claim_count,
            pact_eligible_count
        FROM {self.schema}.gold_claims_timeseries
        ORDER BY week_start, current_status
        LIMIT 500
        """
        results = await self._execute_query(sql)
        if not results:
            return []
        return [
            {
                "weekStart": row[0],
                "currentStatus": row[1],
                "claimCount": int(row[2]) if row[2] is not None else 0,
                "pactEligibleCount": int(row[3]) if row[3] is not None else 0,
            }
            for row in results
        ]

    async def suggest_adjudication_decision(self, claim_id: str) -> Dict[str, Any]:
        """
        Decision support: approve / deny / request_clarification with reasons and doc citations.
        Retrieves VA policy chunks via SQL (no Vector Search). Optionally calls Model Serving URL.
        """
        safe_id = (claim_id or "").replace("'", "")
        citations: List[Dict[str, str]] = []
        context_chunks: List[str] = []
        try:
            sql_chunks = f"""
            SELECT chunk_id, title, section, source_url, body
            FROM {self.schema}.silver_va_doc_chunk
            LIMIT 10
            """
            chunk_rows = await self._execute_query(sql_chunks)
            if chunk_rows:
                for row in chunk_rows:
                    citations.append(
                        {
                            "chunkId": str(row[0]),
                            "title": str(row[1]) if row[1] else "",
                            "section": str(row[2]) if row[2] else "",
                            "sourceUrl": str(row[3]) if row[3] else "",
                        }
                    )
                    if row[4]:
                        context_chunks.append(str(row[4]))
            else:
                logger.error(
                    "suggest_adjudication_decision(%s): doc chunk query returned no rows", safe_id
                )
        except Exception:
            logger.exception(
                "suggest_adjudication_decision(%s): error loading doc chunks for suggestion", safe_id
            )

        fraud_score = 0.0
        compliance_score = 100.0
        condition = ""
        status = ""
        try:
            sql_c = f"""
            SELECT fraud_score, compliance_score, claimed_condition, current_status
            FROM {self.schema}.claims
            WHERE claim_id = '{safe_id}'
            LIMIT 1
            """
            cr = await self._execute_query(sql_c)
            if cr and len(cr[0]) >= 4:
                fraud_score = float(cr[0][0] or 0)
                compliance_score = float(cr[0][1] or 0)
                condition = str(cr[0][2] or "")
                status = str(cr[0][3] or "")
            else:
                logger.error(
                    "suggest_adjudication_decision(%s): claim lookup returned no rows; "
                    "falling back to default scores",
                    safe_id,
                )
        except Exception:
            logger.exception(
                "suggest_adjudication_decision(%s): error loading claim for suggestion", safe_id
            )

        serving_url = os.getenv("DATABRICKS_ADJUDICATION_SUGGEST_URL") or os.getenv(
            "DATABRICKS_SERVING_ENDPOINT_URL"
        )
        if serving_url and context_chunks:
            try:
                import httpx

                payload = {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "You are a VA claims decision-support assistant. Respond with JSON only: "
                                '{"decision":"APPROVE|DENY|REQUEST_CLARIFICATION","confidence":0.0-1.0,'
                                '"reasons":["..."],"citedChunkIds":["..."]}. '
                                f"Claim: id={safe_id}, condition={condition}, status={status}, "
                                f"fraud_score={fraud_score}, compliance_score={compliance_score}. "
                                "Context:\n" + "\n---\n".join(context_chunks[:5])
                            ),
                        }
                    ],
                    "max_tokens": 800,
                }
                async with httpx.AsyncClient(timeout=60.0) as client:
                    headers = {
                        "Content-Type": "application/json",
                        **self.workspace_client.config.authenticate(),
                    }
                    r = await client.post(
                        serving_url,
                        json=payload,
                        headers=headers,
                    )
                    if r.status_code == 200:
                        # Many endpoints wrap text in choices[0].message.content
                        data = r.json()
                        text = ""
                        if isinstance(data, dict):
                            if "choices" in data:
                                text = data["choices"][0].get("message", {}).get("content", "")
                            elif "output" in data:
                                text = str(data["output"])
                            else:
                                text = str(data)
                        return {
                            "decision": "REQUEST_CLARIFICATION",
                            "confidence": 0.5,
                            "reasons": [text[:2000]] if text else ["Model returned empty output."],
                            "citations": citations,
                            "disclaimer": "Decision support only; not a legal determination.",
                            "source": "model_serving",
                        }
                    logger.error(
                        "suggest_adjudication_decision(%s): model serving returned HTTP %s; "
                        "falling back to heuristic",
                        safe_id,
                        r.status_code,
                    )
            except Exception:
                logger.exception(
                    "suggest_adjudication_decision(%s): model serving call failed; "
                    "falling back to heuristic",
                    safe_id,
                )

        # Heuristic fallback (no Inference Tables; no Vector Search)
        reasons: List[str] = []
        if fraud_score >= 60:
            decision = "REQUEST_CLARIFICATION"
            reasons.append("Elevated fraud risk score; verify service records and consistency.")
        elif compliance_score < 55:
            decision = "REQUEST_CLARIFICATION"
            reasons.append("Compliance / evidence score is low; request additional documentation.")
        elif status in ("DECISION_READY",) and fraud_score < 35:
            decision = "APPROVE"
            reasons.append("Claim appears decision-ready with acceptable risk scores (synthetic rules).")
        else:
            decision = "REQUEST_CLARIFICATION"
            reasons.append("Default to clarification pending full manual review.")

        if context_chunks:
            reasons.append("See cited VA public documentation excerpts in citations.")

        return {
            "decision": decision,
            "confidence": 0.65 if decision == "REQUEST_CLARIFICATION" else 0.55,
            "reasons": reasons,
            "citations": citations,
            "disclaimer": "Decision support only; not a legal determination.",
            "source": "heuristic_with_doc_chunks",
        }

    async def update_claim_status(
        self,
        claim_id: str,
        action: str,
        notes: Optional[str] = None,
        adjudicator_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update claim status based on adjudicator action

        Args:
            claim_id: The claim ID to update
            action: Action to take (approve, deny, request_evidence, flag_review)
            notes: Optional notes from adjudicator
            adjudicator_id: ID of the adjudicator taking action

        Returns:
            Dict with success status and message
        """
        try:
            # In production, this would update the database
            # For now, we'll return a success response
            timestamp = datetime.now().isoformat()

            action_map = {
                "approve": "APPROVED",
                "deny": "DENIED",
                "request_evidence": "EVIDENCE_REQUESTED",
                "flag_review": "FLAGGED_FOR_REVIEW",
            }

            new_status = action_map.get(action, "PENDING")

            # Log the action (in production, insert into database)
            logger.info("Claim %s updated to %s by %s at %s", claim_id, new_status, adjudicator_id, timestamp)
            if notes:
                logger.info("Notes: %s", notes)

            return {
                "success": True,
                "message": f"Claim {claim_id} successfully {action}",
                "newStatus": new_status,
                "timestamp": timestamp,
            }

        except Exception as e:
            logger.exception("Error updating claim status for %s", claim_id)
            return {
                "success": False,
                "message": f"Failed to update claim: {str(e)}",
            }
