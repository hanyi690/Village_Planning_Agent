import type { Draft } from 'immer';
import type { PlanningState, PlanningActions } from '../planningStore';

type StoreState = PlanningState & PlanningActions;

export type StoreSet = (
  partial:
    | StoreState
    | Partial<StoreState>
    | ((state: Draft<StoreState>) => void),
  replace?: boolean,
) => void;

export function createHistoryActions(
  set: StoreSet,
): Pick<
  PlanningActions,
  | 'setVillages'
  | 'setSelectedVillage'
  | 'setSelectedSession'
  | 'setHistoryLoading'
  | 'setHistoryError'
  | 'setCheckpoints'
  | 'setSelectedCheckpoint'
> {
  return {
    setVillages: (villages) =>
      set((state) => {
        state.villages = villages;
      }),

    setSelectedVillage: (village) =>
      set((state) => {
        state.selectedVillage = village;
        state.selectedSession = null;
      }),

    setSelectedSession: (session) =>
      set((state) => {
        state.selectedSession = session;
      }),

    setHistoryLoading: (loading) =>
      set((state) => {
        state.historyLoading = loading;
      }),

    setHistoryError: (error) =>
      set((state) => {
        state.historyError = error;
      }),

    setCheckpoints: (checkpoints) =>
      set((state) => {
        state.checkpoints = checkpoints;
      }),

    setSelectedCheckpoint: (checkpointId) =>
      set((state) => {
        state.selectedCheckpoint = checkpointId;
      }),
  };
}