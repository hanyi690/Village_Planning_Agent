/**
 * GIS Data Verification Utilities for E2E tests.
 *
 * Validates GISLayerConfig structure, GeoJSON compliance,
 * coordinate bounds, and layer type enumeration.
 */

// ── Types ────────────────────────────────────────────────────────────

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

export const EXPECTED_LAYER_TYPES = [
  'boundary',
  'infrastructure',
  'planned_road',
  'sensitivity_zone',
  'function_zone',
  'planning_zone',
  'isochrone',
  'development_axis',
  'facility_point',
] as const;

export type LayerType = (typeof EXPECTED_LAYER_TYPES)[number];

const VALID_GEOMETRY_TYPES = new Set([
  'Point',
  'MultiPoint',
  'LineString',
  'MultiLineString',
  'Polygon',
  'MultiPolygon',
]);

// ── GisVerifier ──────────────────────────────────────────────────────

export class GisVerifier {
  /** Validate a single GISLayerConfig object. */
  static validateLayerConfig(layer: any): ValidationResult {
    const errors: string[] = [];

    if (!layer) {
      return { valid: false, errors: ['Layer is null/undefined'] };
    }

    if (!layer.layerType || typeof layer.layerType !== 'string') {
      errors.push('Missing or invalid layerType');
    } else if (!EXPECTED_LAYER_TYPES.includes(layer.layerType)) {
      errors.push(`Unknown layerType: ${layer.layerType}`);
    }

    if (!layer.layerName || typeof layer.layerName !== 'string') {
      errors.push('Missing or invalid layerName');
    }

    if (!layer.geojson) {
      errors.push('Missing geojson');
    } else {
      const geoResult = GisVerifier.validateGeoJSON(layer.geojson);
      if (!geoResult.valid) {
        errors.push(...geoResult.errors.map((e) => `geojson: ${e}`));
      }
    }

    // color is optional but if present must be valid
    if (layer.color !== undefined && typeof layer.color !== 'string') {
      errors.push('Invalid color (must be string)');
    }

    return { valid: errors.length === 0, errors };
  }

  /** Validate GeoJSON FeatureCollection structure. */
  static validateGeoJSON(geojson: any): ValidationResult {
    const errors: string[] = [];

    if (!geojson) {
      return { valid: false, errors: ['GeoJSON is null/undefined'] };
    }

    if (geojson.type !== 'FeatureCollection') {
      errors.push(`Expected type=FeatureCollection, got type=${geojson.type}`);
    }

    if (!Array.isArray(geojson.features)) {
      errors.push('Missing or invalid features array');
      return { valid: false, errors };
    }

    // Validate each feature
    for (let i = 0; i < geojson.features.length; i++) {
      const feature = geojson.features[i];
      const featErrors = GisVerifier.validateFeature(feature, i);
      errors.push(...featErrors);
    }

    return { valid: errors.length === 0, errors };
  }

  /** Validate a single GeoJSON feature. */
  static validateFeature(feature: any, index: number): string[] {
    const errors: string[] = [];
    const prefix = `feature[${index}]`;

    if (!feature) {
      return [`${prefix}: null/undefined`];
    }

    if (feature.type !== 'Feature') {
      errors.push(`${prefix}: expected type=Feature, got type=${feature.type}`);
    }

    if (!feature.geometry) {
      errors.push(`${prefix}: missing geometry`);
    } else {
      if (!VALID_GEOMETRY_TYPES.has(feature.geometry.type)) {
        errors.push(`${prefix}: invalid geometry type=${feature.geometry.type}`);
      } else {
        const coordErrors = GisVerifier.validateCoordinateBounds(feature.geometry);
        for (const e of coordErrors) {
          errors.push(`${prefix}: ${e}`);
        }
      }
    }

    // properties is optional but recommended
    if (feature.properties === undefined) {
      errors.push(`${prefix}: missing properties (recommended)`);
    }

    return errors;
  }

  /** Validate coordinate bounds in a geometry object. */
  static validateCoordinateBounds(geometry: any): string[] {
    const errors: string[] = [];

    if (!geometry || !geometry.coordinates) {
      return ['Missing coordinates'];
    }

    const coords = GisVerifier._flattenCoordinates(geometry.coordinates);
    for (let i = 0; i < coords.length; i += 2) {
      const lon = coords[i];
      const lat = coords[i + 1];
      if (typeof lon !== 'number' || typeof lat !== 'number') {
        errors.push(`Invalid coordinate at index ${i / 2}: [${lon}, ${lat}]`);
        continue;
      }
      if (lon < -180 || lon > 180) {
        errors.push(`Longitude out of range: ${lon}`);
      }
      if (lat < -90 || lat > 90) {
        errors.push(`Latitude out of range: ${lat}`);
      }
    }

    return errors;
  }

  /** Validate that a layers array contains expected layer types. */
  static validateLayerTypes(layers: any[]): ValidationResult {
    const errors: string[] = [];

    if (!Array.isArray(layers) || layers.length === 0) {
      return { valid: false, errors: ['Layers array is empty or not an array'] };
    }

    const presentTypes = new Set(layers.map((l) => l.layerType));

    for (const expected of EXPECTED_LAYER_TYPES) {
      if (!presentTypes.has(expected)) {
        errors.push(`Missing layer type: ${expected}`);
      }
    }

    return { valid: errors.length === 0, errors };
  }

  /** Get the list of expected layer types. */
  static getExpectedLayerTypes(): string[] {
    return [...EXPECTED_LAYER_TYPES];
  }

  /** Build a layers map keyed by layerType from a GISLayerConfig array. */
  static buildLayersMap(layers: any[]): Record<string, any> {
    const map: Record<string, any> = {};
    for (const layer of layers) {
      if (layer.layerType && layer.geojson) {
        map[layer.layerType] = layer.geojson;
      }
    }
    return map;
  }

  // ── Private ──

  /** Recursively flatten coordinate arrays to [lon, lat, lon, lat, ...]. */
  private static _flattenCoordinates(coords: any[]): number[] {
    const result: number[] = [];

    function walk(arr: any[]): void {
      for (const item of arr) {
        if (Array.isArray(item)) {
          if (typeof item[0] === 'number') {
            // This is a coordinate pair [lon, lat, ...]
            result.push(item[0], item[1]);
          } else {
            // Nested array
            walk(item);
          }
        }
      }
    }

    walk(coords);
    return result;
  }
}
