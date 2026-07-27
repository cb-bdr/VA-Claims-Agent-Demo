"""
Claims Service - Queries Databricks for VA Claims data
"""
import os
from typing import List, Dict, Any, Optional
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState
from datetime import datetime
from server.services.hardcoded_claims_data import PRIORITY_CLAIMS_DATA


class ClaimsService:
    """Service for fetching VA Claims data from Databricks"""
    
    def __init__(self):
        self.workspace_client = WorkspaceClient(
            host=os.getenv("DATABRICKS_HOST"),
            token=os.getenv("DATABRICKS_TOKEN")
        )
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
        Get key performance metrics from gold_claims_throughput_daily
        
        Returns:
            Dict with avgCycleTime, activeClaims, processingRate, veteranImpact
        """
        try:
            # Query for average cycle time and throughput metrics
            sql = """
            SELECT 
                AVG(CASE WHEN cycle_time_hours IS NOT NULL THEN cycle_time_hours ELSE 0 END) as avg_cycle_time,
                COUNT(DISTINCT CASE WHEN status = 'ACTIVE' THEN claim_id END) as active_claims,
                AVG(CASE WHEN processing_rate IS NOT NULL THEN processing_rate ELSE 0 END) * 100 as processing_rate,
                COUNT(DISTINCT veteran_id) as veteran_impact
            FROM ahunt_demo.generatorclaims.gold_claims_throughput_daily
            WHERE date >= CURRENT_DATE - INTERVAL 30 DAYS
            """
            
            results = await self._execute_query(sql)
            
            if results and len(results) > 0:
                row = results[0]
                return {
                    "avgCycleTime": float(row[0]) if row[0] else 28.5,
                    "activeClaims": int(row[1]) if row[1] else 534,
                    "processingRate": float(row[2]) if row[2] else 67.0,
                    "veteranImpact": int(row[3]) if row[3] else 186187,
                }
        except Exception as e:
            print(f"Error fetching metrics: {e}")
        
        # Return default values if query fails
        return {
            "avgCycleTime": 28.5,
            "activeClaims": 534,
            "processingRate": 67.0,
            "veteranImpact": 186187,
        }
    
    async def get_critical_claims(self) -> List[Dict[str, Any]]:
        """
        Get critical claims with delays from gold tables
        
        Returns:
            List of critical claims with name, affected count, and days delayed
        """
        try:
            sql = """
            SELECT 
                claim_type as name,
                COUNT(DISTINCT veteran_id) as affected,
                AVG(DATEDIFF(CURRENT_DATE, claim_date)) as days
            FROM ahunt_demo.generatorclaims.silver_claims_events
            WHERE status IN ('PENDING', 'DELAYED')
                AND DATEDIFF(CURRENT_DATE, claim_date) > 20
            GROUP BY claim_type
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
                    }
                    for row in results
                ]
        except Exception as e:
            print(f"Error fetching critical claims: {e}")
        
        # Return VA-specific mock data if query fails
        return [
            {"name": "Disability Compensation Claims", "affected": 8847, "days": 32},
            {"name": "Post-9/11 GI Bill Education Benefits", "affected": 7234, "days": 28},
            {"name": "VA Healthcare Enrollment", "affected": 5621, "days": 24},
            {"name": "Pension & Survivors Benefits", "affected": 4893, "days": 26},
            {"name": "Vocational Rehabilitation & Employment", "affected": 3756, "days": 22},
            {"name": "VA Home Loan Guarantees", "affected": 3234, "days": 29},
            {"name": "Dependency & Indemnity Compensation", "affected": 2891, "days": 31},
            {"name": "Service-Connected Life Insurance", "affected": 2456, "days": 27},
        ]
    
    async def get_visibility_gaps(self) -> List[Dict[str, Any]]:
        """
        Get visibility gaps by provider and region
        
        Returns:
            List of visibility gaps with provider, product, region, delay, and risk
        """
        try:
            sql = """
            SELECT 
                provider_name as provider,
                claim_type as product,
                region,
                AVG(delay_hours) as delay,
                COUNT(*) as risk
            FROM ahunt_demo.generatorclaims.gold_provider_experience_daily
            WHERE delay_hours > 20
            GROUP BY provider_name, claim_type, region
            ORDER BY AVG(delay_hours) DESC
            LIMIT 10
            """
            
            results = await self._execute_query(sql)
            
            if results:
                return [
                    {
                        "provider": row[0],
                        "product": row[1],
                        "region": row[2],
                        "delay": float(row[3]),
                        "risk": int(row[4]),
                    }
                    for row in results
                ]
        except Exception as e:
            print(f"Error fetching visibility gaps: {e}")
        
        # Return VA-specific mock data if query fails
        return [
            {"provider": "Atlanta Regional Office", "product": "Disability Compensation", "region": "Southeast", "delay": 42.8, "risk": 25342},
            {"provider": "Seattle Regional Office", "product": "Healthcare Enrollment", "region": "Pacific Northwest", "delay": 38.2, "risk": 19320},
            {"provider": "New York Regional Office", "product": "Education Benefits", "region": "Northeast", "delay": 36.7, "risk": 18495},
            {"provider": "Nashville Regional Office", "product": "Pension Claims", "region": "Southeast", "delay": 34.1, "risk": 16850},
            {"provider": "Boston Regional Office", "product": "Vocational Rehab", "region": "Northeast", "delay": 33.8, "risk": 23105},
            {"provider": "Chicago Regional Office", "product": "Home Loans", "region": "Midwest", "delay": 29.4, "risk": 18922},
            {"provider": "Phoenix Regional Office", "product": "DIC Benefits", "region": "Southwest", "delay": 27.9, "risk": 16762},
            {"provider": "Denver Regional Office", "product": "Survivors Benefits", "region": "Mountain", "delay": 26.5, "risk": 11452},
            {"provider": "Los Angeles Regional Office", "product": "Mental Health Claims", "region": "Pacific", "delay": 25.8, "risk": 14892},
            {"provider": "Houston Regional Office", "product": "Burial Benefits", "region": "South Central", "delay": 24.6, "risk": 16602},
        ]
    
    async def get_region_delays(self) -> List[Dict[str, Any]]:
        """
        Get delay statistics by VA region
        
        Returns:
            List of VA regions with normal and delayed percentages
        """
        try:
            sql = """
            SELECT 
                region as name,
                AVG(CASE WHEN delay_hours <= 24 THEN 1 ELSE 0 END) * 100 as normal,
                AVG(CASE WHEN delay_hours > 24 THEN 1 ELSE 0 END) * 100 as delayed
            FROM ahunt_demo.generatorclaims.gold_provider_experience_daily
            WHERE region IS NOT NULL
            GROUP BY region
            ORDER BY AVG(CASE WHEN delay_hours > 24 THEN 1 ELSE 0 END) DESC
            LIMIT 6
            """
            
            results = await self._execute_query(sql)
            
            if results:
                return [
                    {
                        "name": row[0],
                        "normal": float(row[1]),
                        "delayed": float(row[2]),
                    }
                    for row in results
                ]
        except Exception as e:
            print(f"Error fetching region delays: {e}")
        
        # Return VA-specific mock data if query fails (based on actual VA regions)
        return [
            {"name": "Southeast (Atlanta)", "normal": 23.2, "delayed": 76.8},
            {"name": "South Central (Houston)", "normal": 31.5, "delayed": 68.5},
            {"name": "Northeast (New York)", "normal": 42.8, "delayed": 57.2},
            {"name": "Pacific (Los Angeles)", "normal": 48.3, "delayed": 51.7},
            {"name": "Midwest (Chicago)", "normal": 52.1, "delayed": 47.9},
            {"name": "Mountain (Denver)", "normal": 61.4, "delayed": 38.6},
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
            sql = f"""
            SELECT 
                AVG(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) * 100 as pending_pct,
                AVG(decision_time_days) as avg_decision_time,
                AVG(CASE WHEN presumptive_match = 1 THEN 1 ELSE 0 END) * 100 as presumptive_match_rate
            FROM {self.schema}.claims
            WHERE date_submitted >= CURRENT_DATE - INTERVAL 30 DAYS
            """
            
            results = await self._execute_query(sql)
            
            if results and len(results) > 0:
                row = results[0]
                return {
                    "pendingClaimsPercent": float(row[0]) if row[0] else 74.0,
                    "avgDecisionTimeDays": int(row[1]) if row[1] else 83,
                    "presumptiveMatchRate": float(row[2]) if row[2] else 74.0,
                }
        except Exception as e:
            print(f"Error fetching adjudicator stats: {e}")
        
        return {
            "pendingClaimsPercent": 74.0,
            "avgDecisionTimeDays": 83,
            "presumptiveMatchRate": 74.0,
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
                    }
                    for row in results
                ]
        except Exception as e:
            print(f"Error fetching pending claims: {e}")
        
        # Return hardcoded Priority Claims data
        return PRIORITY_CLAIMS_DATA
    
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
                    }
                    for row in results
                ]
        except Exception as e:
            print(f"Error fetching high priority claims: {e}")
        
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
            WHERE is_pact_act_eligible = 1
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
                }
        except Exception as e:
            print(f"Error fetching PACT Act statistics: {e}")
        
        # Return mock data
        return {
            "totalEligible": 83,
            "exposureTypes": [
                {"type": "Burn Pit", "count": 45, "percentage": 54.2},
                {"type": "VA Exam", "count": 25, "percentage": 30.1},
                {"type": "Medical Record", "count": 13, "percentage": 15.7},
            ],
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
                }
        except Exception as e:
            print(f"Error fetching claim detail: {e}")
        
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
                }
        
        # Fallback if claim not found
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
                        "percentage": float(row[2]) if row[2] else 0.0
                    }
                return evidence
        except Exception as e:
            print(f"Error fetching evidence: {e}")
        
        return {
            "serviceRecord": {"status": "COMPLETE", "percentage": 100},
            "vaExam": {"status": "COMPLETE", "percentage": 85},
            "medicalRecord": {"status": "COMPLETE", "percentage": 90},
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
        except Exception as e:
            print(f"Error fetching history: {e}")
        
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
        except Exception as e:
            print(f"Error loading doc chunks for suggestion: {e}")

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
        except Exception as e:
            print(f"Error loading claim for suggestion: {e}")

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
                    token = os.getenv("DATABRICKS_TOKEN", "")
                    r = await client.post(
                        serving_url,
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                        },
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
            except Exception as e:
                print(f"Model serving suggestion failed: {e}")

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
            print(f"Claim {claim_id} updated to {new_status} by {adjudicator_id} at {timestamp}")
            if notes:
                print(f"Notes: {notes}")
            
            return {
                "success": True,
                "message": f"Claim {claim_id} successfully {action}",
                "newStatus": new_status,
                "timestamp": timestamp,
            }
            
        except Exception as e:
            print(f"Error updating claim status: {e}")
            return {
                "success": False,
                "message": f"Failed to update claim: {str(e)}",
            }

