import type {
  GISLayerConfig,
  GeoJsonFeature,
  GeoJsonFeatureCollection,
  GeoJsonGeometry,
} from '@/types/message/message-types';
import { classifyLanduseZone } from '@/features/planning/constants/gis';

const VALID_LAYER_TYPES = new Set<GISLayerConfig['layerType']>([
  'boundary',
  'planning_scope',
  'final_landuse',
  'land_use_zone',
  'construction_control',
  'function_zone',
  'facility_point',
  'hazard_point',
  'development_axis',
  'sensitivity_zone',
  'isochrone',
  'infrastructure',
  'planning_zone',
  'settlement_zone',
  'planned_road',
]);

const LAYER_TYPE_ALIASES: Record<string, GISLayerConfig['layerType']> = {
  custom_functional_zone: 'function_zone',
  road_planned: 'planned_road',
  planned_roads: 'planned_road',
  facility: 'facility_point',
  facilities: 'facility_point',
  public_service: 'facility_point',
};

const FACILITY_SYMBOL_LABELS: Record<string, string> = {
  '篮': '篮球场',
  '健': '健身活动场地',
  '广': '公共活动广场',
  '停': '停车场',
  '电': '电力设施',
  '污': '污水处理设施',
  '水': '供水设施',
  '垃': '垃圾收集设施',
  '卫': '公共厕所',
  '厕': '公共厕所',
  '祠': '祠堂文化设施',
  '村': '村委会',
  '站': '公共交通站点',
  '小': '学校',
  '园': '公共绿地与游园',
  '游': '游憩设施',
  '养': '养老服务设施',
  '文': '文化活动室',
  '服': '综合服务设施',
};

function normalizeFacilityLabel(
  properties: Record<string, unknown>,
): Record<string, unknown> {
  const symbol = String(properties['注记'] ?? properties.text ?? properties.label ?? '').trim();
  const semanticName = FACILITY_SYMBOL_LABELS[symbol];
  if (!semanticName) return properties;

  const category = String(properties['分类'] ?? properties.category ?? properties.status ?? '');
  const isPlanned = category.includes('规划') || /planned|proposed/i.test(category);
  const displayName = `${isPlanned ? '规划' : '现状'}${semanticName}`;
  return {
    ...properties,
    annotation_symbol: symbol,
    facility_type: semanticName,
    facility_name: displayName,
    label: displayName,
    // Assign a status so the facility palette (现状保留/规划新建/…) can color
    // the circle marker instead of falling back to gray.
    status: isPlanned ? '规划新建' : '现状保留',
  };
}

// Map detailed current landuse names (DLMC/SDDLMC) to the four broad
// categories used by the final_landuse palette so current parcels render
// with consistent colors instead of the default gray fallback.
// (LANDUSE_TO_ZONE lives in constants/gis.ts)

function normalizeLanduseFeature(feature: GeoJsonFeature): GeoJsonFeature {
  const properties = feature.properties || {};
  const zone = classifyLanduseZone(properties);
  if (!zone || properties.zone_type) return feature;
  return {
    ...feature,
    properties: { ...properties, zone_type: zone },
  };
}

// Assign stable colors to road layers that do not carry per-feature style
// properties, so current and planned roads are visually distinguishable.
// Current roads get a wider stroke so the brown network still shows through
// under the red planned overlay instead of being fully hidden.
const ROAD_SOURCE_COLORS: Record<string, { color: string; stroke: string; weight: number }> = {
  current: { color: '#8B7355', stroke: '#5D4E37', weight: 3.2 },
  planned: { color: '#D73027', stroke: '#8B1A10', weight: 2.4 },
  project: { color: '#4C78A8', stroke: '#2E4A66', weight: 3 },
};

function roadSourceFromPath(path: string): keyof typeof ROAD_SOURCE_COLORS | undefined {
  if (path.includes('/current/')) return 'current';
  if (path.includes('/planned/')) return 'planned';
  if (path.includes('/project/')) return 'project';
  return undefined;
}

function normalizeInfrastructureFeature(
  feature: GeoJsonFeature,
  path: string,
): GeoJsonFeature {
  const properties = feature.properties || {};
  if (properties.color && properties.stroke) return feature;

  // Hydrology from Tianditu WFS should always render as blue water.
  if (/\bhyd/i.test(path)) {
    return {
      ...feature,
      properties: {
        ...properties,
        color: '#00BFFF',
        stroke: '#009ACD',
        weight: 3.5,
        infra_type: properties.infra_type ?? '河流',
      },
    };
  }

  const source = roadSourceFromPath(path);
  if (!source) return feature;
  return {
    ...feature,
    properties: {
      ...properties,
      ...ROAD_SOURCE_COLORS[source],
      infra_type: properties.infra_type ?? source,
    },
  };
}

// CAD drawing-frame annotations in project/annotation are legend artifacts
// and should not be counted as facilities or rendered as map labels.
// Only the pure scale/legend text entries are excluded; real project and
// facility annotations such as "村庄规划范围" are kept so the total matches
// the historical reference count (180).
const LEGEND_LABELS = new Set([
  '图   例',
  '图例',
  '1200M',
  '600',
  '300',
  '0',
  'N',
]);

function isJunkAnnotationFeature(feature: GeoJsonFeature): boolean {
  const properties = feature.properties || {};
  const text = String(properties.text ?? properties.label ?? properties['注记'] ?? '').trim();
  const layer = String(properties.layer ?? '');
  if (layer === 'TX-图框') return true;
  if (LEGEND_LABELS.has(text)) return true;
  return /图例|比例尺|指北针|1200M|M$|^图|^例/i.test(text);
}

function parseMaybeJson(value: unknown): unknown {
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function normalizePosition(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length < 2) return null;
  const first = Number(value[0]);
  const second = Number(value[1]);
  if (!Number.isFinite(first) || !Number.isFinite(second)) return null;

  // GeoJSON requires [longitude, latitude]. A common backend mistake is [lat, lng].
  if (Math.abs(first) <= 90 && Math.abs(second) > 90 && Math.abs(second) <= 180) {
    return [second, first, ...value.slice(2).map(Number).filter(Number.isFinite)];
  }
  if (Math.abs(first) > 180 || Math.abs(second) > 90) return null;
  return [first, second, ...value.slice(2).map(Number).filter(Number.isFinite)];
}

function normalizeCoordinates(value: unknown): unknown {
  const point = normalizePosition(value);
  if (point) return point;
  if (!Array.isArray(value)) return value;
  return value
    .map(normalizeCoordinates)
    .filter((item) => item !== null && item !== undefined);
}

function normalizeGeometry(raw: unknown): GeoJsonGeometry | null {
  const value = parseMaybeJson(raw);
  if (!value || typeof value !== 'object') return null;
  const obj = value as Record<string, unknown>;
  const type = typeof obj.type === 'string' ? obj.type : '';
  if (!type || !('coordinates' in obj)) return null;
  const coordinates = normalizeCoordinates(obj.coordinates);
  if (!coordinates) return null;
  return { type: type as GeoJsonGeometry['type'], coordinates };
}

function normalizeFeature(raw: unknown): GeoJsonFeature | null {
  const value = parseMaybeJson(raw);
  if (!value || typeof value !== 'object') return null;
  const obj = value as Record<string, unknown>;

  if (obj.type === 'Feature') {
    const geometry = normalizeGeometry(obj.geometry);
    if (!geometry) return null;
    return {
      type: 'Feature',
      properties:
        obj.properties && typeof obj.properties === 'object'
          ? (obj.properties as Record<string, unknown>)
          : {},
      geometry,
    };
  }

  const geometry = normalizeGeometry(obj);
  if (!geometry) return null;
  return {
    type: 'Feature',
    properties: {},
    geometry,
  };
}

export function normalizeFeatureCollection(raw: unknown): GeoJsonFeatureCollection | null {
  const value = parseMaybeJson(raw);
  if (!value || typeof value !== 'object') return null;
  const obj = value as Record<string, unknown>;

  if (obj.type === 'FeatureCollection') {
    const features = Array.isArray(obj.features)
      ? obj.features.map(normalizeFeature).filter((f): f is GeoJsonFeature => Boolean(f))
      : [];
    return { type: 'FeatureCollection', features };
  }

  const feature = normalizeFeature(obj);
  return feature ? { type: 'FeatureCollection', features: [feature] } : null;
}

function inferLayerType(raw: Record<string, unknown>, index: number): GISLayerConfig['layerType'] {
  const candidate = String(
    raw.layerType ?? raw.layer_type ?? raw.kind ?? raw.category ?? '',
  ).trim() as GISLayerConfig['layerType'];
  const alias = LAYER_TYPE_ALIASES[candidate];
  if (alias) return alias;
  if (VALID_LAYER_TYPES.has(candidate)) return candidate;

  const name = String(raw.layerName ?? raw.layer_name ?? raw.name ?? '').toLowerCase();
  if (/boundary|边界/.test(name)) return 'boundary';
  if (/ghcfw|规划范围/.test(name)) return 'planning_scope';
  if (/qmdltb|期末地类/.test(name)) return 'final_landuse';
  if (/tdyt|用途分区/.test(name)) return 'land_use_zone';
  if (/jsydgzq|建设用地管制/.test(name)) return 'construction_control';
  if (/facility|设施|节点/.test(name)) return 'facility_point';
  if (/hazard|灾害|风险点/.test(name)) return 'hazard_point';
  if (/axis|轴/.test(name)) return 'development_axis';
  if (/planned.?road|规划道路|推荐路线/.test(name)) return 'planned_road';
  if (/road|river|infra|道路|河流|基础设施/.test(name)) return 'infrastructure';
  if (/sensitivity|敏感/.test(name)) return 'sensitivity_zone';
  if (/isochrone|等时/.test(name)) return 'isochrone';
  if (/settlement|居民点/.test(name)) return 'settlement_zone';
  if (/planning|规划分区|空间功能分区/.test(name)) return 'planning_zone';
  return index === 0 ? 'boundary' : 'planning_zone';
}

export function normalizeGisLayer(raw: unknown, index = 0): GISLayerConfig | null {
  const value = parseMaybeJson(raw);
  if (!value || typeof value !== 'object') return null;
  const obj = value as Record<string, unknown>;
  const sourceGeojson = obj.geojson ?? obj.data ?? obj.featureCollection ?? obj.feature_collection ?? obj.features;
  const trustedGeojson = obj.crs === 'EPSG:4326'
    && sourceGeojson !== null
    && typeof sourceGeojson === 'object'
    && (sourceGeojson as Record<string, unknown>).type === 'FeatureCollection'
    && Array.isArray((sourceGeojson as Record<string, unknown>).features);
  // Generated results already carry a validated EPSG:4326 marker. Rebuilding
  // every nested coordinate array here (and again inside MapView) blocks the
  // browser for several seconds on the 660-parcel dataset.
  const geojson = trustedGeojson
    ? sourceGeojson as GeoJsonFeatureCollection
    : normalizeFeatureCollection(sourceGeojson);
  if (!geojson || geojson.features.length === 0) return null;

  const layerType = inferLayerType(obj, index);
  const layerName = String(
    obj.layerName ?? obj.layer_name ?? obj.name ?? `${layerType}_${index + 1}`,
  );

  const style = obj.style && typeof obj.style === 'object'
    ? (obj.style as GISLayerConfig['style'])
    : undefined;

  const path = obj.metadata && typeof obj.metadata === 'object' && !Array.isArray(obj.metadata)
    ? String((obj.metadata as Record<string, unknown>).path ?? '')
    : '';

  let displayGeojson = geojson;
  if (layerType === 'facility_point') {
    displayGeojson = {
      ...geojson,
      features: geojson.features
        .filter((feature) => !isJunkAnnotationFeature(feature))
        .map((feature) => {
          const properties = feature.properties || {};
          const normalized = normalizeFacilityLabel(properties);
          // Project annotations carry human-readable text instead of 注记.
          const text = String(properties.text ?? '').trim();
          if (text && !normalized.label) {
            return {
              ...feature,
              properties: {
                ...normalized,
                label: text,
                project_name: text,
                status: '规划新建',
              },
            };
          }
          return { ...feature, properties: normalized };
        }),
    };
  } else if (
    layerType === 'final_landuse'
    || layerType === 'function_zone'
    || layerName === 'landuse'
  ) {
    const displayRole = obj.metadata && typeof obj.metadata === 'object' && !Array.isArray(obj.metadata)
      ? String((obj.metadata as Record<string, unknown>).displayRole || '')
      : '';
    const skipLanduseNormalize = displayRole === 'control_reference' || displayRole === 'spatial_structure';
    displayGeojson = skipLanduseNormalize
      ? geojson
      : {
        ...geojson,
        features: geojson.features.map(normalizeLanduseFeature),
      };
  } else if (layerType === 'infrastructure') {
    displayGeojson = {
      ...geojson,
      features: geojson.features.map((feature) => normalizeInfrastructureFeature(feature, path)),
    };
  }

  return {
    geojson: displayGeojson,
    layerType,
    layerName,
    visible: typeof obj.visible === 'boolean' ? obj.visible : true,
    color: typeof obj.color === 'string' ? obj.color : undefined,
    standardCode: typeof obj.standardCode === 'string' ? obj.standardCode : undefined,
    standardName: typeof obj.standardName === 'string' ? obj.standardName : undefined,
    dataAuthority:
      typeof obj.dataAuthority === 'string'
        ? obj.dataAuthority as GISLayerConfig['dataAuthority']
        : undefined,
    requirement:
      typeof obj.requirement === 'string'
        ? obj.requirement as GISLayerConfig['requirement']
        : undefined,
    featureCount: displayGeojson.features.length,
    crs: typeof obj.crs === 'string' ? obj.crs : 'EPSG:4326',
    style,
    metadata: obj.metadata && typeof obj.metadata === 'object' && !Array.isArray(obj.metadata)
      ? obj.metadata as GISLayerConfig['metadata']
      : undefined,
  };
}

export function normalizeGisLayers(rawLayers: unknown): GISLayerConfig[] {
  if (!Array.isArray(rawLayers)) return [];
  return rawLayers
    .map((layer, index) => normalizeGisLayer(layer, index))
    .filter((layer): layer is GISLayerConfig => Boolean(layer));
}
