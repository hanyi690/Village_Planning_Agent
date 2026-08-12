'use client';

import type { CSSProperties, ReactNode } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import type { IconDefinition } from '@fortawesome/fontawesome-svg-core';
import {
  faBook,
  faBuilding,
  faChartBar,
  faChartPie,
  faCheck,
  faCircleCheck,
  faClipboardList,
  faCubes,
  faDrawPolygon,
  faLayerGroup,
  faLocationDot,
  faMap,
  faMapLocationDot,
  faRoad,
  faRoute,
  faShareNodes,
  faShieldHalved,
  faTags,
  faTree,
  faWandMagicSparkles,
} from '@fortawesome/free-solid-svg-icons';

export const WORKBENCH_METRIC_ICONS = {
  spatialFeatures: faCubes,
  entityTypes: faTags,
  currentParcels: faDrawPolygon,
  plannedParcels: faMap,
  constraints: faShieldHalved,
  roads: faRoad,
  kgConstraints: faShareNodes,
  roadCandidates: faRoute,
  validation: faCircleCheck,
} as const;

export const SIDEBAR_NAV_ICONS: Record<string, IconDefinition> = {
  'overview-task': faClipboardList,
  'overview-analysis': faChartPie,
  'overview-document': faBook,
  'overview-evaluation': faWandMagicSparkles,
  drawings: faMap,
  'data-kg': faShareNodes,
  'data-metrics': faChartBar,
  'data-compliance': faShieldHalved,
  'data-suitability': faMapLocationDot,
};

export const LAYER_FILTER_ICONS: Record<string, IconDefinition> = {
  all: faLayerGroup,
  current: faTree,
  planning: faBuilding,
  constraints: faShieldHalved,
  roads: faRoad,
};

export const QUICK_LAYER_GROUP_ICONS: Record<string, IconDefinition> = {
  现状: faTree,
  规划: faBuilding,
  约束: faShieldHalved,
};

export const SPATIAL_RELATIONS = [
  {
    key: '邻近',
    label: '邻近',
    color: '#9b59b6',
    activeBg: '#f1e9f8',
    activeBorder: '#9a6bc0',
    activeText: '#7d4ba5',
  },
  {
    key: '相邻',
    label: '相邻',
    color: '#2ecc71',
    activeBg: '#e8f8ef',
    activeBorder: '#5ecb85',
    activeText: '#249653',
  },
  {
    key: '包含',
    label: '包含',
    color: '#e74c3c',
    activeBg: '#fdeeed',
    activeBorder: '#e58f86',
    activeText: '#c0392b',
  },
  {
    key: '相交',
    label: '相交',
    color: '#f1c40f',
    activeBg: '#fff8e1',
    activeBorder: '#e8c547',
    activeText: '#9a7b0a',
  },
  {
    key: '道路连接',
    label: '道路连接',
    color: '#3498db',
    activeBg: '#eaf4fc',
    activeBorder: '#7eb8e3',
    activeText: '#2471a3',
  },
] as const;

export type SpatialRelationKey = (typeof SPATIAL_RELATIONS)[number]['key'];

export interface EntityBrowserEntry {
  name: string;
  code: string;
  icon: IconDefinition;
  iconColor: string;
}

export const ENTITY_BROWSER_CURRENT: EntityBrowserEntry[] = [
  { name: '现状地块', code: 'Parcel', icon: faDrawPolygon, iconColor: '#2d8c6d' },
  { name: '现状道路', code: 'Road', icon: faRoad, iconColor: '#8b6914' },
  { name: '管控约束', code: 'Zone', icon: faShieldHalved, iconColor: '#c0392b' },
  { name: '设施与标注', code: 'Facility', icon: faLocationDot, iconColor: '#27ae60' },
];

export const ENTITY_BROWSER_PLANNED: EntityBrowserEntry[] = [
  { name: '规划地块', code: 'PlannedParcel', icon: faMap, iconColor: '#2980b9' },
  { name: '既有规划道路', code: 'PlannedRoad', icon: faRoute, iconColor: '#8e44ad' },
  { name: 'Stage5 道路', code: 'RecommendedRoad', icon: faRoad, iconColor: '#e67e22' },
];

export const WORKBENCH_BRAND_ICON = faMapLocationDot;
export const PANEL_TITLE_ICON = faLayerGroup;

export function WorkbenchIcon({
  icon,
  className,
  style,
}: {
  icon: IconDefinition;
  className?: string;
  style?: CSSProperties;
}) {
  if (!icon || !icon.iconName) {
    return (
      <span
        className={className}
        style={{ width: '1em', height: '1em', display: 'inline-block', ...style }}
        aria-hidden
      />
    );
  }
  return (
    <FontAwesomeIcon
      icon={icon}
      className={className}
      style={{ width: '1em', height: '1em', ...style }}
    />
  );
}

export function RelationDot({ color, className }: { color: string; className?: string }) {
  return (
    <span
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${className ?? ''}`}
      style={{ backgroundColor: color }}
      aria-hidden
    />
  );
}

export function EntityBrowserRow({
  entry,
  count,
}: {
  entry: EntityBrowserEntry;
  count: number;
}) {
  return (
    <div className="flex items-center gap-2 py-1.5">
      <span
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[#f2f8f5] text-[11px]"
        style={{ color: entry.iconColor }}
      >
        <WorkbenchIcon icon={entry.icon} />
      </span>
      <span className="min-w-0 flex-1 truncate text-[#3e5e54]">{entry.name}</span>
      <span className="mr-2 shrink-0 text-[10px] text-[#9bb0a8]">{entry.code}</span>
      <b className="shrink-0 rounded-full bg-[#e4f5ed] px-2 py-0.5 text-[#36906e]">{count}</b>
    </div>
  );
}

export function getSpatialRelation(key: string) {
  return SPATIAL_RELATIONS.find((relation) => relation.key === key) ?? SPATIAL_RELATIONS[0];
}

export function renderLayerDoneIcon(done: boolean, layer: number): ReactNode {
  if (done) {
    return <WorkbenchIcon icon={faCheck} className="text-[9px]" />;
  }
  return layer;
}
