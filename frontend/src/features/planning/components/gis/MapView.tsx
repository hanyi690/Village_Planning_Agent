'use client';

/**
 * MapView - MapLibre GL 地图容器组件
 *
 * 用于渲染 GIS 分析结果，支持 GeoJSON 图层、矢量瓦片等。
 * 使用 GeoJSON 标准坐标格式 [longitude, latitude]（经度在前）。
 * 支持要素点击事件和 Popup 属性显示。
 */

import { useEffect, useState, useMemo, useRef, useCallback } from 'react';
import Map, { Source, Layer, Marker, Popup, NavigationControl, ScaleControl } from 'react-map-gl/maplibre';
import type { FillLayerSpecification, FillExtrusionLayerSpecification, LineLayerSpecification, CircleLayerSpecification, StyleSpecification, ExpressionSpecification, Map as MaplibreMap } from 'maplibre-gl';
import type { MapRef, MapLayerMouseEvent } from 'react-map-gl/maplibre';
import type { FeatureCollection, Geometry, Position, Feature, GeoJsonProperties } from 'geojson';
import { faCube, faMap, faCrosshairs, faHighlighter } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import type { GISLayerConfig, GeoJsonFeatureCollection } from '@/types/message/message-types';
import { PLANNING_COLORS, DEFAULT_COLORS, TILE_SOURCES, BASE_MAP_TYPES, normalizeTileSource, BaseMapType, LineColors, FeatureColors, LayerType, LAYER_TYPE_LABELS, LAYER_CATEGORY_FIELDS, isStyleDrivenLayer } from '@/features/planning/constants/gis';
import { normalizeGisLayers } from '@/features/planning/utils/gis-normalize';
import { transformGeoJsonToGcj02, wgs84ToGcj02 } from '@/features/planning/utils/coord-transform';
import {
  getRoadActionLabel,
  getRoadLineColor,
  getRoadLabelText,
} from '@/features/planning/utils/road-map-style';
import LegendPanel from './LegendPanel';

const VIEW_MODE_CAMERA = {
  '2d': { pitch: 0, bearing: 0 },
  '3d': { pitch: 50, bearing: 0 },
} as const;

const MAP_ZOOM_RATE = 1 / 320;
const MAP_EASE_MS = 900;
const MAP_ROTATE_DEGREES_PER_PIXEL = 0.42;
const MAP_PITCH_DEGREES_PER_PIXEL = -0.32;

const MAP_INTERACTION_OPTIONS = {
  rotateDegreesPerPixelMoved: MAP_ROTATE_DEGREES_PER_PIXEL,
  pitchDegreesPerPixelMoved: MAP_PITCH_DEGREES_PER_PIXEL,
};

function easeOutCubic(t: number): number {
  return 1 - (1 - t) ** 3;
}

function getCameraForViewMode(mode: '2d' | '3d') {
  return VIEW_MODE_CAMERA[mode];
}

function applyMapRotateMode(map: MaplibreMap, mode: '2d' | '3d') {
  map.dragRotate.disable();
  map.touchZoomRotate.enableRotation();
  if (mode === '2d') {
    map.setMinPitch(0);
    map.setMaxPitch(0);
    if (map.getPitch() !== 0) map.setPitch(0);
    map.touchPitch.disable();
    return;
  }
  map.setMinPitch(0);
  map.setMaxPitch(55);
  map.touchPitch.enable({ around: 'center' });
}

function configureMapInteractions(
  map: MaplibreMap,
  container: HTMLElement,
  onInteractionChange: (active: boolean) => void,
  viewMode: '2d' | '3d',
  getViewMode: () => '2d' | '3d',
) {
  map.scrollZoom.setZoomRate(MAP_ZOOM_RATE);
  map.scrollZoom.setWheelZoomRate(MAP_ZOOM_RATE);
  map.scrollZoom.enable({ around: 'center' });
  map.touchZoomRotate.enable({ around: 'center' });
  applyMapRotateMode(map, viewMode);
  // MapLibre dragRotate is bypassed — pointerdown preventDefault breaks its mousedown chain.
  map.dragRotate.disable();

  let interactionEndTimer: number | null = null;
  const markInteracting = () => {
    onInteractionChange(true);
    if (interactionEndTimer !== null) window.clearTimeout(interactionEndTimer);
  };
  const scheduleInteractionEnd = () => {
    if (interactionEndTimer !== null) window.clearTimeout(interactionEndTimer);
    interactionEndTimer = window.setTimeout(() => onInteractionChange(false), 140);
  };

  const interactionEvents = ['wheel', 'dragstart', 'rotatestart', 'pitchstart', 'zoomstart'] as const;
  const settleEvents = ['moveend', 'zoomend', 'rotateend', 'pitchend', 'dragend'] as const;
  interactionEvents.forEach((eventName) => map.on(eventName, markInteracting));
  settleEvents.forEach((eventName) => map.on(eventName, scheduleInteractionEnd));

  const blockPageScrollOnWheel = (event: WheelEvent) => {
    event.preventDefault();
  };
  container.addEventListener('wheel', blockPageScrollOnWheel, { passive: false });

  const preventContextMenu = (event: MouseEvent) => {
    event.preventDefault();
  };
  container.addEventListener('contextmenu', preventContextMenu);

  const canvas = map.getCanvas();
  canvas.addEventListener('contextmenu', preventContextMenu);

  let rotating = false;
  let startX = 0;
  let startY = 0;
  let startBearing = 0;
  let startPitch = 0;

  const onRotateMouseDown = (event: MouseEvent) => {
    if (event.button !== 2) return;
    event.preventDefault();
    rotating = true;
    startX = event.clientX;
    startY = event.clientY;
    startBearing = map.getBearing();
    startPitch = map.getPitch();
    markInteracting();
  };

  const onRotateMouseMove = (event: MouseEvent) => {
    if (!rotating) return;
    if ((event.buttons & 2) === 0) {
      rotating = false;
      scheduleInteractionEnd();
      return;
    }
    const dx = event.clientX - startX;
    const dy = event.clientY - startY;
    map.setBearing(startBearing + dx * MAP_ROTATE_DEGREES_PER_PIXEL);
    if (getViewMode() === '3d') {
      map.setPitch(Math.min(55, Math.max(0, startPitch + dy * MAP_PITCH_DEGREES_PER_PIXEL)));
    }
    event.preventDefault();
  };

  const onRotateMouseUp = (event: MouseEvent) => {
    if (!rotating || event.button !== 2) return;
    rotating = false;
    scheduleInteractionEnd();
  };

  container.addEventListener('mousedown', onRotateMouseDown, true);
  window.addEventListener('mousemove', onRotateMouseMove);
  window.addEventListener('mouseup', onRotateMouseUp);

  return () => {
    interactionEvents.forEach((eventName) => map.off(eventName, markInteracting));
    settleEvents.forEach((eventName) => map.off(eventName, scheduleInteractionEnd));
    container.removeEventListener('wheel', blockPageScrollOnWheel);
    container.removeEventListener('contextmenu', preventContextMenu);
    canvas.removeEventListener('contextmenu', preventContextMenu);
    container.removeEventListener('mousedown', onRotateMouseDown, true);
    window.removeEventListener('mousemove', onRotateMouseMove);
    window.removeEventListener('mouseup', onRotateMouseUp);
    if (interactionEndTimer !== null) window.clearTimeout(interactionEndTimer);
    onInteractionChange(false);
  };
}

// Feature Popup Content Component
function FeaturePopupContent({
  feature,
  layerName,
  layerType,
  hover = false,
}: {
  feature: Feature<Geometry, GeoJsonProperties>;
  layerName: string;
  layerType: string;
  hover?: boolean;
}) {
  const properties = feature.properties || {};
  const featureTitle = getFeatureDisplayName(feature, layerType);
  const kind = getFeatureKindBadge(layerType, feature);
  const hiddenKeys = new Set([
    '注记', 'text', 'annotation_symbol', 'project_name', 'facility_name', 'route_name',
    'label', 'name', 'Shape_Length', 'Shape_Area',
  ]);
  if (featureTitle && (properties.BSM === featureTitle || properties.bsm === featureTitle)) {
    hiddenKeys.add('BSM');
    hiddenKeys.add('bsm');
  }
  const propertyLabels: Record<string, string> = {
    BSM: '地块编号',
    TBH: '图斑号',
    XZQHMC: '行政村',
    DLBM: '现状用途代码',
    GHYTBM: '规划用途代码',
    GHYTMC: '规划用途',
    DLMJ: '地块面积',
    facility_type: '设施类型',
    category: '设施类别',
    status: '规划状态',
    construction_action: '建设方式',
    action_label: '道路类型',
    route_name: '道路名称',
    segment_id: '路段编号',
    planned_width_m: '规划宽度（米）',
    selection_status: '推荐状态',
    length_m: '长度（米）',
    data_authority: '数据属性',
  };

  const displayValue = (key: string, value: unknown): string => {
    if (key === 'DLMJ' && Number.isFinite(Number(value))) {
      return `${(Number(value) / 10000).toFixed(2)} ha`;
    }
    if (key === 'length_m' && Number.isFinite(Number(value))) {
      return `${Number(value).toFixed(1)} m`;
    }
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  };

  // Raw one-character annotation symbols are source-data internals. The map
  // popup presents the normalized full facility/project name instead.
  const priorityKeys = ['BSM', 'TBH', 'XZQHMC', 'DLBM', 'GHYTBM', 'GHYTMC', 'DLMJ'];
  const displayProps = Object.entries(properties)
    .filter(([key]) => !key.startsWith('_') && !hiddenKeys.has(key))
    .sort(([left], [right]) => {
      const leftPriority = priorityKeys.indexOf(left);
      const rightPriority = priorityKeys.indexOf(right);
      return (leftPriority < 0 ? 999 : leftPriority) - (rightPriority < 0 ? 999 : rightPriority);
    })
    .slice(0, 12);

  return (
    <div className={`max-w-[300px] p-3 ${hover ? 'min-w-[230px] rounded-xl bg-[#26323b] text-white shadow-xl' : ''}`}>
      <div className={`mb-2 border-b pb-2 ${hover ? 'border-white/15' : 'border-emerald-100'}`}>
        <div className="flex flex-wrap items-center gap-1.5">
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-semibold text-white"
            style={{ backgroundColor: kind.tone }}
          >
            {kind.label}
          </span>
          <span className={`text-[10px] font-medium ${hover ? 'text-[#49c49a]' : 'text-emerald-700'}`}>
            {LAYER_TYPE_LABELS[layerType as LayerType] || layerType}
          </span>
        </div>
        <div className={`mt-1.5 break-words text-sm font-semibold leading-5 ${hover ? 'text-white' : 'text-gray-800'}`}>{featureTitle || layerName}</div>
        {featureTitle && featureTitle !== layerName && (
          <div className={`mt-0.5 break-words text-[10px] ${hover ? 'text-slate-300' : 'text-gray-400'}`}>{layerName}</div>
        )}
      </div>
      <div className="space-y-1 text-xs">
        {displayProps.length > 0 ? (
          displayProps.map(([key, value]) => (
            <div key={key} className="flex justify-between gap-2">
                <span className={`shrink-0 ${hover ? 'text-[#50c9a0]' : 'text-gray-500'}`}>{propertyLabels[key] || key}:</span>
                <span className={`min-w-0 break-words text-right font-medium ${hover ? 'text-slate-100' : 'text-gray-700'}`}>
                  {displayValue(key, value)}
                </span>
            </div>
          ))
        ) : (
          <div className="text-gray-400">无属性数据</div>
        )}
      </div>
    </div>
  );
}

// Helper: Extract all coordinates from a geometry recursively
function extractCoords(geometry: { type: string; coordinates: unknown }): Position[] {
  const coords: Position[] = [];
  const coordsData = geometry.coordinates;
  if (geometry.type === 'Point') {
    coords.push(coordsData as Position);
  } else if (geometry.type === 'LineString' || geometry.type === 'MultiPoint') {
    coords.push(...(coordsData as Position[]));
  } else if (geometry.type === 'Polygon' || geometry.type === 'MultiLineString') {
    for (const ring of coordsData as Position[][]) {
      coords.push(...ring);
    }
  } else if (geometry.type === 'MultiPolygon') {
    for (const polygon of coordsData as Position[][][]) {
      for (const ring of polygon) {
        coords.push(...ring);
      }
    }
  }
  return coords;
}

// Helper: Calculate bounds from GeoJSON
function getBoundsFromGeoJSON(geojson: GeoJsonFeatureCollection): [[number, number], [number, number]] | null {
  if (!geojson.features || geojson.features.length === 0) return null;

  let minLon = Infinity, maxLon = -Infinity;
  let minLat = Infinity, maxLat = -Infinity;

  for (const feature of geojson.features) {
    const coords = extractCoords(feature.geometry);
    for (const coord of coords) {
      const [lon, lat] = coord;
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  }

  if (minLon === Infinity) return null;   
  return [[minLon, minLat], [maxLon, maxLat]];
}

function buildRoadDashExpression(): ExpressionSpecification {
  return [
    'match',
    ['coalesce', ['get', 'construction_action'], ['get', 'road_action'], 'planned'],
    'reuse_existing', ['literal', [2, 2]],
    'repair', ['literal', [3, 1.5]],
    'harden', ['literal', [6, 3, 2, 3]],
    'widen', ['literal', [5, 2]],
    ['literal', [1, 0]],
  ] as ExpressionSpecification;
}

function getGeometryAnchor(geometry: { type: string; coordinates: unknown }): [number, number] | null {
  if (geometry.type === 'Point') {
    const point = geometry.coordinates as number[];
    return point.length >= 2 ? [point[0], point[1]] : null;
  }
  const coordinates = extractCoords(geometry);
  if (coordinates.length === 0) return null;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const coordinate of coordinates) {
    minX = Math.min(minX, coordinate[0]);
    minY = Math.min(minY, coordinate[1]);
    maxX = Math.max(maxX, coordinate[0]);
    maxY = Math.max(maxY, coordinate[1]);
  }
  return Number.isFinite(minX) ? [(minX + maxX) / 2, (minY + maxY) / 2] : null;
}

function getTileApiBase(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '');
  if (configured) return configured;
  if (typeof window !== 'undefined') {
    const { protocol, hostname, origin } = window.location;
    // Local dev: hit FastAPI directly — more reliable than the Next rewrite for .png tiles.
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
      return `${protocol}//${hostname}:8000`;
    }
    return origin;
  }
  return 'http://127.0.0.1:8000';
}

// Tile URLs - vec_w: Vector map (planning法定底图), cva_w: Vector annotation
const getTiandituUrls = (baseMapType: BaseMapType) => {
  const apiBase = getTileApiBase();
  const config = BASE_MAP_TYPES[baseMapType];
  return {
    baseUrl: `${apiBase}/api/tiles/tianditu/${config.tile}_w/{z}/{y}/{x}`,
    annotationUrl: `${apiBase}/api/tiles/tianditu/${config.annotation}_w/{z}/{y}/{x}`,
  };
};
function getAmapTileUrls(): string[] {
  const direct = [1, 2, 3, 4].map(
    (server) => `https://webrd0${server}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={x}&y={y}&z={z}`,
  );
  const apiBase = getTileApiBase();
  const proxied = [1, 2, 3, 4].map(
    (server) => `${apiBase}/api/tiles/amap/{z}/{x}/{y}.png?s=${server}`,
  );
  return [...direct, ...proxied];
}
function getGeoqTileUrl(): string {
  return `${getTileApiBase()}/api/tiles/geoq/{z}/{y}/{x}`;
}
function getOsmTileUrl(): string {
  return `${getTileApiBase()}/api/tiles/osm/{z}/{x}/{y}.png`;
}

function buildRasterTileSource(tileUrls: string | string[], attribution: string, maxzoom = 19) {
  return {
    type: 'raster' as const,
    tiles: Array.isArray(tileUrls) ? tileUrls : [tileUrls],
    tileSize: 256,
    minzoom: 0,
    maxzoom,
    scheme: 'xyz' as const,
    attribution,
  };
}

const RASTER_LAYER_PAINT = {
  'raster-opacity': 1,
  'raster-fade-duration': 0,
} as const;

function expandBoundsForFit(
  minLon: number,
  minLat: number,
  maxLon: number,
  maxLat: number,
  ratio = 0.25,
): [[number, number], [number, number]] {
  const lonPad = Math.max((maxLon - minLon) * ratio, 0.01);
  const latPad = Math.max((maxLat - minLat) * ratio, 0.01);
  return [
    [minLon - lonPad, minLat - latPad],
    [maxLon + lonPad, maxLat + latPad],
  ];
}

const DEFAULT_CENTER: [number, number] = [116.0735, 24.8317];

function featureBBoxArea(feature: Feature<Geometry, GeoJsonProperties>): number {
  const bounds = getBoundsFromGeoJSON({
    type: 'FeatureCollection',
    features: [feature as GeoJsonFeatureCollection['features'][number]],
  });
  if (!bounds) return Number.POSITIVE_INFINITY;
  const width = Math.abs(bounds[1][0] - bounds[0][0]);
  const height = Math.abs(bounds[1][1] - bounds[0][1]);
  return width * height;
}

function featureIdentity(feature: Feature<Geometry, GeoJsonProperties>): string {
  const properties = feature.properties || {};
  return String(
    feature.id
    ?? properties.BSM
    ?? properties.TBH
    ?? properties.GHYTMC
    ?? properties.objectid
    ?? properties.OBJECTID
    ?? properties.FID
    ?? JSON.stringify(feature.geometry),
  );
}

function isParcelLikeFeature(feature: Feature<Geometry, GeoJsonProperties>): boolean {
  const properties = feature.properties || {};
  return Boolean(
    properties.BSM || properties.TBH || properties.GHYTMC || properties.DLBM
    || properties.GHYTBM || properties.zone_type || properties.constraint_type
    || properties.DLMJ || properties['规划用途'] || properties['用途']
  );
}

function getFeatureBsm(feature: Feature<Geometry, GeoJsonProperties>): string | null {
  const properties = feature.properties || {};
  const raw = properties.BSM ?? properties.bsm;
  if (raw === null || raw === undefined) return null;
  const text = String(raw).trim();
  return text.length > 0 ? text : null;
}

function layerDisplayRole(layer: GISLayerConfig): string {
  return String(layer.metadata?.displayRole ?? '');
}

function pickPrimaryParcelLayer(layers: GISLayerConfig[]): GISLayerConfig | null {
  const candidates = layers.filter((layer) => {
    if (layerDisplayRole(layer) === 'original_planning_reference') return false;
    if (/现状|原版|参考/.test(layer.layerName)) return false;
    if ((layer.geojson?.features?.length ?? 0) === 0) return false;
    if (layer.layerType === 'planning_zone') return true;
    return layer.layerName === 'landuse' && String(layer.metadata?.path ?? '').includes('/planned/');
  });
  if (candidates.length === 0) return null;
  const preferred = candidates.find((layer) => layer.layerName.includes('用途规划'));
  if (preferred) return preferred;
  return [...candidates].sort(
    (left, right) => (right.geojson?.features?.length ?? 0) - (left.geojson?.features?.length ?? 0),
  )[0];
}

function pointInRing(point: [number, number], ring: Position[]): boolean {
  const [x, y] = point;
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const intersects = ((yi > y) !== (yj > y))
      && (x < ((xj - xi) * (y - yi)) / ((yj - yi) || Number.EPSILON) + xi);
    if (intersects) inside = !inside;
  }
  return inside;
}

function pointInParcel(lng: number, lat: number, feature: Feature<Geometry, GeoJsonProperties>): boolean {
  const geometry = feature.geometry;
  if (geometry.type === 'Polygon') {
    const [outer, ...holes] = geometry.coordinates;
    if (!pointInRing([lng, lat], outer)) return false;
    return !holes.some((hole) => pointInRing([lng, lat], hole));
  }
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates.some((polygon) => {
      const [outer, ...holes] = polygon;
      if (!pointInRing([lng, lat], outer)) return false;
      return !holes.some((hole) => pointInRing([lng, lat], hole));
    });
  }
  return false;
}

function findParcelAtLngLat(
  lng: number,
  lat: number,
  layer: GISLayerConfig | null,
): Feature<Geometry, GeoJsonProperties> | null {
  if (!layer?.geojson?.features?.length) return null;

  const hits = layer.geojson.features.filter(
    (feature) => pointInParcel(lng, lat, feature as Feature<Geometry, GeoJsonProperties>),
  ) as Feature<Geometry, GeoJsonProperties>[];

  if (hits.length === 0) return null;
  return [...hits].sort((left, right) => featureBBoxArea(left) - featureBBoxArea(right))[0];
}

function getFeatureDisplayName(
  feature: Feature<Geometry, GeoJsonProperties>,
  layerType?: string,
): string {
  const properties = feature.properties || {};
  if (layerType === 'planned_road') {
    return getRoadLabelText(properties);
  }
  return String(
    properties.route_name
    ?? properties.project_name
    ?? properties.facility_name
    ?? properties.label
    ?? properties.name
    ?? properties.action_label
    ?? properties.BSM
    ?? properties.bsm
    ?? '',
  ).trim();
}

function getFeatureKindBadge(layerType: string, feature: Feature<Geometry, GeoJsonProperties>): {
  label: string;
  tone: string;
} {
  const properties = feature.properties || {};
  if (layerType === 'hazard_point') {
    return { label: '地质灾害点', tone: '#EA580C' };
  }
  if (layerType === 'facility_point') {
    const status = String(properties.status ?? '');
    if (status === '规划新建') return { label: '规划设施/项目', tone: '#DC2626' };
    if (status === '规划改扩建') return { label: '规划改扩建', tone: '#EA580C' };
    if (status === '规划迁建') return { label: '规划迁建', tone: '#9333EA' };
    return { label: '现状设施', tone: '#16A34A' };
  }
  if (layerType === 'planned_road') {
    const label = getRoadActionLabel(properties);
    return { label, tone: getRoadLineColor(properties) };
  }
  if (layerType === 'infrastructure') {
    const role = String(properties.display_role || '');
    if (role.includes('road') || String(properties.infra_type || '').includes('road')) {
      return { label: '道路廊道', tone: '#D97706' };
    }
    return { label: '道路要素', tone: '#2563EB' };
  }
  if (layerType === 'planning_zone' || layerType === 'function_zone' || layerType === 'final_landuse') {
    return { label: '地块', tone: '#0D9488' };
  }
  if (layerType === 'development_axis') {
    return { label: '发展轴', tone: '#7C3AED' };
  }
  return { label: LAYER_TYPE_LABELS[layerType as LayerType] || '空间要素', tone: '#64748B' };
}

function isVectorPickLayerId(layerId: string): boolean {
  return layerId.endsWith('-circle')
    || layerId.endsWith('-infra')
    || layerId.endsWith('-planned-road');
}

function pickVectorFeature(
  features: Feature<Geometry, GeoJsonProperties>[] | undefined,
): Feature<Geometry, GeoJsonProperties> | null {
  if (!features?.length) return null;

  const pointHits = features.filter((candidate) => {
    const layerId = String((candidate as Feature<Geometry, GeoJsonProperties> & { layer?: { id?: string } }).layer?.id || '');
    return candidate.geometry.type === 'Point' || layerId.endsWith('-circle');
  });
  if (pointHits.length > 0) {
    return pointHits[0] as Feature<Geometry, GeoJsonProperties>;
  }

  const lineHits = features.filter((candidate) => {
    const layerId = String((candidate as Feature<Geometry, GeoJsonProperties> & { layer?: { id?: string } }).layer?.id || '');
    return (candidate.geometry.type === 'LineString' || candidate.geometry.type === 'MultiLineString')
      && isVectorPickLayerId(layerId);
  });
  if (lineHits.length > 0) {
    return lineHits[0] as Feature<Geometry, GeoJsonProperties>;
  }

  return null;
}

function parseLayerNameFromMapLayerId(layerId: string): string | null {
  const match = layerId.match(/^layer-\d+-(.+)-(?:fill|line|circle|boundary|boundary-fill|infra|planned-road|road-casing|extrusion)$/);
  return match?.[1] ?? null;
}

interface MapViewProps {
  layers: GISLayerConfig[];
  center?: [number, number]; // [longitude, latitude] GeoJSON standard
  zoom?: number;
  height?: string;
  title?: string;
  baseMapType?: BaseMapType; // Default: 'vector' (planning法定底图)
  showLegend?: boolean; // Whether to show legend panel
  legendPosition?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
  visibleLayerTypes?: Set<LayerType>; // Optional: filter which layers to render
  frameless?: boolean; // Fill a parent tool surface without a second border
  compactLegend?: boolean; // Collapse the legend by default to preserve map space
  offlineBaseMap?: boolean; // Render local GeoJSON without depending on remote tiles
  maxMapLabels?: number; // Cap HTML callouts for dense planning maps
  hoverPopup?: boolean; // Enable parcel/vector pick mode; click for details
  defaultHoverHighlight?: boolean; // Initial hover highlight state when hoverPopup is on
  tileSourceOverride?: 'amap' | 'tianditu' | 'geoq' | 'openstreetmap' | 'osm' | 'offline';
  fitPadding?: number; // Extra context around the fitted village boundary
  autoFitOnLayerChange?: boolean; // Refit camera when visible layers change (default false)
}

// Layer rendering priority (numerical order, higher = top layer)
const LAYER_PRIORITY: Record<string, number> = {
  'sensitivity_zone': 1,
  'function_zone': 2,
  'final_landuse': 3,
  'land_use_zone': 4,
  'planning_zone': 5,
  'construction_control': 6,
  'isochrone': 7,
  'infrastructure': 90,
  'development_axis': 100,
  'planned_road': 105,
  'boundary': 110,
  'planning_scope': 111,
  'hazard_point': 119,
  'facility_point': 120,
};

// Helper: check if features have per-feature color
function hasFeatureColors(geojson: GeoJsonFeatureCollection | undefined): boolean {
  return !!geojson?.features?.some(f => (f.properties as Record<string, unknown>)?.color);
}

function styleNumber(layer: GISLayerConfig, key: string, fallback: number): number {
  const value = layer.style?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function styleColor(layer: GISLayerConfig, key: string, fallback: string): string {
  const value = layer.style?.[key];
  if (typeof value === 'string' && value.trim()) return value;
  if (key === 'lineColor' && typeof layer.color === 'string') return layer.color;
  if (key === 'fillColor' && typeof layer.color === 'string') return layer.color;
  return fallback;
}

function styleDasharray(layer: GISLayerConfig): number[] | undefined {
  const value = layer.style?.lineDasharray;
  if (!Array.isArray(value)) return undefined;
  const numbers = value.map(Number).filter((item) => Number.isFinite(item) && item > 0);
  return numbers.length >= 2 ? numbers : undefined;
}

// Build match expression from PLANNING_COLORS sub-map
function buildMatchExpression(
  property: string | readonly string[],
  colorMap: Record<string, Record<string, unknown>>,
  defaultValue: string | number,
  field: 'fill' | 'stroke' | 'width' = 'fill',
): ExpressionSpecification {
  const cases: (string | number)[] = [];
  for (const [key, colors] of Object.entries(colorMap)) {
    const value = colors[field];
    if (typeof value === 'string' || typeof value === 'number') cases.push(key, value);
  }
  const valueExpression = Array.isArray(property)
    ? ['coalesce', ...property.map((field) => ['get', field]), '']
    : ['get', property];
  return ['match', valueExpression, ...cases, defaultValue] as unknown as ExpressionSpecification;
}

export default function MapView({
  layers,
  center = DEFAULT_CENTER,
  zoom = 14,
  height = '400px',
  title,
  baseMapType = 'vector',
  showLegend = true,
  legendPosition = 'bottom-right',
  visibleLayerTypes,
  frameless = false,
  compactLegend = false,
  offlineBaseMap = false,
  maxMapLabels = 38,
  hoverPopup = false,
  defaultHoverHighlight = true,
  tileSourceOverride,
  fitPadding = 36,
  autoFitOnLayerChange = false,
}: MapViewProps) {
  const resolvedTileSource = normalizeTileSource(
    tileSourceOverride || process.env.NEXT_PUBLIC_TILE_SOURCE || TILE_SOURCES.AMAP,
  );
  const isOfflineBasemap = offlineBaseMap || tileSourceOverride === 'offline';
  const isAmapBasemap = !isOfflineBasemap && resolvedTileSource === TILE_SOURCES.AMAP;
  const displayCenter = useMemo((): [number, number] => {
    if (!isAmapBasemap) return center;
    return wgs84ToGcj02(center[0], center[1]);
  }, [center, isAmapBasemap]);
  // Normalize backend payloads before rendering. Some historical sessions use
  // data/layer_type/layer_name instead of geojson/layerType/layerName.
  const normalizedLayers = useMemo(() => {
    const parsed = normalizeGisLayers(layers);
    if (!isAmapBasemap) return parsed;
    return parsed.map((layer) => {
      if (!isAmapBasemap || !layer.geojson) return layer;
      return {
        ...layer,
        geojson: transformGeoJsonToGcj02(layer.geojson),
      };
    });
  }, [isAmapBasemap, layers]);

  // Filter layers by visible types if provided
  const filteredLayers = useMemo(
    () => visibleLayerTypes
      ? normalizedLayers.filter((l) => visibleLayerTypes.has(l.layerType as LayerType))
      : normalizedLayers.filter((l) => l.visible !== false),
    [normalizedLayers, visibleLayerTypes],
  );
  const primaryParcelLayer = useMemo(
    () => pickPrimaryParcelLayer(filteredLayers),
    [filteredLayers],
  );
  const [mounted, setMounted] = useState(false);
  const [hoverHighlightEnabled, setHoverHighlightEnabled] = useState(defaultHoverHighlight);
  const hoverHighlightActive = hoverPopup && hoverHighlightEnabled;

  useEffect(() => {
    if (hoverPopup) setHoverHighlightEnabled(defaultHoverHighlight);
  }, [hoverPopup, defaultHoverHighlight]);
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d');
  const viewModeRef = useRef<'2d' | '3d'>('2d');
  const mapInteractingRef = useRef(false);
  const mapCleanupRef = useRef<(() => void) | null>(null);
  const mapRef = useRef<MapRef>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const hasInitialFitRef = useRef(false);
  const interactiveLayerIdsRef = useRef<string[]>([]);
  const queryableLayerIdsRef = useRef<string[]>([]);

  // Popup state
  const [popupInfo, setPopupInfo] = useState<{
    longitude: number;
    latitude: number;
    feature: Feature<Geometry, GeoJsonProperties>;
    layerName: string;
    layerType: string;
    mode: 'hover' | 'click';
  } | null>(null);
  // Keep a separate geometry overlay for hover.  A popup alone makes it hard
  // to tell which irregular parcel is being described on a dense village map.
  const [hoveredFeature, setHoveredFeature] = useState<Feature<Geometry, GeoJsonProperties> | null>(null);
  const [hoveredVector, setHoveredVector] = useState<{
    feature: Feature<Geometry, GeoJsonProperties>;
    layerName: string;
    layerType: string;
  } | null>(null);
  const hoverFrameRef = useRef<number | null>(null);
  const latestHoverEventRef = useRef<MapLayerMouseEvent | null>(null);

  useEffect(() => {
    setMounted(true);
    return () => {
      if (hoverFrameRef.current !== null) {
        window.cancelAnimationFrame(hoverFrameRef.current);
      }
    };
  }, []);

  const resolveLayerMeta = useCallback((feature: Feature<Geometry, GeoJsonProperties> & { source?: string; layer?: { id?: string } }) => {
    const sourceKey = String(feature.source || '');
    const fromSource = sourceKey.match(/^layer-\d+-(.+)$/);
    if (fromSource?.[1]) {
      const layerName = fromSource[1];
      const layerType = filteredLayers.find((layer) => layer.layerName === layerName)?.layerType || 'custom';
      return { layerName, layerType };
    }
    const layerId = String(feature.layer?.id || '');
    const fromLayer = parseLayerNameFromMapLayerId(layerId);
    if (fromLayer) {
      const layerType = filteredLayers.find((layer) => layer.layerName === fromLayer)?.layerType || 'custom';
      return { layerName: fromLayer, layerType };
    }
    if (primaryParcelLayer) {
      return { layerName: primaryParcelLayer.layerName, layerType: primaryParcelLayer.layerType };
    }
    return { layerName: '未知图层', layerType: 'custom' };
  }, [filteredLayers, primaryParcelLayer]);

  const pickInteractiveFeature = useCallback((features: Feature<Geometry, GeoJsonProperties>[] | undefined) => {
    if (!features?.length) return null;

    const polygons = features.filter((candidate) => (
      candidate.geometry.type === 'Polygon' || candidate.geometry.type === 'MultiPolygon'
    )) as Feature<Geometry, GeoJsonProperties>[];

    if (polygons.length > 0) {
      return [...polygons].sort((left, right) => {
        const leftParcel = isParcelLikeFeature(left) ? 0 : 1;
        const rightParcel = isParcelLikeFeature(right) ? 0 : 1;
        if (leftParcel !== rightParcel) return leftParcel - rightParcel;
        return featureBBoxArea(left) - featureBBoxArea(right);
      })[0];
    }

    const lines = features.filter((candidate) => (
      candidate.geometry.type === 'LineString' || candidate.geometry.type === 'MultiLineString'
    ));
    if (lines.length > 0) return lines[0] as Feature<Geometry, GeoJsonProperties>;

    return features[0] as Feature<Geometry, GeoJsonProperties>;
  }, []);

  const pickFeature = pickInteractiveFeature;

  const resolveFeatureFromLayers = useCallback((hit: Feature<Geometry, GeoJsonProperties>) => {
    const hitId = featureIdentity(hit);
    for (const layer of filteredLayers) {
      const matched = layer.geojson.features.find((candidate) => featureIdentity(candidate as Feature<Geometry, GeoJsonProperties>) === hitId);
      if (matched) return matched as Feature<Geometry, GeoJsonProperties>;
    }
    return hit;
  }, [filteredLayers]);

  const lookupParcelAtEvent = useCallback((event: MapLayerMouseEvent) => {
    if (!hoverPopup || !primaryParcelLayer) return null;
    return findParcelAtLngLat(event.lngLat.lng, event.lngLat.lat, primaryParcelLayer);
  }, [hoverPopup, primaryParcelLayer]);

  const parcelHoverIdentity = useCallback((feature: Feature<Geometry, GeoJsonProperties> | null) => {
    if (!feature) return null;
    return getFeatureBsm(feature) ?? featureIdentity(feature);
  }, []);

  const applyParcelHover = useCallback((event: MapLayerMouseEvent) => {
    if ((event.originalEvent as MouseEvent | undefined)?.buttons) {
      setHoveredFeature(null);
      return;
    }

    const canvas = mapRef.current?.getCanvas();
    const feature = lookupParcelAtEvent(event);

    if (!feature) {
      if (canvas) canvas.style.cursor = '';
      setHoveredFeature(null);
      return;
    }

    if (canvas) canvas.style.cursor = 'pointer';
    const identity = parcelHoverIdentity(feature);
    setHoveredFeature((current) => (
      current && parcelHoverIdentity(current) === identity ? current : feature
    ));
  }, [lookupParcelAtEvent, parcelHoverIdentity]);

  const queryVectorAtEvent = useCallback((event: MapLayerMouseEvent) => {
    const map = mapRef.current?.getMap();
    const layerIds = queryableLayerIdsRef.current.filter((layerId) => isVectorPickLayerId(layerId));
    if (!map || layerIds.length === 0) return null;

    const hits = map.queryRenderedFeatures(event.point, { layers: layerIds }) as Feature<Geometry, GeoJsonProperties>[];
    const hit = pickVectorFeature(hits);
    if (!hit) return null;

    const feature = resolveFeatureFromLayers(hit);
    const meta = resolveLayerMeta(hit);
    return { feature, ...meta };
  }, [resolveFeatureFromLayers, resolveLayerMeta]);

  // Handle feature click
  const handleLayerClick = useCallback((event: MapLayerMouseEvent) => {
    if (hoverPopup) {
      const vectorHit = queryVectorAtEvent(event);
      if (vectorHit) {
        setPopupInfo({
          longitude: event.lngLat.lng,
          latitude: event.lngLat.lat,
          feature: vectorHit.feature,
          layerName: vectorHit.layerName,
          layerType: vectorHit.layerType,
          mode: 'click',
        });
        setHoveredVector(vectorHit);
        setHoveredFeature(null);
        return;
      }

      const feature = lookupParcelAtEvent(event);
      if (!feature) return;
      const { layerName, layerType } = resolveLayerMeta(feature);
      setPopupInfo({
        longitude: event.lngLat.lng,
        latitude: event.lngLat.lat,
        feature,
        layerName,
        layerType,
        mode: 'click',
      });
      setHoveredFeature(feature);
      setHoveredVector(null);
      return;
    }

    const hit = pickFeature(event.features as Feature<Geometry, GeoJsonProperties>[] | undefined);
    if (!hit) return;

    const feature = resolveFeatureFromLayers(hit);
    const { layerName, layerType } = resolveLayerMeta(hit);

    setPopupInfo({
      longitude: event.lngLat.lng,
      latitude: event.lngLat.lat,
      feature,
      layerName,
      layerType,
      mode: 'click',
    });
    setHoveredFeature(feature);
    setHoveredVector(null);
  }, [hoverPopup, lookupParcelAtEvent, pickFeature, queryVectorAtEvent, resolveFeatureFromLayers, resolveLayerMeta]);

  const handleLayerHover = useCallback((event: MapLayerMouseEvent) => {
    if (!hoverHighlightActive || mapInteractingRef.current) return;
    latestHoverEventRef.current = event;
    if (hoverFrameRef.current !== null) return;

    hoverFrameRef.current = window.requestAnimationFrame(() => {
      hoverFrameRef.current = null;
      const latest = latestHoverEventRef.current;
      if (!latest) return;

      const vectorHit = queryVectorAtEvent(latest);
      const canvas = mapRef.current?.getCanvas();
      if (vectorHit) {
        if (canvas) canvas.style.cursor = 'pointer';
        const identity = featureIdentity(vectorHit.feature);
        setHoveredVector((current) => (
          current && featureIdentity(current.feature) === identity ? current : vectorHit
        ));
        setHoveredFeature(null);
        return;
      }

      setHoveredVector(null);
      applyParcelHover(latest);
    });
  }, [hoverHighlightActive, applyParcelHover, queryVectorAtEvent]);

  const toggleHoverHighlight = useCallback(() => {
    setHoverHighlightEnabled((current) => {
      if (current) {
        setHoveredFeature(null);
        setHoveredVector(null);
        const canvas = mapRef.current?.getCanvas();
        if (canvas) canvas.style.cursor = '';
      }
      return !current;
    });
  }, []);

  const handleMapMouseLeave = useCallback(() => {
    const canvas = mapRef.current?.getCanvas();
    if (canvas) canvas.style.cursor = '';
    setHoveredFeature(null);
    setHoveredVector(null);
  }, []);

  const closePopup = useCallback(() => {
    setPopupInfo(null);
    setHoveredVector(null);
  }, []);

  const resetMapOrientation = useCallback(() => {
    mapRef.current?.easeTo({
      ...getCameraForViewMode(viewModeRef.current),
      duration: 600,
      easing: easeOutCubic,
      essential: true,
    });
  }, []);

  const changeViewMode = useCallback((mode: '2d' | '3d') => {
    viewModeRef.current = mode;
    setViewMode(mode);
    setPopupInfo(null);
    const camera = getCameraForViewMode(mode);
    const map = mapRef.current?.getMap();
    if (map) applyMapRotateMode(map, mode);
    mapRef.current?.easeTo({
      ...camera,
      duration: MAP_EASE_MS,
      easing: easeOutCubic,
      essential: true,
    });
  }, []);

  useEffect(() => {
    viewModeRef.current = viewMode;
  }, [viewMode]);

  useEffect(() => () => {
    mapCleanupRef.current?.();
    mapCleanupRef.current = null;
  }, []);

  // Fly to village center when no GIS layers present
  useEffect(() => {
    if (!mounted || !mapRef.current) return;
    if (filteredLayers.length > 0) return;
    if (!center || (displayCenter[0] === DEFAULT_CENTER[0] && displayCenter[1] === DEFAULT_CENTER[1])) return;
    mapRef.current.easeTo({
      center: displayCenter as [number, number],
      zoom: 13,
      ...getCameraForViewMode(viewModeRef.current),
      duration: 1500,
      easing: easeOutCubic,
      essential: true,
    });
  }, [mounted, filteredLayers.length, displayCenter]);

  // Keep MapLibre canvas in sync with the animated/resizable side panel.
  useEffect(() => {
    if (!mounted || !containerRef.current) return;
    const resize = () => mapRef.current?.resize();
    const observer = new ResizeObserver(resize);
    observer.observe(containerRef.current);
    const t1 = window.setTimeout(resize, 0);
    const t2 = window.setTimeout(resize, 250);
    return () => {
      observer.disconnect();
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [mounted]);

  // Auto-fit all valid GIS geometry. Prefer a boundary, but do not require it.
  // This callback is also invoked from onLoad: calling fitBounds before the
  // MapLibre style is ready leaves the camera at DEFAULT_CENTER on first load.
  const fitToLayers = useCallback((duration = MAP_EASE_MS) => {
    if (!mapRef.current) return;
    const camera = getCameraForViewMode(viewModeRef.current);
    if (filteredLayers.length === 0) {
      mapRef.current.easeTo({
        center: displayCenter as [number, number],
        zoom: 11,
        ...camera,
        duration,
        easing: easeOutCubic,
        essential: true,
      });
      return;
    }
    const preferred = filteredLayers.filter((l) => l.layerType === 'boundary');
    const candidates = preferred.length > 0 ? preferred : filteredLayers;
    let minLon = Infinity;
    let minLat = Infinity;
    let maxLon = -Infinity;
    let maxLat = -Infinity;

    for (const layer of candidates) {
      const bounds = getBoundsFromGeoJSON(layer.geojson);
      if (!bounds) continue;
      minLon = Math.min(minLon, bounds[0][0]);
      minLat = Math.min(minLat, bounds[0][1]);
      maxLon = Math.max(maxLon, bounds[1][0]);
      maxLat = Math.max(maxLat, bounds[1][1]);
    }

    if (!Number.isFinite(minLon)) return;
    const samePoint = Math.abs(maxLon - minLon) < 1e-7 && Math.abs(maxLat - minLat) < 1e-7;
    if (samePoint) {
      mapRef.current.easeTo({
        center: [minLon, minLat],
        zoom: 15,
        ...camera,
        duration,
        easing: easeOutCubic,
        essential: true,
      });
    } else {
      mapRef.current.fitBounds(
        expandBoundsForFit(minLon, minLat, maxLon, maxLat),
        {
          padding: fitPadding,
          duration,
          maxZoom: 13,
          pitch: camera.pitch,
          bearing: camera.bearing,
          easing: easeOutCubic,
          essential: true,
        },
      );
    }
  }, [center, displayCenter, filteredLayers, fitPadding]);

  const handleMapLoad = useCallback(() => {
    const map = mapRef.current?.getMap();
    const container = containerRef.current;
    const refreshMap = () => {
      mapRef.current?.resize();
      map?.triggerRepaint();
    };
    refreshMap();
    window.requestAnimationFrame(refreshMap);
    window.setTimeout(refreshMap, 120);
    if (map && container) {
      mapCleanupRef.current?.();
      mapCleanupRef.current = configureMapInteractions(
        map,
        container,
        (active) => { mapInteractingRef.current = active; },
        viewModeRef.current,
        () => viewModeRef.current,
      );
      map.once('idle', refreshMap);
    }
    if (!hasInitialFitRef.current) {
      window.requestAnimationFrame(() => {
        fitToLayers(0);
        hasInitialFitRef.current = true;
        refreshMap();
      });
    }
  }, [fitToLayers]);

  useEffect(() => {
    if (!mounted) return;
    if (hasInitialFitRef.current && !autoFitOnLayerChange) return;
    if (filteredLayers.length === 0) return;
    fitToLayers();
    hasInitialFitRef.current = true;
  }, [autoFitOnLayerChange, filteredLayers.length, fitToLayers, mounted]);

  // Build GeoJSON sources with layer priority sorting
  const geojsonSources = useMemo(() => {
    return [...filteredLayers].sort((a, b) => {
      const pa = LAYER_PRIORITY[a.layerType] || 0;
      const pb = LAYER_PRIORITY[b.layerType] || 0;
      return pa - pb;
    }).map((layer, index) => {
      const sourceId = `layer-${index}-${layer.layerName}`;
      return { sourceId, data: layer.geojson, layer };
    });
  }, [filteredLayers]);

  // HTML callouts keep Chinese labels available even when a raster base style
  // has no glyph server.  A deterministic grid keeps the map readable while
  // retaining complete project names (never the source CAD one-letter glyph).
  const mapLabels = useMemo(() => {
    const candidates: Array<{
      longitude: number;
      latitude: number;
      text: string;
      color: string;
      priority: number;
      role: string;
    }> = [];
    for (const layer of filteredLayers) {
      const role = String(layer.metadata?.displayRole || '');
      // Roads show details on click only — no persistent HTML callouts.
      const supportsLabels = layer.layerType === 'facility_point'
        || layer.layerType === 'development_axis'
        || role === 'spatial_structure';
      if (!supportsLabels) continue;
      for (const feature of layer.geojson.features || []) {
        const properties = feature.properties || {};
        const text = String(
          properties.project_name
          ?? properties.facility_name
          ?? properties.label
          ?? properties.name
          ?? '',
        ).trim();
        if (text.length < 2) continue;
        const anchor = getGeometryAnchor(feature.geometry);
        if (!anchor) continue;
        const displayRole = String(properties.display_role || role);
        const isCore = displayRole.includes('core');
        const isStructure = displayRole.includes('spatial_structure') || role === 'spatial_structure';
        const hasProjectName = Boolean(properties.project_name);
        const hasFacilityName = Boolean(properties.facility_name);
        candidates.push({
          longitude: anchor[0],
          latitude: anchor[1],
          text,
          color: String(properties.stroke || properties.color || layer.color || '#64748b'),
          priority: isCore ? 130 : isStructure ? 120 : hasProjectName ? 115 : hasFacilityName ? 100 : 72,
          role: isCore ? 'core' : isStructure ? 'structure' : hasProjectName ? 'project' : 'facility',
        });
      }
    }
    if (candidates.length === 0) return [];
    const minX = Math.min(...candidates.map((item) => item.longitude));
    const maxX = Math.max(...candidates.map((item) => item.longitude));
    const minY = Math.min(...candidates.map((item) => item.latitude));
    const maxY = Math.max(...candidates.map((item) => item.latitude));
    const cellX = Math.max((maxX - minX) / 19, 1e-8);
    const cellY = Math.max((maxY - minY) / 14, 1e-8);
    const occupied = new Set<string>();
    const duplicateNames = new Set<string>();
    return candidates
      .sort((a, b) => b.priority - a.priority || a.text.localeCompare(b.text, 'zh-CN'))
      .filter((candidate) => {
        const cell = `${Math.round((candidate.longitude - minX) / cellX)}:${Math.round((candidate.latitude - minY) / cellY)}`;
        const nameKey = `${candidate.text}:${cell}`;
        if (duplicateNames.has(nameKey)) return false;
        duplicateNames.add(nameKey);
        if (candidate.role !== 'core' && occupied.has(cell)) return false;
        occupied.add(cell);
        return true;
      })
      .slice(0, maxMapLabels);
  }, [filteredLayers, maxMapLabels]);

  // Extract active layer types for legend
  const activeLayerTypes = useMemo(() => {
    const types = new Set<LayerType>();
    for (const layer of filteredLayers) {
      const layerType = layer.layerType as LayerType;
      if (layerType && PLANNING_COLORS[layerType]) {
        types.add(layerType);
      }
    }
    return Array.from(types);
  }, [filteredLayers]);

  // Build layer styles — unified: ['get', 'color'] with ['match'] fallback
  const layerStyles = useMemo(() => {
    return geojsonSources.map(({ sourceId, layer }) => {
      if (layer.layerType === 'boundary' || layer.layerType === 'planning_scope') {
        const boundaryStyle = layer.layerType === 'planning_scope'
          ? (PLANNING_COLORS.planning_scope as Record<string, LineColors>)['规划村范围（GHCFW）']
          : (PLANNING_COLORS.boundary as Record<string, LineColors>)['行政边界'];
        const boundaryFill: FillLayerSpecification = {
          id: `${sourceId}-boundary-fill`,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': '#3fb589',
            'fill-opacity': 0.04,
          },
        };
        const boundaryLayer: LineLayerSpecification = {
          id: `${sourceId}-boundary`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': boundaryStyle.stroke,
            'line-width': boundaryStyle.width,
            'line-opacity': 1,
          },
        };
        return [boundaryFill, boundaryLayer];
      } else if (layer.layerType === 'facility_point' || layer.layerType === 'hazard_point') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        const isHazard = layer.layerType === 'hazard_point';
        const circleLayer: CircleLayerSpecification = {
          id: `${sourceId}-circle`,
          type: 'circle',
          source: sourceId,
          ...(layer.layerType === 'facility_point' ? {
            filter: ['!', ['has', 'text']] as ExpressionSpecification,
          } : {}),
          paint: {
            'circle-radius': [
              'interpolate', ['linear'], ['zoom'],
              10, styleNumber(layer, 'pointRadius', isHazard ? 3 : 3.5) * 0.8,
              14, styleNumber(layer, 'pointRadius', isHazard ? 4.5 : 5),
              18, styleNumber(layer, 'pointRadius', isHazard ? 7.5 : 8.5) * 1.45,
            ] as ExpressionSpecification,
            'circle-color': useFeatureColors
              ? ['get', 'color'] as ExpressionSpecification
              : isHazard
                ? buildMatchExpression('hazard_scale', PLANNING_COLORS.hazard_point, styleColor(layer, 'fillColor', '#ef4444'))
                : buildMatchExpression('status', PLANNING_COLORS.facility_point, styleColor(layer, 'fillColor', DEFAULT_COLORS.fill)),
            'circle-stroke-width': [
              'interpolate', ['linear'], ['zoom'],
              10, 1.2, 14, 2, 18, 2.6,
            ] as ExpressionSpecification,
            'circle-stroke-color': isHazard
              ? '#ffffff'
              : [
                'match',
                ['get', 'status'],
                '规划新建', '#ffffff',
                '规划改扩建', '#ffffff',
                '规划迁建', '#ffffff',
                '#f8fafc',
              ] as ExpressionSpecification,
            'circle-opacity': styleNumber(layer, 'pointOpacity', isHazard ? 0.95 : 0.88),
          },
        };
        return [circleLayer];
      } else if (layer.layerType === 'development_axis') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-line`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': useFeatureColors
              ? ['get', 'color'] as ExpressionSpecification
              : buildMatchExpression('axis_type', PLANNING_COLORS.development_axis, styleColor(layer, 'lineColor', '#00AA00'), 'stroke'),
            'line-width': useFeatureColors
              ? ['coalesce', ['get', 'weight'], styleNumber(layer, 'lineWidth', 2)] as ExpressionSpecification
              : styleNumber(layer, 'lineWidth', 2),
            'line-opacity': styleNumber(layer, 'lineOpacity', 1),
            ...(styleDasharray(layer) ? { 'line-dasharray': styleDasharray(layer) } : {}),
          },
        };
        return [lineLayer];
      } else if (layer.layerType === 'planned_road') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        const roadPalette = PLANNING_COLORS.planned_road;
        const baseWidth = useFeatureColors
          ? ['min', ['coalesce', ['get', 'weight'], 3], 4] as ExpressionSpecification
          : buildMatchExpression(['construction_action', 'road_action'], roadPalette, 3, 'width');
        const roadColor = useFeatureColors
          ? ['get', 'color'] as ExpressionSpecification
          : buildMatchExpression(['construction_action', 'road_action'], roadPalette, '#D73027', 'stroke');
        const casingLayer: LineLayerSpecification = {
          id: `${sourceId}-road-casing`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': '#ffffff',
            'line-width': ['+', baseWidth, 1.2] as ExpressionSpecification,
            'line-opacity': 0.75,
          },
        };
        const roadLayer: LineLayerSpecification = {
          id: `${sourceId}-planned-road`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': roadColor,
            'line-width': baseWidth,
            'line-opacity': 0.9,
            'line-dasharray': buildRoadDashExpression(),
          },
          layout: {
            'line-cap': 'round',
            'line-join': 'round',
          },
        };
        return [casingLayer, roadLayer];
      } else if (layer.layerType === 'infrastructure') {
        const styleDriven = isStyleDrivenLayer(layer);
        const useFeatureColors = !styleDriven && hasFeatureColors(layer.geojson);
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-infra`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': styleDriven
              ? styleColor(layer, 'lineColor', '#666666')
              : useFeatureColors
                ? ['get', 'color'] as ExpressionSpecification
                : buildMatchExpression('infra_type', PLANNING_COLORS.infrastructure, styleColor(layer, 'lineColor', '#666666'), 'stroke'),
            'line-width': styleDriven
              ? styleNumber(layer, 'lineWidth', 2)
              : useFeatureColors
                ? ['coalesce', ['get', 'weight'], styleNumber(layer, 'lineWidth', 2)] as ExpressionSpecification
                : styleNumber(layer, 'lineWidth', 2),
            'line-opacity': styleNumber(layer, 'lineOpacity', 1),
            ...(styleDasharray(layer) ? { 'line-dasharray': styleDasharray(layer) } : {}),
          },
        };
        return [lineLayer];
      } else if (layer.layerType === 'sensitivity_zone') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        const fillLayer: FillLayerSpecification = {
          id: `${sourceId}-fill`,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': useFeatureColors
              ? ['get', 'color'] as ExpressionSpecification
              : buildMatchExpression('sensitivity_level', PLANNING_COLORS.sensitivity_zone, DEFAULT_COLORS.fill),
            'fill-opacity': 0.16,
          },
        };
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-line`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': useFeatureColors
              ? ['get', 'stroke'] as ExpressionSpecification
              : buildMatchExpression('sensitivity_level', PLANNING_COLORS.sensitivity_zone, DEFAULT_COLORS.stroke, 'stroke'),
            'line-width': 0.8,
            'line-opacity': 0.65,
          },
        };
        return [fillLayer, lineLayer];
      } else if (layer.layerType === 'isochrone') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        // Isochrone match: time_minutes is numeric (5/10/15), PLANNING_COLORS keys are '5min'/'10min'/'15min'
        const isoMatch = (field: 'fill' | 'stroke', defaultColor: string): ExpressionSpecification =>
          ['match', ['to-string', ['get', 'time_minutes']],
            ...Object.entries(PLANNING_COLORS.isochrone).flatMap(([k, c]) => [k.replace('min', ''), (c as FeatureColors)[field]]),
            defaultColor] as ExpressionSpecification;
        const fillLayer: FillLayerSpecification = {
          id: `${sourceId}-fill`,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': useFeatureColors ? ['get', 'color'] as ExpressionSpecification : isoMatch('fill', DEFAULT_COLORS.fill),
            'fill-opacity': 0.2,
          },
        };
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-line`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': useFeatureColors ? ['get', 'stroke'] as ExpressionSpecification : isoMatch('stroke', DEFAULT_COLORS.stroke),
            'line-width': 1,
          },
        };
        return [fillLayer, lineLayer];
      } else if (layer.layerType === 'planning_zone') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        const categoryFields = LAYER_CATEGORY_FIELDS.planning_zone || ['zone_type'];
        const fillLayer: FillLayerSpecification = {
          id: `${sourceId}-fill`,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': useFeatureColors
              ? ['get', 'color'] as ExpressionSpecification
              : buildMatchExpression(categoryFields, PLANNING_COLORS.planning_zone, DEFAULT_COLORS.fill),
            'fill-opacity': styleNumber(layer, 'fillOpacity', 0.12),
          },
        };
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-line`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': useFeatureColors
              ? ['get', 'stroke'] as ExpressionSpecification
              : buildMatchExpression(categoryFields, PLANNING_COLORS.planning_zone, DEFAULT_COLORS.stroke, 'stroke'),
            'line-width': styleNumber(layer, 'lineWidth', 1.5),
            'line-dasharray': styleDasharray(layer) || [3, 2],
            'line-opacity': styleNumber(layer, 'lineOpacity', 0.9),
          },
        };
        return [fillLayer, lineLayer];
      } else if (layer.layerType === 'function_zone' || layer.layerType === 'final_landuse' || layer.layerType === 'land_use_zone' || layer.layerType === 'construction_control') {
        const styleDriven = isStyleDrivenLayer(layer);
        const useFeatureColors = !styleDriven && hasFeatureColors(layer.geojson);
        const isOfflineLanduse = isOfflineBasemap && (
          layer.layerName === '现状用地（原版底图）'
          || layer.layerName === 'landuse'
          || layer.layerType === 'final_landuse'
        );
        const defaultOpacity = layer.layerType === 'construction_control'
          ? 0.12
          : layer.layerType === 'land_use_zone'
            ? 0.18
            : layer.layerType === 'function_zone' ? 0.42 : 0.52;
        const opacity = isOfflineLanduse
          ? Math.max(styleNumber(layer, 'fillOpacity', defaultOpacity), 0.85)
          : styleDriven
            ? styleNumber(layer, 'fillOpacity', defaultOpacity)
            : styleNumber(layer, 'fillOpacity', defaultOpacity);
        const palette = layer.layerType === 'function_zone' && !styleDriven
          ? PLANNING_COLORS.final_landuse
          : PLANNING_COLORS[layer.layerType] as Record<string, Record<string, unknown>>;
        const categoryFields = layer.layerType === 'function_zone' && !styleDriven
          ? (LAYER_CATEGORY_FIELDS.final_landuse || ['zone_type'])
          : (LAYER_CATEGORY_FIELDS[layer.layerType] || ['zone_type']);
        const fillColor = styleDriven
          ? styleColor(layer, 'fillColor', DEFAULT_COLORS.fill)
          : useFeatureColors
            ? ['get', 'color'] as ExpressionSpecification
            : buildMatchExpression(categoryFields, palette, DEFAULT_COLORS.fill);
        const fillLayer: FillLayerSpecification = {
          id: `${sourceId}-fill`,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': fillColor,
            'fill-opacity': opacity,
          },
        };
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-line`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': styleDriven
              ? styleColor(layer, 'lineColor', DEFAULT_COLORS.stroke)
              : useFeatureColors
                ? ['get', 'stroke'] as ExpressionSpecification
                : buildMatchExpression(categoryFields, palette, DEFAULT_COLORS.stroke, 'stroke'),
            'line-width': styleNumber(layer, 'lineWidth', layer.layerType === 'construction_control' ? 1.8 : 0.9),
            'line-opacity': styleNumber(layer, 'lineOpacity', layer.layerType === 'construction_control' ? 0.85 : 0.62),
            ...(styleDasharray(layer) ? { 'line-dasharray': styleDasharray(layer) } : {}),
          },
        };
        if (viewMode === '3d' && layer.layerType === 'final_landuse') {
          const extrusionLayer: FillExtrusionLayerSpecification = {
            id: `${sourceId}-extrusion`,
            type: 'fill-extrusion',
            source: sourceId,
            filter: ['>', ['coalesce', ['get', '_planning_height_m'], 0], 0],
            paint: {
              'fill-extrusion-color': fillColor,
              'fill-extrusion-height': ['coalesce', ['get', '_planning_height_m'], 0] as ExpressionSpecification,
              'fill-extrusion-base': 0,
              'fill-extrusion-opacity': 0.82,
              'fill-extrusion-vertical-gradient': true,
            },
          };
          return [fillLayer, extrusionLayer, lineLayer];
        }
        return [fillLayer, lineLayer];
      }
      // Default: fill + line for unknown layer types
      const defaultFill: FillLayerSpecification = {
        id: `${sourceId}-fill`,
        type: 'fill',
        source: sourceId,
        paint: {
          'fill-color': hasFeatureColors(layer.geojson) ? ['get', 'color'] as ExpressionSpecification : DEFAULT_COLORS.fill,
          'fill-opacity': 0.5,
        },
      };
      const defaultLine: LineLayerSpecification = {
        id: `${sourceId}-line`,
        type: 'line',
        source: sourceId,
        paint: {
          'line-color': hasFeatureColors(layer.geojson) ? ['get', 'stroke'] as ExpressionSpecification : DEFAULT_COLORS.stroke,
          'line-width': 1.5,
        },
      };
      return [defaultFill, defaultLine];
    });
  }, [geojsonSources, isOfflineBasemap, viewMode]);

  // Memoize interactive layer IDs for click handling
  const interactiveLayerIds = useMemo(() =>
    geojsonSources.flatMap(
      (_, index) => (layerStyles[index] || []).map(ls => ls.id)
    ).filter(Boolean),
    [geojsonSources, layerStyles],
  );

  const queryableLayerIds = useMemo(
    () => interactiveLayerIds.filter((layerId) => (
      layerId.endsWith('-fill')
      || layerId.endsWith('-line')
      || layerId.endsWith('-circle')
      || layerId.endsWith('-boundary')
      || layerId.endsWith('-boundary-fill')
      || layerId.endsWith('-infra')
      || layerId.endsWith('-planned-road')
      || layerId.endsWith('-road-casing')
    )),
    [interactiveLayerIds],
  );

  const vectorPickLayerIds = useMemo(
    () => queryableLayerIds.filter((layerId) => isVectorPickLayerId(layerId)),
    [queryableLayerIds],
  );

  const effectiveQueryableLayerIds = hoverPopup ? vectorPickLayerIds : queryableLayerIds;

  const displayMapLabels = useMemo(() => {
    if (!hoverPopup) return mapLabels;
    return mapLabels.filter((label) => label.role !== 'facility' || label.priority >= 100);
  }, [hoverPopup, mapLabels]);

  useEffect(() => {
    interactiveLayerIdsRef.current = interactiveLayerIds;
    queryableLayerIdsRef.current = queryableLayerIds;
  }, [interactiveLayerIds, queryableLayerIds]);

  // Build base map style - dynamic based on baseMapType
  const mapStyle: StyleSpecification = useMemo(() => {
    if (offlineBaseMap || tileSourceOverride === 'offline') {
      return {
        version: 8,
        sources: {},
        layers: [
          { id: 'background', type: 'background', paint: { 'background-color': '#d5dde6' } },
        ],
      } as StyleSpecification;
    }
    const tileSource = normalizeTileSource(tileSourceOverride || process.env.NEXT_PUBLIC_TILE_SOURCE || TILE_SOURCES.AMAP);

    // Handle non-Tianditu tile sources
    if (tileSource !== TILE_SOURCES.TIANDITU) {
      const otherConfigs: Record<string, { baseUrl: string | string[]; attribution: string }> = {
        [TILE_SOURCES.AMAP]: { baseUrl: getAmapTileUrls(), attribution: '高德地图' },
        [TILE_SOURCES.GEOQ]: { baseUrl: getGeoqTileUrl(), attribution: 'GeoQ' },
        [TILE_SOURCES.OSM]: { baseUrl: getOsmTileUrl(), attribution: 'OpenStreetMap' },
      };
      const config = otherConfigs[tileSource] || otherConfigs[TILE_SOURCES.AMAP];
      const maxZoom = tileSource === TILE_SOURCES.AMAP ? 18 : 19;
      return {
        version: 8,
        sources: {
          'base-tiles': buildRasterTileSource(config.baseUrl, config.attribution, maxZoom),
        },
        layers: [
          { id: 'background', type: 'background', paint: { 'background-color': '#eef4f7' } },
          { id: 'base-tiles-layer', type: 'raster', source: 'base-tiles', paint: RASTER_LAYER_PAINT },
        ],
      } as StyleSpecification;
    }

    // Tianditu with annotation layer
    const { baseUrl, annotationUrl } = getTiandituUrls(baseMapType);
    return {
      version: 8,
      sources: {
        'base-tiles': buildRasterTileSource(baseUrl, '天地图', 18),
        'annotation-tiles': buildRasterTileSource(annotationUrl, '天地图注记', 18),
      },
      layers: [
        { id: 'background', type: 'background', paint: { 'background-color': '#eef4f7' } },
        { id: 'base-tiles-layer', type: 'raster', source: 'base-tiles', paint: RASTER_LAYER_PAINT },
        { id: 'annotation-tiles-layer', type: 'raster', source: 'annotation-tiles', paint: RASTER_LAYER_PAINT },
      ],
    } as StyleSpecification;
  }, [baseMapType, offlineBaseMap, tileSourceOverride, mounted]);

  const basemapKey = offlineBaseMap || tileSourceOverride === 'offline'
    ? 'offline'
    : `${normalizeTileSource(tileSourceOverride || process.env.NEXT_PUBLIC_TILE_SOURCE || TILE_SOURCES.AMAP)}-${baseMapType}`;

  useEffect(() => {
    hasInitialFitRef.current = false;
  }, [basemapKey]);

  useEffect(() => {
    if (!mounted) return;
    const map = mapRef.current?.getMap();
    if (!map) return;

    const refreshMap = () => {
      mapRef.current?.resize();
      map.triggerRepaint();
    };

    if (map.isStyleLoaded()) {
      refreshMap();
      return;
    }

    map.once('style.load', refreshMap);
    return () => {
      map.off('style.load', refreshMap);
    };
  }, [basemapKey, mapStyle, mounted]);

  useEffect(() => {
    if (!mounted) return;
    const map = mapRef.current?.getMap();
    if (!map) return;
    applyMapRotateMode(map, viewMode);
  }, [mounted, viewMode]);

  if (!mounted) {
    return (
      <div
        className={`bg-gray-100 flex items-center justify-center ${frameless ? '' : 'rounded-lg'}`}
        style={{ height }}
      >
        <span className="text-gray-500">加载地图中...</span>
      </div>
    );
  }

  return (
    <div className={frameless ? 'h-full overflow-hidden' : 'rounded-lg overflow-hidden border border-gray-200'}>
      {title && (
        <div className="bg-gray-50 px-4 py-2 border-b border-gray-200">
          <h3 className="text-sm font-medium text-gray-700">{title}</h3>
        </div>
      )}
      <div
        ref={containerRef}
        className="map-view-container select-none"
        style={{
          height,
          position: 'relative',
          background: '#eef4f7',
          overscrollBehavior: 'contain',
          touchAction: 'none',
        }}
      >
        <Map
          key={basemapKey}
          ref={mapRef}
          reuseMaps={false}
          {...MAP_INTERACTION_OPTIONS}
          initialViewState={{
            longitude: displayCenter[0],
            latitude: displayCenter[1],
            zoom: zoom,
          }}
          style={{ width: '100%', height: '100%' }}
          mapStyle={mapStyle}
          minZoom={1}
          maxZoom={20}
          scrollZoom={{ around: 'center' }}
          dragRotate={false}
          pitchWithRotate
          touchPitch
          touchZoomRotate
          minPitch={0}
          maxPitch={viewMode === '3d' ? 55 : 0}
          bearingSnap={0}
          interactiveLayerIds={effectiveQueryableLayerIds}
          cursor={hoverHighlightActive ? 'default' : undefined}
          onClick={handleLayerClick}
          onMouseMove={hoverHighlightActive ? handleLayerHover : undefined}
          onMouseLeave={hoverHighlightActive ? handleMapMouseLeave : undefined}
          onLoad={handleMapLoad}
          onError={(event) => {
            // A failed base tile must not prevent local GeoJSON from rendering.
            console.warn('[GIS] map resource error:', event.error?.message || event);
          }}
        >
          <NavigationControl position="top-left" showCompass visualizePitch={viewMode === '3d'} />
          <ScaleControl position="bottom-left" unit="metric" />
          {geojsonSources.map(({ sourceId, data }, index) => (
            <Source
              key={sourceId}
              id={sourceId}
              type="geojson"
              data={data as FeatureCollection<Geometry>}
            >
              {(layerStyles[index] || []).map((layerStyle) => (
                <Layer key={layerStyle.id} {...layerStyle} />
              ))}
            </Source>
          ))}

          {/* Subtle white veil on hover — matches kg_inspection_v2 deck.gl autoHighlight */}
          {hoverHighlightActive && hoveredFeature && (
            <Source
              id="hovered-feature-footprint"
              type="geojson"
              data={{ type: 'FeatureCollection', features: [hoveredFeature] } as FeatureCollection<Geometry>}
            >
              {(hoveredFeature.geometry.type === 'Polygon' || hoveredFeature.geometry.type === 'MultiPolygon') && (
                <Layer
                  id="hovered-feature-fill"
                  type="fill"
                  paint={{ 'fill-color': '#ffffff', 'fill-opacity': 0.48 }}
                  layout={{ 'fill-sort-key': 9999 }}
                />
              )}
              <Layer
                id="hovered-feature-outline"
                type="line"
                paint={{
                  'line-color': '#ffffff',
                  'line-width': 2.5,
                  'line-opacity': 0.9,
                }}
                layout={{ 'line-sort-key': 9999 }}
              />
            </Source>
          )}

          {displayMapLabels.map((label, index) => (
            <Marker
              key={`${label.text}-${index}`}
              longitude={label.longitude}
              latitude={label.latitude}
              anchor="center"
              style={{ pointerEvents: 'none' }}
            >
              <div
                className={`pointer-events-none max-w-[188px] whitespace-pre-line break-words rounded-md px-2 py-1 text-center text-[10px] font-medium leading-[1.25] shadow-sm ${
                  label.role === 'core'
                    ? 'bg-yellow-100 text-red-800 ring-2 ring-red-500'
                    : label.role === 'project'
                      ? 'bg-white/95 text-red-700 ring-1 ring-red-300'
                      : label.role === 'structure'
                        ? 'bg-violet-50 text-violet-800 ring-1 ring-violet-300'
                        : 'bg-white/92 text-slate-800 ring-1 ring-emerald-300'
                }`}
              >
                {label.text}
              </div>
            </Marker>
          ))}

          {/* Feature Popup — click only */}
          {popupInfo?.mode === 'click' && (
            <Popup
              longitude={popupInfo.longitude}
              latitude={popupInfo.latitude}
              onClose={closePopup}
              closeButton
              closeOnClick={false}
              closeOnMove={false}
              anchor="top"
              className="feature-popup"
            >
              <FeaturePopupContent
                feature={popupInfo.feature}
                layerName={popupInfo.layerName}
                layerType={popupInfo.layerType}
                hover={false}
              />
            </Popup>
          )}
        </Map>
        {hoverHighlightActive && hoveredVector && (
          <div className="pointer-events-none absolute right-3 top-3 z-20 max-w-[240px] rounded-lg bg-[#26323b]/94 px-3 py-2 text-white shadow-lg">
            <div
              className="mb-1 inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold text-white"
              style={{ backgroundColor: getFeatureKindBadge(hoveredVector.layerType, hoveredVector.feature).tone }}
            >
              {getFeatureKindBadge(hoveredVector.layerType, hoveredVector.feature).label}
            </div>
            <div className="break-words text-xs font-semibold leading-5">
              {getFeatureDisplayName(hoveredVector.feature, hoveredVector.layerType) || hoveredVector.layerName}
            </div>
            <div className="mt-1 text-[10px] text-slate-300">单击查看详情</div>
          </div>
        )}
        {hoverHighlightActive && !hoveredVector && hoveredFeature && (
          <div className="pointer-events-none absolute right-3 top-3 z-20 rounded-lg bg-[#26323b]/92 px-3 py-1.5 text-xs font-medium text-white shadow-lg">
            <div className="text-[10px] text-emerald-300">规划地块</div>
            <div className="mt-0.5">地块编号：{getFeatureBsm(hoveredFeature) ?? featureIdentity(hoveredFeature)}</div>
            <div className="mt-1 text-[10px] text-slate-300">单击查看属性</div>
          </div>
        )}
        <div
          className="absolute left-12 top-2 z-10 flex h-8 overflow-hidden rounded border border-gray-200 bg-white shadow-sm"
          role="group"
          aria-label="地图视图模式"
        >
          <button
            type="button"
            title="锁定村域视角"
            aria-label="锁定村域视角"
            onClick={() => fitToLayers(MAP_EASE_MS)}
            className="flex h-8 items-center gap-1 border-r border-gray-200 px-2.5 text-[11px] font-medium text-[#2f7a61] transition-colors hover:bg-emerald-50"
          >
            <FontAwesomeIcon icon={faCrosshairs} style={{ width: 13, height: 13 }} />
            <span>锁定视角</span>
          </button>
          <button
            type="button"
            title="二维平面"
            aria-label="切换到二维平面"
            aria-pressed={viewMode === '2d'}
            onClick={() => changeViewMode('2d')}
            className={`flex h-8 w-8 items-center justify-center border-r border-gray-200 transition-colors ${viewMode === '2d' ? 'bg-cyan-50 text-cyan-700' : 'text-gray-500 hover:bg-gray-50'}`}
          >
            <FontAwesomeIcon icon={faMap} style={{ width: 14, height: 14 }} />
          </button>
          <button
            type="button"
            title="三维立体（右键拖动旋转/俯仰）"
            aria-label="切换到三维立体"
            aria-pressed={viewMode === '3d'}
            onClick={() => changeViewMode('3d')}
            className={`flex h-8 w-8 items-center justify-center transition-colors ${viewMode === '3d' ? 'bg-cyan-50 text-cyan-700' : 'text-gray-500 hover:bg-gray-50'} ${viewMode === '3d' || hoverPopup ? 'border-r border-gray-200' : ''}`}
          >
            <FontAwesomeIcon icon={faCube} style={{ width: 14, height: 14 }} />
          </button>
          <button
            type="button"
            title="复位地图方向"
            aria-label="复位地图方向"
            onClick={resetMapOrientation}
            className={`flex h-8 items-center gap-1 border-r border-gray-200 px-2.5 text-[11px] font-medium text-[#2f7a61] transition-colors hover:bg-emerald-50 ${hoverPopup ? '' : ''}`}
          >
            <span>复位方向</span>
          </button>
          {hoverPopup && (
            <button
              type="button"
              title={hoverHighlightEnabled ? '关闭悬停高亮' : '开启悬停高亮'}
              aria-label={hoverHighlightEnabled ? '关闭悬停高亮' : '开启悬停高亮'}
              aria-pressed={hoverHighlightEnabled}
              onClick={toggleHoverHighlight}
              className={`flex h-8 items-center gap-1 px-2.5 text-[11px] font-medium transition-colors ${
                hoverHighlightEnabled
                  ? 'bg-emerald-50 text-[#2f7a61]'
                  : 'text-gray-500 hover:bg-gray-50'
              }`}
            >
              <FontAwesomeIcon icon={faHighlighter} style={{ width: 13, height: 13 }} />
              <span>悬停高亮</span>
            </button>
          )}
        </div>
        {showLegend && activeLayerTypes.length > 0 && (
          <LegendPanel
            layerTypes={activeLayerTypes}
            layers={filteredLayers}
            position={legendPosition}
            collapsible={compactLegend}
            defaultCollapsed={compactLegend}
          />
        )}
      </div>
    </div>
  );
}
