/** Persist workbench view / panel / analysis nav in the URL for refresh-safe navigation. */

export type WorkbenchView = 'overview' | 'drawings' | 'data';
export type OverviewPanel = 'task' | 'analysis' | 'document' | 'evaluation';

export interface WorkbenchNavState {
  view?: WorkbenchView;
  panel?: OverviewPanel;
  nav?: string | null;
}

const VALID_VIEWS = new Set<WorkbenchView>(['overview', 'drawings', 'data']);
const VALID_PANELS = new Set<OverviewPanel>(['task', 'analysis', 'document', 'evaluation']);

export function getWorkbenchNavFromUrl(): WorkbenchNavState {
  if (typeof window === 'undefined') return {};
  const params = new URL(window.location.href).searchParams;
  const view = params.get('view') as WorkbenchView | null;
  const panel = params.get('panel') as OverviewPanel | null;
  const nav = params.get('nav');
  return {
    view: view && VALID_VIEWS.has(view) ? view : undefined,
    panel: panel && VALID_PANELS.has(panel) ? panel : undefined,
    nav: nav || undefined,
  };
}

export function setWorkbenchNavInUrl(patch: WorkbenchNavState): void {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);

  if (patch.view !== undefined) {
    if (patch.view) url.searchParams.set('view', patch.view);
    else url.searchParams.delete('view');
  }
  if (patch.panel !== undefined) {
    if (patch.panel) url.searchParams.set('panel', patch.panel);
    else url.searchParams.delete('panel');
  }
  if (patch.nav !== undefined) {
    if (patch.nav) url.searchParams.set('nav', patch.nav);
    else url.searchParams.delete('nav');
  }

  window.history.replaceState({}, '', url.toString());
}

export function resolveDefaultWorkbenchNav(sessionId: string | null): {
  view: WorkbenchView;
  panel: OverviewPanel;
} {
  const fromUrl = getWorkbenchNavFromUrl();
  return {
    view: fromUrl.view ?? 'overview',
    panel: fromUrl.panel ?? (sessionId ? 'analysis' : 'task'),
  };
}
