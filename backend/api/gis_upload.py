"""
GIS Upload API endpoints - GIS file upload and parsing
GIS 上传 API 端点 - GIS 文件上传和解析

支持的 GIS 格式：
- GeoJSON (.geojson, .json)
- Shapefile ZIP (.zip containing .shp/.dbf/.prj)
- KML (.kml)
- KMZ (.kmz)
- GeoTIFF (.tif, .tiff)

不支持：
- ArcGIS Map Package (.mpk) - 专有格式，需导出为通用格式
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from pathlib import Path
import logging
import time
import json

router = APIRouter()

logger = logging.getLogger(__name__)


# ============================================
# Response Schemas
# ============================================

class GISUploadMetadata(BaseModel):
    """GIS upload metadata"""
    file_name: str = Field(..., description="Original file name")
    file_size: int = Field(..., description="File size in bytes")
    file_type: str = Field(..., description="File type: geojson, shapefile, kml, etc.")
    feature_count: int = Field(0, description="Number of features")
    properties: List[str] = Field(default_factory=list, description="Property fields")
    crs: str = Field("EPSG:4326", description="Coordinate reference system")
    uploaded_at: float = Field(..., description="Upload timestamp")


class GISUploadResponse(BaseModel):
    """GIS upload response"""
    success: bool = Field(..., description="Upload success status")
    village_name: str = Field(..., description="Village name for data association")
    data_type: str = Field(..., description="Inferred data type: boundary/water/road/residential/poi/custom")
    geojson: Dict[str, Any] = Field(..., description="Parsed GeoJSON data")
    metadata: GISUploadMetadata = Field(..., description="Upload metadata")
    source: str = Field("user_upload", description="Data source identifier")
    error: Optional[str] = Field(None, description="Error message if failed")


class GISDataStatusResponse(BaseModel):
    """GIS data status response"""
    village_name: str = Field(..., description="Village name")
    user_uploaded: List[str] = Field(default_factory=list, description="User uploaded data types")
    cached: List[str] = Field(default_factory=list, description="Cached data types")
    missing: List[str] = Field(default_factory=list, description="Missing data types")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Data metadata")


# ============================================
# Configuration
# ============================================

# 支持的 GIS 文件扩展名
GIS_EXTENSIONS = {
    '.geojson': 'geojson',
    '.json': 'geojson',
    '.shp': 'shapefile',
    '.zip': 'shapefile',  # ZIP 包含 Shapefile
    '.kml': 'kml',
    '.kmz': 'kmz',
    '.tif': 'geotiff',
    '.tiff': 'geotiff',
}

# 不支持的扩展名（需要友好提示）
UNSUPPORTED_EXTENSIONS = {
    '.mpk': "不支持 ArcGIS Map Package (.mpk) 格式，请使用 ArcGIS Pro 导出为 Shapefile 或 GeoJSON",
    '.mxd': "不支持 ArcGIS Map Document (.mxd) 格式，请导出为 Shapefile 或 GeoJSON",
    '.aprx': "不支持 ArcGIS Pro Project (.aprx) 格式，请导出为 Shapefile 或 GeoJSON",
}

# 最大文件大小限制
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


# ============================================
# Helper Functions
# ============================================

def detect_file_type(filename: str) -> Optional[str]:
    """Detect GIS file type from filename"""
    ext = Path(filename).suffix.lower()
    return GIS_EXTENSIONS.get(ext)


def check_unsupported_format(filename: str) -> Optional[str]:
    """Check if file format is unsupported and return error message"""
    ext = Path(filename).suffix.lower()
    return UNSUPPORTED_EXTENSIONS.get(ext)


# ============================================
# GIS Upload Endpoints
# ============================================

@router.post("/upload", response_model=GISUploadResponse)
async def upload_gis_file(
    file: UploadFile = File(...),
    village_name: str = Form(...),
    data_type: Optional[str] = Form(None),
):
    """
    Upload and parse GIS file
    上传并解析 GIS 文件

    支持格式：GeoJSON, Shapefile (ZIP), KML, KMZ, GeoTIFF
    不支持：ArcGIS Map Package (.mpk) 等专有格式

    Args:
        file: GIS 文件
        village_name: 村庄名称（用于数据关联）
        data_type: 数据类型（可选，自动推断）

    Returns:
        GISUploadResponse 包含解析后的 GeoJSON 和元数据
    """
    try:
        # 检查不支持的格式
        unsupported_error = check_unsupported_format(file.filename or "")
        if unsupported_error:
            raise HTTPException(status_code=400, detail=unsupported_error)

        # 检测文件类型
        file_type = detect_file_type(file.filename or "")
        if file_type is None:
            raise HTTPException(
                status_code=400,
                detail=f"无法识别文件类型: {file.filename}。支持的格式: GeoJSON, Shapefile (ZIP), KML, KMZ, GeoTIFF"
            )

        # 读取文件内容
        content = await file.read()
        file_size = len(content)

        # 检查文件大小
        if file_size == 0:
            raise HTTPException(status_code=400, detail="文件内容为空")
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）")

        logger.info(f"[GISUpload] 收到文件: {file.filename}, 大小: {file_size} bytes, 类型: {file_type}")

        # 解析 GIS 文件
        from src.tools.gis.data_parser import GISDataParser

        parser = GISDataParser()
        result = parser.parse_from_bytes(content, file.filename or "", file_type)

        if not result.success:
            raise HTTPException(status_code=400, detail=result.error or "GIS 文件解析失败")

        # 推断数据类型（如果未指定）
        if data_type is None:
            data_type = parser.infer_data_type(result.geojson)
            logger.info(f"[GISUpload] 自动推断数据类型: {data_type}")

        # 存储到 GISDataManager
        from src.tools.gis.data_manager import GISDataManager

        metadata = {
            'uploaded_at': time.time(),
            'file_name': file.filename,
            'feature_count': result.feature_count,
            'file_size': file_size,
            'file_type': file_type,
        }

        GISDataManager.set_user_data(
            data_type=data_type,
            village_name=village_name,
            geojson=result.geojson,
            metadata=metadata,
        )

        logger.info(f"[GISUpload] 数据已存储: {village_name}/{data_type}, 特征数: {result.feature_count}")

        return GISUploadResponse(
            success=True,
            village_name=village_name,
            data_type=data_type,
            geojson=result.geojson,
            metadata=GISUploadMetadata(
                file_name=file.filename or "",
                file_size=file_size,
                file_type=file_type,
                feature_count=result.feature_count,
                properties=result.properties,
                crs=result.crs,
                uploaded_at=time.time(),
            ),
            source="user_upload",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GISUpload] 文件处理失败: {str(e)}")
        raise HTTPException(status_code=400, detail=f"GIS 文件处理失败: {str(e)}")


@router.get("/status/{village_name}", response_model=GISDataStatusResponse)
async def get_gis_data_status(village_name: str):
    """
    Get GIS data status for a village
    获取指定村庄的 GIS 数据状态

    Args:
        village_name: 村庄名称

    Returns:
        GISDataStatusResponse 包含数据状态概览
    """
    from src.tools.gis.data_manager import GISDataManager

    status = GISDataManager.get_data_status(village_name)

    return GISDataStatusResponse(
        village_name=status['village_name'],
        user_uploaded=status['user_uploaded'],
        cached=status['cached'],
        missing=status['missing'],
        metadata=status['metadata'],
    )


@router.delete("/clear/{village_name}/{data_type}")
async def clear_gis_user_data(village_name: str, data_type: str):
    """
    Clear user uploaded GIS data
    清除用户上传的 GIS 数据

    Args:
        village_name: 村庄名称
        data_type: 数据类型

    Returns:
        Success message
    """
    from src.tools.gis.data_manager import GISDataManager

    GISDataManager.clear_user_data(village_name, data_type)
    logger.info(f"[GISUpload] 用户数据已清除: {village_name}/{data_type}")

    return {"success": True, "message": f"已清除 {village_name}/{data_type} 用户数据"}


@router.get("/supported-formats")
async def get_supported_formats():
    """
    Get supported GIS file formats
    获取支持的 GIS 文件格式列表

    Returns:
        List of supported formats with descriptions
    """
    return {
        "supported": [
            {"ext": ".geojson, .json", "type": "geojson", "description": "GeoJSON 格式，前端直接解析"},
            {"ext": ".zip (含 .shp)", "type": "shapefile", "description": "Shapefile ZIP 包，包含 .shp/.dbf/.prj"},
            {"ext": ".kml", "type": "kml", "description": "Google KML 格式"},
            {"ext": ".kmz", "type": "kmz", "description": "Google KMZ 压缩格式"},
            {"ext": ".tif, .tiff", "type": "geotiff", "description": "GeoTIFF 栅格格式"},
        ],
        "unsupported": [
            {"ext": ".mpk", "type": "ArcGIS Map Package", "description": "ArcGIS 专有格式，请导出为 Shapefile 或 GeoJSON"},
            {"ext": ".mxd", "type": "ArcGIS Map Document", "description": "ArcGIS 专有格式，请导出为 Shapefile 或 GeoJSON"},
        ],
        "max_file_size_mb": MAX_FILE_SIZE // 1024 // 1024,
    }


__all__ = ["router"]