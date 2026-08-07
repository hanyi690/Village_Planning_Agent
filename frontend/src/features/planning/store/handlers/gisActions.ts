import type { Draft } from 'immer';
import type { GISLayerConfig } from '@/types/message/message-types';
import type { PlanningState, PlanningActions } from '../planningStore';

type StoreState = PlanningState & PlanningActions;

export type StoreSet = (
  partial:
    | StoreState
    | Partial<StoreState>
    | ((state: Draft<StoreState>) => void),
  replace?: boolean,
) => void;

export function createGisActions(
  set: StoreSet,
): Pick<
  PlanningActions,
  | 'addGisLayersFromUpload'
  | 'setFullMapOpen'
  | 'setUploadedGisDataTypes'
> {
  return {
    addGisLayersFromUpload: (configs) =>
      set((state) => {
        for (const cfg of configs) {
          const layers = cfg.layers as GISLayerConfig[] | undefined;
          if (!layers || layers.length === 0) continue;
          const key = `upload_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
          state.gisLayers[key] = layers;
        }
      }),

    setFullMapOpen: (open) =>
      set((state) => {
        state.isFullMapOpen = open;
      }),

    setUploadedGisDataTypes: (types) =>
      set((state) => {
        state.uploadedGisDataTypes = types;
      }),
  };
}