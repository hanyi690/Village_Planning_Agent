"""Stage-2.5 manual spatial confirmation for road-planning demands.

This module creates a deterministic review queue and a browser map for manual
point placement.  It never derives a village centre from planned roads,
project geometries, hazard points, or similarly named features.  Confirmations
must contain a real Point geometry and human provenance before they can be
applied to the Stage-2 outputs.
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import math
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from .schemas import LocationConfirmationConfig, LocationConfirmationResult


SCHEMA_VERSION = "1.0"


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _norm(value: Any) -> str:
    text = "" if value is None else str(value)
    return "".join(character for character in text.strip().lower() if character not in " \t\r\n_（）()、,，;；:：-—–/")


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_generalized_or_route(place_name: str) -> bool:
    text = str(place_name or "").strip()
    if text in {"", "全村", "各自然村", "金田村", "村内"}:
        return True
    return any(token in text for token in ("-", "—", "–", "至", "到", "经过"))


def _task_sources(demands: Mapping[str, Any], projects: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    official_places = sorted(
        {
            feature["properties"].get("place_name")
            for feature in demands.get("features", [])
            if feature.get("properties", {}).get("demand_type") == "settlement"
            and feature["properties"].get("place_name")
        }
    )
    place_sources: MutableMapping[str, List[Dict[str, Any]]] = defaultdict(list)
    for feature in demands.get("features", []):
        properties = feature.get("properties") or {}
        place = properties.get("place_name")
        if (
            properties.get("location_status") != "matched"
            and place
            and not _is_generalized_or_route(str(place))
        ):
            place_sources[str(place)].append(
                {"object_type": "demand", "object_id": properties.get("demand_id")}
            )

    endpoint_tasks: List[Dict[str, Any]] = []
    for project in projects.get("projects", []):
        project_id = project.get("project_id")
        for role, label in (("start", "起点"), ("end", "终点")):
            place_field = f"{role}_place"
            status_field = f"{role}_location_status"
            place = project.get(place_field)
            if place and project.get(status_field) != "matched" and not _is_generalized_or_route(str(place)):
                place_sources[str(place)].append(
                    {"object_type": "road_project", "object_id": project_id, "endpoint_role": role}
                )
            elif not place:
                endpoint_tasks.append(
                    {
                        "task_type": "road_endpoint",
                        "project_id": project_id,
                        "endpoint_role": role,
                        "display_name": f"{project_id} {project.get('name', '道路项目')}{label}",
                        "instruction": f"请根据原始证据在地图上点击{project.get('name', '道路项目')}的{label}。",
                        "source_objects": [{"object_type": "road_project", "object_id": project_id}],
                        "evidence": project.get("evidence"),
                    }
                )

    tasks: List[Dict[str, Any]] = []
    official_order = {_norm(value): index for index, value in enumerate(official_places)}
    for place_name in sorted(
        place_sources,
        key=lambda value: (
            0 if _norm(value) in official_order else 1,
            official_order.get(_norm(value), 9999),
            _norm(value),
            value,
        ),
    ):
        suggestions = difflib.get_close_matches(place_name, official_places, n=3, cutoff=0.72)
        suggestions = [value for value in suggestions if _norm(value) != _norm(place_name)]
        tasks.append(
            {
                "task_type": "place",
                "place_name": place_name,
                "display_name": place_name,
                "instruction": f"请在现状地图上点击“{place_name}”的代表点。",
                "source_objects": place_sources[place_name],
                "suggested_aliases": suggestions,
            }
        )
    endpoint_tasks.sort(
        key=lambda item: (
            item["project_id"],
            0 if item["endpoint_role"] == "start" else 1,
        )
    )
    tasks.extend(endpoint_tasks)
    for index, task in enumerate(tasks, 1):
        task["task_id"] = f"LC{index:03d}"
        task["status"] = "pending"
    return tasks, official_places


def _constraint_tasks(constraints: Mapping[str, Any]) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    for constraint in constraints.get("constraints", []):
        if not constraint.get("requires_human_confirmation"):
            continue
        tasks.append(
            {
                "constraint_id": constraint.get("constraint_id"),
                "target_layer": constraint.get("target_layer"),
                "description": constraint.get("description"),
                "parameter": "buffer_m",
                "value": None,
                "unit": "m",
                "confirmed_by": None,
                "confirmed_at": None,
                "basis": None,
                "status": "pending",
                "evidence_id": (constraint.get("evidence") or {}).get("evidence_id"),
            }
        )
    return tasks


def _copy_maplibre_assets(config: LocationConfirmationConfig) -> Tuple[str, str, str]:
    if config.maplibre_dist_dir is not None:
        js_source = config.maplibre_dist_dir / "maplibre-gl.js"
        css_source = config.maplibre_dist_dir / "maplibre-gl.css"
        if js_source.exists() and css_source.exists():
            shutil.copyfile(js_source, config.output_dir / "maplibre-gl.js")
            shutil.copyfile(css_source, config.output_dir / "maplibre-gl.css")
            return "maplibre-gl.js", "maplibre-gl.css", "local"
    return (
        "https://unpkg.com/maplibre-gl@5.22.0/dist/maplibre-gl.js",
        "https://unpkg.com/maplibre-gl@5.22.0/dist/maplibre-gl.css",
        "cdn_fallback",
    )


def _safe_script_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def _map_html(
    *,
    tasks: Sequence[Mapping[str, Any]],
    constraint_tasks: Sequence[Mapping[str, Any]],
    boundary: Mapping[str, Any],
    roads: Mapping[str, Any],
    js_url: str,
    css_url: str,
    storage_key: str,
) -> str:
    template = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>道路规划阶段2.5：空间位置确认</title>
  <link rel="stylesheet" href="__CSS_URL__" />
  <style>
    *{box-sizing:border-box} body{margin:0;font-family:"Microsoft YaHei",sans-serif;color:#172033;background:#eef2f6}
    #app{display:grid;grid-template-columns:360px 1fr;height:100vh}.panel{padding:16px;background:white;overflow:auto;border-right:1px solid #d9e0e8}
    h1{font-size:18px;margin:0 0 8px}.hint{font-size:12px;line-height:1.6;color:#5b6472}.task{margin:12px 0;padding:12px;border:1px solid #cfd8e3;border-radius:8px;background:#f8fafc}
    .task.done{border-color:#20a36a;background:#effbf6}.task-name{font-weight:700;margin-bottom:6px}.badge{display:inline-block;padding:2px 7px;border-radius:10px;background:#e6eef8;font-size:11px}
    label{display:block;font-size:12px;margin-top:10px;color:#475569}input,textarea{width:100%;padding:7px;border:1px solid #cbd5e1;border-radius:5px;margin-top:4px}
    button{border:0;border-radius:6px;padding:8px 10px;cursor:pointer;background:#1769aa;color:white;margin:5px 4px 0 0}.secondary{background:#64748b}.danger{background:#b42318}
    #map{height:100vh}.constraint{border-top:1px solid #e2e8f0;margin-top:14px;padding-top:12px}.row{display:flex;gap:8px}.row>*{flex:1}
    .crosshair{position:absolute;left:50%;top:50%;z-index:3;transform:translate(-50%,-50%);pointer-events:none;font-size:24px;color:#d22630;text-shadow:0 0 3px white}
    @media(max-width:800px){#app{grid-template-columns:1fr;grid-template-rows:46vh 54vh}.panel{border-right:0;border-bottom:1px solid #ddd}#map{height:54vh}}
  </style>
</head>
<body><div id="app"><section class="panel">
  <h1>阶段2.5：空间位置确认</h1>
  <div class="hint">选择任务后在地图上点击。坐标不会自动推测；每个结果必须填写确认人。绿色表示已点击，可重复点击修正。</div>
  <label>确认人<input id="confirmedBy" placeholder="例如：规划人员张三" /></label>
  <div id="taskBox"></div>
  <div><button id="prevBtn" class="secondary">上一个</button><button id="nextBtn" class="secondary">下一个</button><button id="clearBtn" class="danger">清除当前点</button></div>
  <div class="constraint"><h1>约束参数确认</h1><div class="hint">缓冲距离必须依据主管部门要求或项目技术标准填写，并说明依据。</div><div id="constraintBox"></div></div>
  <div class="constraint"><button id="downloadGeo">导出位置确认 GeoJSON</button><button id="downloadParams">导出约束参数 JSON</button></div>
</section><main style="position:relative"><div id="map"></div><div class="crosshair">＋</div></main></div>
<script src="__JS_URL__"></script>
<script>
const tasks=__TASKS__; const constraintTasks=__CONSTRAINTS__; const boundary=__BOUNDARY__; const roads=__ROADS__;
const storageKey='__STORAGE_KEY__'; let currentIndex=0;
let saved={features:[],parameters:{},confirmedBy:''}; try{saved={...saved,...JSON.parse(localStorage.getItem(storageKey)||'{}')}}catch(e){}
const confirmedBy=document.getElementById('confirmedBy'); confirmedBy.value=saved.confirmedBy||'';
confirmedBy.addEventListener('input',()=>{saved.confirmedBy=confirmedBy.value.trim();persist()});
function persist(){localStorage.setItem(storageKey,JSON.stringify(saved))}
function currentTask(){return tasks[currentIndex]}
function taskFeature(taskId){return saved.features.find(f=>f.properties.task_id===taskId)}
function renderTask(){const t=currentTask();const done=!!taskFeature(t.task_id);document.getElementById('taskBox').innerHTML=`<div class="task ${done?'done':''}"><span class="badge">${currentIndex+1}/${tasks.length} · ${t.task_type}</span><div class="task-name">${t.display_name}</div><div class="hint">${t.instruction}</div>${(t.suggested_aliases||[]).length?`<div class="hint">可能的名称核对项：${t.suggested_aliases.join('、')}（仅提示，不会自动合并）</div>`:''}</div>`}
function renderConstraints(){const box=document.getElementById('constraintBox');box.innerHTML=constraintTasks.map(t=>{const v=saved.parameters[t.constraint_id]||{};return `<div class="task"><div class="task-name">${t.constraint_id} ${t.description}</div><label>缓冲距离（米）<input type="number" min="0" step="1" data-field="value" data-id="${t.constraint_id}" value="${v.value??''}"></label><label>依据<textarea data-field="basis" data-id="${t.constraint_id}" placeholder="法规、主管部门意见或技术标准">${v.basis||''}</textarea></label></div>`}).join('');box.querySelectorAll('[data-id]').forEach(el=>el.addEventListener('input',()=>{const id=el.dataset.id;saved.parameters[id]=saved.parameters[id]||{};saved.parameters[id][el.dataset.field]=el.dataset.field==='value'?(el.value===''?null:Number(el.value)):el.value;saved.parameters[id].confirmed_by=confirmedBy.value.trim();saved.parameters[id].confirmed_at=new Date().toISOString();persist()}))}
const map=new maplibregl.Map({container:'map',style:{version:8,sources:{},layers:[{id:'bg',type:'background',paint:{'background-color':'#edf3ee'}}]},center:[116.05,24.83],zoom:12});
map.addControl(new maplibregl.NavigationControl(),'top-left');
map.on('load',()=>{map.addSource('boundary',{type:'geojson',data:boundary});map.addLayer({id:'boundary-fill',type:'fill',source:'boundary',paint:{'fill-color':'#88c999','fill-opacity':0.12}});map.addLayer({id:'boundary-line',type:'line',source:'boundary',paint:{'line-color':'#277a45','line-width':2}});map.addSource('roads',{type:'geojson',data:roads});map.addLayer({id:'roads',type:'line',source:'roads',paint:{'line-color':'#667085','line-width':1.8}});map.addSource('confirmed',{type:'geojson',data:{type:'FeatureCollection',features:saved.features}});map.addLayer({id:'confirmed',type:'circle',source:'confirmed',paint:{'circle-radius':7,'circle-color':'#d22630','circle-stroke-color':'#fff','circle-stroke-width':2}});const bounds=new maplibregl.LngLatBounds();(boundary.features||[]).forEach(f=>walk(f.geometry?.coordinates,bounds));if(!bounds.isEmpty())map.fitBounds(bounds,{padding:35,duration:0})});
function walk(coords,bounds){if(!Array.isArray(coords))return;if(typeof coords[0]==='number'){bounds.extend(coords);return}coords.forEach(c=>walk(c,bounds))}
map.on('click',e=>{const t=currentTask();const who=confirmedBy.value.trim();if(!who){alert('请先填写确认人');return}const props={task_id:t.task_id,confirmation_type:t.task_type,confirmation_status:'confirmed',confirmed_by:who,confirmed_at:new Date().toISOString(),source_method:'manual_map_click'};if(t.task_type==='place')props.name=t.place_name;else{props.project_id=t.project_id;props.endpoint_role=t.endpoint_role;props.name=t.display_name}const feature={type:'Feature',geometry:{type:'Point',coordinates:[e.lngLat.lng,e.lngLat.lat]},properties:props};saved.features=saved.features.filter(f=>f.properties.task_id!==t.task_id);saved.features.push(feature);persist();map.getSource('confirmed')?.setData({type:'FeatureCollection',features:saved.features});renderTask()});
document.getElementById('prevBtn').onclick=()=>{currentIndex=(currentIndex-1+tasks.length)%tasks.length;renderTask()};document.getElementById('nextBtn').onclick=()=>{currentIndex=(currentIndex+1)%tasks.length;renderTask()};document.getElementById('clearBtn').onclick=()=>{const id=currentTask().task_id;saved.features=saved.features.filter(f=>f.properties.task_id!==id);persist();map.getSource('confirmed')?.setData({type:'FeatureCollection',features:saved.features});renderTask()};
function download(name,payload){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));a.download=name;a.click();URL.revokeObjectURL(a.href)}
document.getElementById('downloadGeo').onclick=()=>download('location_confirmations.geojson',{type:'FeatureCollection',name:'location_confirmations',crs:{type:'name',properties:{name:'EPSG:4326'}},features:saved.features});
document.getElementById('downloadParams').onclick=()=>download('constraint_parameters.json',{type:'ConstraintParameterConfirmation',schema_version:'1.0',parameters:constraintTasks.map(t=>({...t,...(saved.parameters[t.constraint_id]||{}),status:saved.parameters[t.constraint_id]?.value!=null?'confirmed':'pending'}))});
renderTask();renderConstraints();
</script></body></html>'''
    replacements = {
        "__CSS_URL__": css_url,
        "__JS_URL__": js_url,
        "__TASKS__": _safe_script_json(tasks),
        "__CONSTRAINTS__": _safe_script_json(constraint_tasks),
        "__BOUNDARY__": _safe_script_json(boundary),
        "__ROADS__": _safe_script_json(roads),
        "__STORAGE_KEY__": storage_key,
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def generate_location_confirmation_workflow(
    config: LocationConfirmationConfig,
) -> LocationConfirmationResult:
    """Create tasks, empty templates, and the standalone click-confirmation map."""

    config.validate()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    demands = _read_json(config.stage2_dir / "demand_points.geojson")
    projects = _read_json(config.stage2_dir / "road_projects.json")
    constraints = _read_json(config.stage2_dir / "road_constraints.json")
    tasks, official_places = _task_sources(demands, projects)
    constraint_tasks = _constraint_tasks(constraints)
    task_payload = {
        "type": "LocationConfirmationTaskCollection",
        "schema_version": SCHEMA_VERSION,
        "task_fingerprint": _fingerprint(tasks),
        "official_places": official_places,
        "tasks": tasks,
    }
    confirmation_template = {
        "type": "FeatureCollection",
        "name": "location_confirmations",
        "crs": {"type": "name", "properties": {"name": config.display_crs}},
        "features": [],
    }
    constraint_payload = {
        "type": "ConstraintParameterConfirmation",
        "schema_version": SCHEMA_VERSION,
        "parameters": constraint_tasks,
    }
    tasks_path = config.output_dir / "location_confirmation_tasks.json"
    confirmation_path = config.output_dir / "location_confirmations_template.geojson"
    constraint_path = config.output_dir / "constraint_parameters_template.json"
    map_path = config.output_dir / "location_confirmation_map.html"
    report_path = config.output_dir / "stage2_5_report.json"
    _write_json(tasks_path, task_payload)
    _write_json(confirmation_path, confirmation_template)
    _write_json(constraint_path, constraint_payload)
    js_url, css_url, asset_mode = _copy_maplibre_assets(config)
    map_path.write_text(
        _map_html(
            tasks=tasks,
            constraint_tasks=constraint_tasks,
            boundary=_read_json(config.boundary_path),
            roads=_read_json(config.current_road_path),
            js_url=js_url,
            css_url=css_url,
            storage_key=f"road-stage25-{_fingerprint(tasks)[:12]}",
        ),
        encoding="utf-8",
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "awaiting_manual_confirmation",
        "place_task_count": sum(task["task_type"] == "place" for task in tasks),
        "road_endpoint_task_count": sum(task["task_type"] == "road_endpoint" for task in tasks),
        "constraint_parameter_task_count": len(constraint_tasks),
        "confirmed_location_count": 0,
        "pending_location_count": len(tasks),
        "pending_constraint_parameter_count": len(constraint_tasks),
        "map_asset_mode": asset_mode,
        "planned_geometry_read": False,
        "next_action": "Open location_confirmation_map.html, click every required point, fill buffers, and export both confirmation files.",
    }
    _write_json(report_path, report)
    return LocationConfirmationResult(
        output_dir=config.output_dir,
        tasks_path=tasks_path,
        map_path=map_path,
        confirmation_template_path=confirmation_path,
        constraint_template_path=constraint_path,
        report_path=report_path,
        report=report,
    )


def _validate_point(coordinates: Any) -> List[float]:
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise ValueError("confirmation geometry must contain [longitude, latitude]")
    longitude, latitude = coordinates[:2]
    if not isinstance(longitude, (int, float)) or not isinstance(latitude, (int, float)):
        raise ValueError("confirmation coordinates must be numeric")
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise ValueError("confirmation coordinates must be finite")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError("confirmation coordinates are outside EPSG:4326 bounds")
    return [float(longitude), float(latitude)]


def _validated_confirmations(
    payload: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    task_index = {task["task_id"]: task for task in tasks}
    seen: set[str] = set()
    validated: List[Dict[str, Any]] = []
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        task_id = properties.get("task_id")
        if task_id not in task_index:
            raise ValueError(f"unknown or stale confirmation task_id: {task_id}")
        if task_id in seen:
            raise ValueError(f"duplicate confirmation for task_id: {task_id}")
        seen.add(task_id)
        if properties.get("confirmation_status") != "confirmed":
            raise ValueError(f"confirmation {task_id} is not marked confirmed")
        if not str(properties.get("confirmed_by") or "").strip():
            raise ValueError(f"confirmation {task_id} is missing confirmed_by")
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            raise ValueError(f"confirmation {task_id} must use Point geometry")
        coordinates = _validate_point(geometry.get("coordinates"))
        validated.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coordinates},
                "properties": copy.deepcopy(properties),
            }
        )
    return validated


def _validated_parameters(
    payload: Optional[Mapping[str, Any]], constraint_tasks: Sequence[Mapping[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    if payload is None:
        return {}
    expected = {task["constraint_id"] for task in constraint_tasks}
    output: Dict[str, Dict[str, Any]] = {}
    for item in payload.get("parameters", []):
        constraint_id = item.get("constraint_id")
        if constraint_id not in expected:
            raise ValueError(f"unknown constraint parameter target: {constraint_id}")
        if item.get("status") != "confirmed":
            continue
        value = item.get("value")
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"constraint {constraint_id} buffer_m must be a non-negative number")
        if not str(item.get("confirmed_by") or "").strip():
            raise ValueError(f"constraint {constraint_id} is missing confirmed_by")
        if not str(item.get("basis") or "").strip():
            raise ValueError(f"constraint {constraint_id} is missing its legal/technical basis")
        output[str(constraint_id)] = copy.deepcopy(item)
    return output


def apply_location_confirmations(
    config: LocationConfirmationConfig,
    confirmation_path: Path,
    constraint_parameters_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate human confirmations and produce Stage-3-ready resolved outputs."""

    config.validate()
    task_result = generate_location_confirmation_workflow(config)
    task_payload = _read_json(task_result.tasks_path)
    tasks = task_payload["tasks"]
    constraint_template = _read_json(task_result.constraint_template_path)
    confirmations = _validated_confirmations(_read_json(confirmation_path), tasks)
    parameter_payload = _read_json(constraint_parameters_path) if constraint_parameters_path else None
    parameters = _validated_parameters(parameter_payload, constraint_template["parameters"])

    demands = _read_json(config.stage2_dir / "demand_points.geojson")
    projects = _read_json(config.stage2_dir / "road_projects.json")
    constraints = _read_json(config.stage2_dir / "road_constraints.json")
    task_index = {task["task_id"]: task for task in tasks}
    place_confirmations: Dict[str, Dict[str, Any]] = {}
    endpoint_confirmations: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for feature in confirmations:
        task = task_index[feature["properties"]["task_id"]]
        if task["task_type"] == "place":
            place_confirmations[_norm(task["place_name"])] = feature
        else:
            endpoint_confirmations[(task["project_id"], task["endpoint_role"])] = feature

    for feature in demands.get("features", []):
        properties = feature.get("properties") or {}
        confirmation = place_confirmations.get(_norm(properties.get("place_name")))
        if confirmation is None:
            continue
        feature["geometry"] = copy.deepcopy(confirmation["geometry"])
        properties["location_status"] = "matched"
        properties["location_confidence"] = 1.0
        properties["location_reason"] = "confirmed by manual map click in Stage 2.5"
        properties["location_match"] = {
            "source": "stage2_5_manual_confirmation",
            "task_id": confirmation["properties"]["task_id"],
            "confirmed_by": confirmation["properties"]["confirmed_by"],
            "confirmed_at": confirmation["properties"].get("confirmed_at"),
        }
        properties["requires_human_confirmation"] = False

    for constraint in constraints.get("constraints", []):
        parameter = parameters.get(constraint.get("constraint_id"))
        if parameter is None:
            continue
        constraint["buffer_m"] = float(parameter["value"])
        constraint["requires_human_confirmation"] = False
        constraint["parameter_confirmation"] = parameter

    pending_constraint_ids = [
        constraint.get("constraint_id")
        for constraint in constraints.get("constraints", [])
        if constraint.get("requires_human_confirmation")
    ]
    for project in projects.get("projects", []):
        project_id = project.get("project_id")
        for role in ("start", "end"):
            confirmation = endpoint_confirmations.get((project_id, role))
            if confirmation is None:
                confirmation = place_confirmations.get(_norm(project.get(f"{role}_place")))
            if confirmation is None:
                continue
            project[f"{role}_geometry"] = copy.deepcopy(confirmation["geometry"])
            project[f"{role}_location_status"] = "matched"
            if not project.get(f"{role}_place"):
                project[f"{role}_place"] = confirmation["properties"].get("name")
            project[f"{role}_location_confirmation"] = copy.deepcopy(confirmation["properties"])
        location_ready = all(
            project.get(f"{role}_location_status") == "matched"
            and (project.get(f"{role}_geometry") or {}).get("type") == "Point"
            for role in ("start", "end")
        )
        if not location_ready:
            project["planning_status"] = "blocked_needs_location_confirmation"
        elif pending_constraint_ids:
            project["planning_status"] = "blocked_missing_constraint_parameters"
        else:
            project["planning_status"] = "ready"
        project["requires_human_confirmation"] = project["planning_status"] != "ready"

    resolved_dir = config.output_dir / "resolved"
    resolved_dir.mkdir(parents=True, exist_ok=True)
    _write_json(resolved_dir / "demand_points.geojson", demands)
    _write_json(resolved_dir / "road_projects.json", projects)
    _write_json(resolved_dir / "road_constraints.json", constraints)
    confirmed_location_features = []
    for feature in confirmations:
        task = task_index[feature["properties"]["task_id"]]
        if task["task_type"] != "place":
            continue
        confirmed_location_features.append(
            {
                "type": "Feature",
                "geometry": copy.deepcopy(feature["geometry"]),
                "properties": {
                    "name": task["place_name"],
                    **copy.deepcopy(feature["properties"]),
                },
            }
        )
    _write_json(
        resolved_dir / "confirmed_locations.geojson",
        {
            "type": "FeatureCollection",
            "name": "confirmed_locations",
            "crs": {"type": "name", "properties": {"name": config.display_crs}},
            "features": confirmed_location_features,
        },
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "ready_for_stage3"
        if all(project.get("planning_status") == "ready" for project in projects.get("projects", []))
        else "manual_confirmation_incomplete",
        "confirmed_location_task_count": len(confirmations),
        "pending_location_task_count": len(tasks) - len(confirmations),
        "confirmed_constraint_parameter_count": len(parameters),
        "pending_constraint_parameter_count": len(pending_constraint_ids),
        "matched_demand_count": sum(
            feature.get("properties", {}).get("location_status") == "matched"
            for feature in demands.get("features", [])
        ),
        "ready_project_count": sum(
            project.get("planning_status") == "ready" for project in projects.get("projects", [])
        ),
        "blocked_project_count": sum(
            project.get("planning_status") != "ready" for project in projects.get("projects", [])
        ),
        "pending_constraint_ids": pending_constraint_ids,
        "planned_geometry_read": False,
        "resolved_output_dir": resolved_dir.as_posix(),
    }
    _write_json(resolved_dir / "stage2_5_report.json", report)
    return report


__all__ = [
    "apply_location_confirmations",
    "generate_location_confirmation_workflow",
]
