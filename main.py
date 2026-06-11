from mcp.server.fastmcp import FastMCP

from services import (
    get_anomalies_atomic_service,
    get_complaints_atomic_service,
    get_faults_atomic_service,
    get_metrics_atomic_service,
    get_stations_atomic_service,
)

mcp = FastMCP("Telecom_NOC_Atomic_Tools")


@mcp.tool()
def get_faults(
    cell_id: str = "all",
    region: str = "all",
    severity: str = "all",
    fault_type: str = "all",
    resolved: str = "all",
    window_min: int = 60,
    limit: int = 200,
):
    """Fault tablosunu filtreleyerek getirir."""
    return get_faults_atomic_service(
        cell_id=cell_id,
        region=region,
        severity=severity,
        fault_type=fault_type,
        resolved=resolved,
        window_min=window_min,
        limit=limit,
    )


@mcp.tool()
def get_complaints(
    cell_id: str = "all",
    region: str = "all",
    issue: str = "all",
    window_min: int = 60,
    limit: int = 200,
):
    """Complaints tablosunu filtreleyerek getirir."""
    return get_complaints_atomic_service(
        cell_id=cell_id,
        region=region,
        issue=issue,
        window_min=window_min,
        limit=limit,
    )


@mcp.tool()
def get_anomalies(
    cell_id: str = "all",
    region: str = "all",
    severity: str = "all",
    only_anomalies: bool = True,
    window_min: int = 60,
    limit: int = 200,
):
    """Anomaly_results tablosunu filtreleyerek getirir."""
    return get_anomalies_atomic_service(
        cell_id=cell_id,
        region=region,
        severity=severity,
        only_anomalies=only_anomalies,
        window_min=window_min,
        limit=limit,
    )


@mcp.tool()
def get_metrics(
    cell_id: str = "all",
    region: str = "all",
    slice_type: str = "all",
    window_min: int = 60,
    limit: int = 200,
):
    """Network metrics tablosunu filtreleyerek getirir."""
    return get_metrics_atomic_service(
        cell_id=cell_id,
        region=region,
        slice_type=slice_type,
        window_min=window_min,
        limit=limit,
    )


@mcp.tool()
def get_stations(
    cell_id: str = "all",
    region: str = "all",
    status: str = "all",
    limit: int = 200,
):
    """Base stations tablosunu filtreleyerek getirir."""
    return get_stations_atomic_service(
        cell_id=cell_id,
        region=region,
        status=status,
        limit=limit,
    )


if __name__ == "__main__":
    mcp.run()
