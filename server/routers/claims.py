"""
Claims Router - Provides endpoints for VA Claims Dashboard
"""
from fastapi import APIRouter, HTTPException, Body, Query
from fastapi.responses import StreamingResponse
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from pydantic import BaseModel
from server.services.claims_service import ClaimsService
from server.services import genie_conversation_client as genie_conv
from databricks.sdk import WorkspaceClient
import httpx
import os
import json

router = APIRouter(prefix="/claims", tags=["claims"])


class ClaimMetrics(BaseModel):
    avgCycleTime: float
    activeClaims: int
    processingRate: float
    veteranImpact: int
    isFallback: bool = False


class CriticalClaim(BaseModel):
    name: str
    affected: int
    days: int
    isFallback: bool = False


class VisibilityGap(BaseModel):
    provider: str
    product: str
    region: str
    delay: float
    risk: int
    isFallback: bool = False


class RegionDelay(BaseModel):
    name: str
    normal: float
    delayed: float
    isFallback: bool = False


class DashboardData(BaseModel):
    metrics: ClaimMetrics
    criticalClaims: List[CriticalClaim]
    visibilityGaps: List[VisibilityGap]
    regionDelays: List[RegionDelay]
    dataIntegrity: float
    compliance: float


@router.get("/dashboard", response_model=DashboardData)
async def get_dashboard_data() -> DashboardData:
    """
    Get comprehensive dashboard data for VA Claims Command Center
    
    Returns:
        DashboardData: Complete dashboard metrics and data
    """
    try:
        service = ClaimsService()
        data = await service.get_dashboard_data()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch dashboard data: {str(e)}")


@router.get("/metrics", response_model=ClaimMetrics)
async def get_metrics() -> ClaimMetrics:
    """
    Get key claims metrics
    
    Returns:
        ClaimMetrics: Key performance indicators
    """
    try:
        service = ClaimsService()
        metrics = await service.get_metrics()
        return metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch metrics: {str(e)}")


@router.get("/critical", response_model=List[CriticalClaim])
async def get_critical_claims() -> List[CriticalClaim]:
    """
    Get critical claims with delays
    
    Returns:
        List[CriticalClaim]: List of critical claims
    """
    try:
        service = ClaimsService()
        claims = await service.get_critical_claims()
        return claims
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch critical claims: {str(e)}")


# ============================================================================
# PACT ACT CLAIMS ADJUDICATION ENDPOINTS
# ============================================================================

class AdjudicatorStats(BaseModel):
    pendingClaimsPercent: float
    avgDecisionTimeDays: int
    presumptiveMatchRate: float
    isFallback: bool = False


class PendingClaim(BaseModel):
    claimId: str
    veteranName: str
    dateSubmitted: str
    claimedCondition: str
    currentStatus: str
    priorityLevel: str
    fraudScore: float
    complianceScore: float
    isPactAct: Optional[bool] = True
    isFallback: bool = False


class HighPriorityClaim(BaseModel):
    claimId: str
    veteranName: str
    dateSubmitted: str
    claimedCondition: str
    priorityReason: str
    fraudScore: float
    fraudReason: Optional[str]
    complianceUpdate: Optional[str]
    aiSummary: str
    isFallback: bool = False


class PactActStats(BaseModel):
    totalEligible: int
    exposureTypes: List[Dict[str, Any]]
    isFallback: bool = False


class AdjudicationDashboardData(BaseModel):
    adjudicatorStats: AdjudicatorStats
    pendingClaims: List[PendingClaim]
    highPriorityClaims: List[HighPriorityClaim]
    pactActStats: PactActStats


class ClaimDetailEvidence(BaseModel):
    serviceRecord: Dict[str, Any]
    vaExam: Dict[str, Any]
    medicalRecord: Dict[str, Any]


class ClaimHistoryItem(BaseModel):
    date: str
    action: str
    user: str


class ClaimDetail(BaseModel):
    claimId: str
    veteranName: str
    dateSubmitted: str
    claimedCondition: str
    currentStatus: str
    priorityLevel: str
    fraudScore: float
    fraudReason: Optional[str]
    complianceScore: float
    complianceUpdate: Optional[str]
    aiSummary: str
    isPactActEligible: bool
    exposureType: str
    evidence: ClaimDetailEvidence
    presumptiveMatchRate: Optional[float] = 74.0
    history: List[ClaimHistoryItem]
    isFallback: bool = False


class ClaimActionRequest(BaseModel):
    action: str
    notes: Optional[str] = None
    adjudicatorId: Optional[str] = None


class ClaimActionResponse(BaseModel):
    success: bool
    message: str
    newStatus: Optional[str] = None
    timestamp: Optional[str] = None


class TimeseriesRow(BaseModel):
    weekStart: str
    currentStatus: str
    claimCount: int
    pactEligibleCount: int


class GenieVerifyResponse(BaseModel):
    ok: bool
    statusCode: Optional[int] = None
    detail: Optional[str] = None


class GenieConversationStatusResponse(BaseModel):
    configured: bool


class GenieAskRequest(BaseModel):
    content: str
    conversation_id: Optional[str] = None


class GenieAskResponse(BaseModel):
    conversation_id: str
    message_id: str


class AdjudicationSuggestionRequest(BaseModel):
    claimId: str


class AdjudicationSuggestionResponse(BaseModel):
    decision: str
    confidence: float
    reasons: List[str]
    citations: List[Dict[str, Any]]
    disclaimer: str
    source: str


@router.get("/adjudication/timeseries", response_model=List[TimeseriesRow])
async def get_adjudication_timeseries() -> List[TimeseriesRow]:
    """Gold-layer weekly claim counts for dashboard trends (SDP `gold_claims_timeseries`)."""
    try:
        service = ClaimsService()
        rows = await service.get_claims_timeseries()
        return [TimeseriesRow(**r) for r in rows]
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch adjudication timeseries: {str(e)}"
        )


@router.get("/genie/verify", response_model=GenieVerifyResponse)
async def verify_genie_space(url: str = Query(..., min_length=16, max_length=2048)) -> GenieVerifyResponse:
    """
    Best-effort check that a Genie space URL is reachable on the configured workspace,
    authenticated via the SDK's unified auth (CLI profile, OAuth U2M, or the app service
    principal when deployed) rather than a raw PAT. Used before embedding Genie in an iframe.
    """
    try:
        workspace_client = WorkspaceClient()
        headers = workspace_client.config.authenticate()
        cfg_host = urlparse(workspace_client.config.host or "").hostname
    except Exception as e:
        return GenieVerifyResponse(ok=False, detail=f"Databricks auth not configured on app: {e}")

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Genie URL must use https")
    host = (parsed.hostname or "").lower()
    if not (host.endswith("databricks.com") or host.endswith("azuredatabricks.net")):
        raise HTTPException(
            status_code=400,
            detail="Genie URL host must be a Databricks cloud domain",
        )

    if cfg_host and host != cfg_host.lower():
        raise HTTPException(
            status_code=400,
            detail=f"Genie URL host must match DATABRICKS_HOST ({cfg_host})",
        )

    try:
        async with httpx.AsyncClient() as client:
            head = await client.head(url, headers=headers, follow_redirects=True, timeout=25.0)
            code = head.status_code
            # Many UIs return 404 for HEAD while GET serves the SPA (Genie included).
            if code in (404, 405):
                get_resp = await client.get(
                    url, headers=headers, follow_redirects=True, timeout=25.0
                )
                code = get_resp.status_code
        if code >= 400:
            return GenieVerifyResponse(
                ok=False, statusCode=code, detail=f"Genie URL returned HTTP {code}"
            )
        return GenieVerifyResponse(ok=True, statusCode=code)
    except httpx.HTTPError as e:
        return GenieVerifyResponse(ok=False, detail=str(e))


def _genie_ask_impl(body: GenieAskRequest) -> GenieAskResponse:
    if not genie_conv.is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Genie conversation API not configured. Set DATABRICKS_GENIE_SPACE_ID "
                "(or DATABRICKS_GENIE_SPACE_URL with /genie/rooms/{id}), and ensure Databricks "
                "auth resolves (CLI profile, OAuth U2M, or the app service principal)."
            ),
        )
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    space_id = genie_conv.get_genie_space_id()
    try:
        raw = (
            genie_conv.create_message(space_id, body.conversation_id, content)
            if body.conversation_id
            else genie_conv.start_conversation(space_id, content)
        )
        if isinstance(raw.get("result"), dict):
            raw = raw["result"]
        conv = raw.get("conversation") or {}
        msg = raw.get("message") or {}
        conversation_id = (
            (conv.get("id") or conv.get("conversation_id"))
            or raw.get("conversation_id")
            or (body.conversation_id if body.conversation_id else None)
        )
        message_id = msg.get("message_id") or msg.get("id") or raw.get("message_id") or raw.get("id")
        if not conversation_id or not message_id:
            keys = list(raw.keys()) if isinstance(raw, dict) else []
            raise HTTPException(
                status_code=502,
                detail=f"Unexpected Genie API response shape (top-level keys: {keys})",
            )
        return GenieAskResponse(conversation_id=str(conversation_id), message_id=str(message_id))
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        snippet = (e.response.text or "")[:500] if e.response is not None else ""
        raise HTTPException(
            status_code=502,
            detail=f"Genie API HTTP {e.response.status_code if e.response else '?'}: {snippet or str(e)}",
        ) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/genie/conversation/status", response_model=GenieConversationStatusResponse)
async def genie_conversation_status() -> GenieConversationStatusResponse:
    """Whether server can proxy Genie Conversation API (token + host + space id)."""
    return GenieConversationStatusResponse(configured=genie_conv.is_configured())


@router.post("/genie/conversation/ask", response_model=GenieAskResponse)
async def genie_conversation_ask(body: GenieAskRequest) -> GenieAskResponse:
    """Start or continue a Genie conversation; poll with GET /genie/conversation/message."""
    return _genie_ask_impl(body)


@router.get("/genie/conversation/message")
async def genie_conversation_get_message(
    conversation_id: str = Query(..., min_length=1),
    message_id: str = Query(..., min_length=1),
) -> Dict[str, Any]:
    if not genie_conv.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Genie conversation API not configured.",
        )
    space_id = genie_conv.get_genie_space_id()
    try:
        raw = genie_conv.get_message(space_id, conversation_id, message_id)
    except httpx.HTTPStatusError as e:
        snippet = (e.response.text or "")[:500] if e.response is not None else ""
        raise HTTPException(
            status_code=502,
            detail=f"Genie API HTTP {e.response.status_code if e.response else '?'}: {snippet or str(e)}",
        ) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {
        "status": raw.get("status") or "UNKNOWN",
        "content": raw.get("content"),
        "attachments": raw.get("attachments"),
        "error": raw.get("error"),
    }


@router.post("/adjudication/suggest", response_model=AdjudicationSuggestionResponse)
async def post_adjudication_suggest(
    body: AdjudicationSuggestionRequest,
) -> AdjudicationSuggestionResponse:
    """
    Near-real-time adjudication suggestion (approve / deny / request clarification).
    Uses SQL-selected policy chunks; optional Model Serving via DATABRICKS_ADJUDICATION_SUGGEST_URL
    or DATABRICKS_SERVING_ENDPOINT_URL. No Vector Search or Inference Tables.
    """
    try:
        service = ClaimsService()
        data = await service.suggest_adjudication_decision(body.claimId)
        return AdjudicationSuggestionResponse(**data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Adjudication suggest failed: {str(e)}")


@router.get("/adjudication/dashboard", response_model=AdjudicationDashboardData)
async def get_adjudication_dashboard() -> AdjudicationDashboardData:
    """
    Get complete adjudication dashboard data for PACT Act claims
    
    Returns:
        AdjudicationDashboardData: Complete dashboard with stats, pending, and high priority claims
    """
    try:
        service = ClaimsService()
        data = await service.get_adjudication_dashboard()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch adjudication dashboard: {str(e)}")


@router.get("/adjudication/stats", response_model=AdjudicatorStats)
async def get_adjudicator_stats() -> AdjudicatorStats:
    """
    Get statistics for the current adjudicator
    
    Returns:
        AdjudicatorStats: Adjudicator performance statistics
    """
    try:
        service = ClaimsService()
        stats = await service.get_adjudicator_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch adjudicator stats: {str(e)}")


@router.get("/adjudication/pending", response_model=List[PendingClaim])
async def get_pending_claims(limit: int = 50) -> List[PendingClaim]:
    """
    Get list of pending claims for adjudication
    
    Args:
        limit: Maximum number of claims to return
        
    Returns:
        List[PendingClaim]: List of pending claims
    """
    try:
        service = ClaimsService()
        claims = await service.get_pending_claims(limit=limit)
        return claims
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch pending claims: {str(e)}")


@router.get("/adjudication/high-priority", response_model=List[HighPriorityClaim])
async def get_high_priority_claims(limit: int = 20) -> List[HighPriorityClaim]:
    """
    Get high priority claims requiring immediate attention
    
    Args:
        limit: Maximum number of claims to return
        
    Returns:
        List[HighPriorityClaim]: List of high priority claims with AI summaries
    """
    try:
        service = ClaimsService()
        claims = await service.get_high_priority_claims(limit=limit)
        return claims
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch high priority claims: {str(e)}")


@router.get("/adjudication/pact-act-stats", response_model=PactActStats)
async def get_pact_act_stats() -> PactActStats:
    """
    Get PACT Act specific statistics
    
    Returns:
        PactActStats: PACT Act eligibility and exposure statistics
    """
    try:
        service = ClaimsService()
        stats = await service.get_pact_act_statistics()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch PACT Act stats: {str(e)}")


@router.get("/adjudication/claim/{claim_id}", response_model=ClaimDetail)
async def get_claim_detail(claim_id: str) -> ClaimDetail:
    """
    Get detailed information for a specific claim
    
    Args:
        claim_id: The claim ID to fetch details for
        
    Returns:
        ClaimDetail: Full claim details with evidence and history
    """
    try:
        service = ClaimsService()
        detail = await service.get_claim_detail(claim_id)
        return detail
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch claim detail: {str(e)}")


@router.post("/adjudication/claim/{claim_id}/action", response_model=ClaimActionResponse)
async def update_claim_status(
    claim_id: str,
    action_request: ClaimActionRequest = Body(...)
) -> ClaimActionResponse:
    """
    Update claim status based on adjudicator action
    
    Args:
        claim_id: The claim ID to update
        action_request: Action details (action, notes, adjudicatorId)
        
    Returns:
        ClaimActionResponse: Success status and new claim status
    """
    try:
        service = ClaimsService()
        result = await service.update_claim_status(
            claim_id=claim_id,
            action=action_request.action,
            notes=action_request.notes,
            adjudicator_id=action_request.adjudicatorId
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update claim status: {str(e)}")


class AgentEvaluationRequest(BaseModel):
    claimant_id: str


@router.post("/evaluate-agent")
async def evaluate_claim_with_agent(request: AgentEvaluationRequest):
    """
    Proxy endpoint to call Databricks VBA Claims Agent with streaming
    """
    endpoint_url = os.getenv("DATABRICKS_SERVING_ENDPOINT_URL")
    if not endpoint_url:
        raise HTTPException(status_code=500, detail="DATABRICKS_SERVING_ENDPOINT_URL environment variable not set")
    try:
        auth_headers = WorkspaceClient().config.authenticate()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Databricks auth not configured on app: {e}")

    async def stream_response():
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Format for Databricks Agent Framework
                payload = {
                    "input": [{
                        "status": None,
                        "content": f"Evaluate the eligibility for claimant {request.claimant_id}",
                        "role": "user",
                        "type": "message"
                    }],
                    "max_output_tokens": 4000,
                    "stream": True
                }

                async with client.stream(
                    'POST',
                    endpoint_url,
                    json=payload,
                    headers={
                        'Content-Type': 'application/json',
                        **auth_headers,
                    }
                ) as response:
                    response.raise_for_status()
                    
                    async for line in response.aiter_lines():
                        if line.strip():
                            # Forward SSE format as-is
                            yield f"{line}\n"
        except httpx.HTTPStatusError as e:
            error_msg = json.dumps({
                'id': 'error',
                'content': f'HTTP {e.response.status_code}: {str(e)}'
            })
            yield f"data: {error_msg}\n\n"
        except Exception as e:
            error_msg = json.dumps({
                'id': 'error', 
                'content': f'Error: {str(e)}'
            })
            yield f"data: {error_msg}\n\n"
    
    return StreamingResponse(
        stream_response(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


