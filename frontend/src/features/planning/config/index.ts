/**
 * Planning Feature Config
 *
 * Configuration constants for dimensions and planning phases.
 */

export {
  DIMENSION_NAMES,
  DIMENSION_ICONS,
  DIMENSIONS_BY_LAYER,
  getDimensionName,
  getDimensionIcon,
  getDimensionsByLayer,
  getDimensionConfigsByLayer,
} from './dimensions';

export {
  PLANNING_DEFAULTS,
  PARAM_MAPPING,
  type PlanningDefaults,
  type ParamMapping,
  getPlanningDefaults,
  getParamMapping,
  convertToBackendParams,
} from './phases';