"""API routes for querying the 2024 administrative code dataset (china_area-2024)."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.modules.parsing.admin_code_loader import get_admin_code_service

router = APIRouter(prefix="/api/admin-codes", tags=["Admin Codes"])


@router.get("/stats")
async def admin_code_stats():
    """Get statistics about the loaded administrative code dataset."""
    service = get_admin_code_service()
    return service.stats()


@router.get("/provinces")
async def list_provinces():
    """List all provinces (level 1)."""
    service = get_admin_code_service()
    return [r.to_dict() for r in service.get_provinces()]


@router.get("/code/{code}")
async def get_by_code(code: str):
    """Get a single administrative division by its 12-digit code."""
    service = get_admin_code_service()
    record = service.get_by_code(code)
    if not record:
        raise HTTPException(status_code=404, detail=f"Code not found: {code}")
    chain = [{"code": c, "name": n, "level": l} for c, n, l in service.get_parent_chain_with_names(code)]
    return {**record.to_dict(), "parent_chain": chain}


@router.get("/code/{code}/children")
async def get_children(code: str):
    """Get all direct children of a given administrative code."""
    service = get_admin_code_service()
    children = service.get_children(code)
    return [r.to_dict() for r in children]


@router.get("/search")
async def search(
    keyword: str = Query(..., description="Keyword to search by name"),
    level: Optional[int] = Query(None, description="Filter by level (1-5)"),
    limit: int = Query(20, description="Max results"),
):
    """Search administrative divisions by name (substring match)."""
    service = get_admin_code_service()
    results = service.search(keyword, level=level, limit=limit)
    return [r.to_dict() for r in results]


@router.get("/resolve")
async def resolve_hierarchy(
    province: str = Query("", description="Province name"),
    city: str = Query("", description="City name"),
    county: str = Query("", description="County name"),
    town: str = Query("", description="Town name"),
    village: str = Query("", description="Village name"),
):
    """Resolve an administrative hierarchy from names to codes."""
    service = get_admin_code_service()
    return service.resolve_hierarchy(province=province, city=city, county=county, town=town, village=village)


@router.get("/hierarchy/{code}")
async def get_hierarchy(code: str):
    """Get the full parent chain (province→city→county→town→village) for a code."""
    service = get_admin_code_service()
    chain = service.get_parent_chain_with_names(code)
    if not chain:
        raise HTTPException(status_code=404, detail=f"Code not found: {code}")
    return [{"code": c, "name": n, "level": l} for c, n, l in chain]