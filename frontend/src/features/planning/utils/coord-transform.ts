import type { GeoJsonFeatureCollection, GeoJsonGeometry } from '@/types/message/message-types';

const PI = Math.PI;
const A = 6378245.0;
const EE = 0.006693421622965943;

function outOfChina(lon: number, lat: number): boolean {
  return !(lon > 73.66 && lon < 135.05 && lat > 3.86 && lat < 53.55);
}

function transformLat(x: number, y: number): number {
  let ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
  ret += (20.0 * Math.sin(6.0 * x * PI) + 20.0 * Math.sin(2.0 * x * PI)) * 2.0 / 3.0;
  ret += (20.0 * Math.sin(y * PI) + 40.0 * Math.sin(y / 3.0 * PI)) * 2.0 / 3.0;
  ret += (160.0 * Math.sin(y / 12.0 * PI) + 320 * Math.sin(y * PI / 30.0)) * 2.0 / 3.0;
  return ret;
}

function transformLon(x: number, y: number): number {
  let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  ret += (20.0 * Math.sin(6.0 * x * PI) + 20.0 * Math.sin(2.0 * x * PI)) * 2.0 / 3.0;
  ret += (20.0 * Math.sin(x * PI) + 40.0 * Math.sin(x / 3.0 * PI)) * 2.0 / 3.0;
  ret += (150.0 * Math.sin(x / 12.0 * PI) + 300.0 * Math.sin(x / 30.0 * PI)) * 2.0 / 3.0;
  return ret;
}

export function wgs84ToGcj02(lon: number, lat: number): [number, number] {
  if (outOfChina(lon, lat)) return [lon, lat];
  let dLat = transformLat(lon - 105.0, lat - 35.0);
  let dLon = transformLon(lon - 105.0, lat - 35.0);
  const radLat = lat / 180.0 * PI;
  let magic = Math.sin(radLat);
  magic = 1 - EE * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180.0) / (((A * (1 - EE)) / (magic * sqrtMagic)) * PI);
  dLon = (dLon * 180.0) / ((A / sqrtMagic) * Math.cos(radLat) * PI);
  return [lon + dLon, lat + dLat];
}

function transformCoordinateTuple(coord: number[]): number[] {
  if (coord.length < 2) return coord;
  const [lng, lat] = wgs84ToGcj02(coord[0], coord[1]);
  return coord.length === 2 ? [lng, lat] : [lng, lat, ...coord.slice(2)];
}

function transformCoordinates(coords: unknown): unknown {
  if (!Array.isArray(coords)) return coords;
  if (typeof coords[0] === 'number') {
    return transformCoordinateTuple(coords as number[]);
  }
  return coords.map((item) => transformCoordinates(item));
}

export function transformGeometryToGcj02(geometry: GeoJsonGeometry): GeoJsonGeometry {
  return {
    ...geometry,
    coordinates: transformCoordinates(geometry.coordinates) as GeoJsonGeometry['coordinates'],
  };
}

export function transformGeoJsonToGcj02(
  geojson: GeoJsonFeatureCollection,
): GeoJsonFeatureCollection {
  if (!geojson.features?.length) return geojson;
  return {
    ...geojson,
    features: geojson.features.map((feature) => ({
      ...feature,
      geometry: feature.geometry
        ? transformGeometryToGcj02(feature.geometry)
        : feature.geometry,
    })),
  };
}
