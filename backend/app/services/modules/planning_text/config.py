"""Planning text generation configuration."""

from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class PlanningTextConfig:
    """Configuration for planning text generation."""
    session_id: str
    project_name: str = ""
    village_name: str = ""
    province: str = ""
    city: str = ""
    county: str = ""
    township: str = ""
    planning_period: str = "2022-2035年"
    generate_tier3: bool = True
    output_dir: str = "output/planning_text"
    output_formats: Tuple[str, ...] = ("md", "json")
    append_rag: bool = True

    # Layer export options
    export_layers: bool = False
    layer_output_formats: Tuple[str, ...] = ("md", "json")
    include_rag_details: bool = False
    include_summaries: bool = True
