"""Schema validation utilities for GIS modules.

Enforces that GIS data flows through typed models, not raw GeoJSON.
"""

from typing import Type, get_origin, get_args, Any, Dict, List, Optional, Union
import inspect
import functools
from app.utils.logger import get_logger

logger = get_logger(__name__)


def validate_ingestion_point(func):
    """Decorator: enforce that function consumes typed GIS models, not raw dicts.
    
    Failed decorators should log warnings but NOT block execution.
    Usage: @validate_ingestion_point -> function accepts models, not GeoJSON.
    """
    sig = inspect.signature(func)
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Also apply to class methods
        obj = args[0] if args and hasattr(args[0], '__class__') else None
        
        # Check first parameter (self/class) is not the issue
        valid_initial_args = 1 if obj else 0
        
        # Inspect positional and keyword arguments
        for i, arg_name in enumerate(sig.parameters):
            param = sig.parameters[arg_name]
            
            if i < valid_initial_args:
                continue  # Skip self, cls
            
            # Determine argument value
            if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD, param.VAR_POSITIONAL):
                arg_value = args[i - valid_initial_args] if i - valid_initial_args < len(args) else None
            
            elif arg_name in kwargs:
                arg_value = kwargs[arg_name]
            
            else:
                continue
            
            # Reject raw dict or GeoJSON if type hint expects model
            expected_param_type = param.annotation if param.annotation != inspect.Signature.empty else None
            
            if expected_param_type:
                if arg_value is None:
                    continue
                
                # Extract generic type from typing.List[SomeModel]
                origin = get_origin(expected_param_type)
                if origin is list and param.annotation != list[dict]:  # Not expecting list[dict]
                    elem_type = get_args(expected_param_type)[0] if get_args(expected_param_type) else dict
                    
                    # Unwrap Union types (e.g., List[Union[SpatialOperation, dict]])
                    origin_elem = get_origin(elem_type)
                    if origin_elem is not None:
                        elem_type = origin_elem

                # Reject raw dict
                if isinstance(arg_value, dict):
                    # Check if this parameter is ALLOWED to receive dict (e.g., gis_data: Dict[str, Any])
                    if is_gis_data_bundle(arg_value):
                        logger.warning(
                            f"[SchemaInjection] {func.__qualname__} parameter '{arg_name}' "
                            f"received GIS data bundle (Dict). This is acceptable at module entry points."
                        )
                    else:
                        logger.warning(
                            f"[SchemaInjection] {func.__qualname__} parameter '{arg_name}' "
                            f"received raw GeoJSON-like dict: {list(arg_value.keys())[:5]}... "
                            f"Expected: {expected_param_type}. "
                            f"Import from app/modules.gis.schema for typed models."
                        )
        
        return func(*args, **kwargs)
    
    return wrapper


def is_gis_data_bundle(data: Dict[str, Any]) -> bool:
    """Check if dict is a GIS data bundle (allowed at module entry)."""
    if not isinstance(data, dict):
        return False
    
    # Check for common GIS bundle indicators
    indicators = ["features", "geometry", "boundary", "landuse", "properties", "coordinates"]
    return any(ind in str(data) for ind in indicators)


def validate_model_type(result: Any, expected_type: Type) -> bool:
    """Validate that result matches expected type."""
    if result is None:
        return True  # None is acceptable
    
    if isinstance(result, expected_type):
        return True
    
    # Wrapped in dict
    if isinstance(result, dict):
        if expected_type.__name__ in result:
            return True
        
    # Type mismatch warning
    logger.warning(
        f"[SchemaOutput] Return type mismatch: expected {expected_type.__name__}, "
        f"got {type(result).__name__}"
    )
    return False


def normalize_geste(target_objects: List[Any], expected_type: Type) -> List[Any]:
    """Normalize list of objects to expected type."""
    if not isinstance(target_objects, list):
        return []
    
    normalized = []
    for obj in target_objects:
        if isinstance(obj, expected_type):
            normalized.append(obj)
        else:
            # Wrap dict in model if possible
            if isinstance(obj, dict):
                try:
                    normalized.append(expected_type(**obj))
                except Exception as e:
                    logger.warning(f"[SchemaNormalize] Failed to validate {expected_type.__name__}: {e}")
    
    return normalized


__all__ = [
    "validate_ingestion_point",
    "is_gis_data_bundle",
    "validate_model_type",
    "normalize_geste",
]
