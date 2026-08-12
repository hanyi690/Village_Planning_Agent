import { useEffect, useRef } from 'react';
import { usePlanningStore } from '../store';
import { planningApi } from '../api';
import { normalizeV1MapLayers } from '../utils/gis-normalize';

/**
 * Fetches the authoritative v1 delivery + map-layers projections.
 *
 * Triggered when:
 * - a `delivery_ready` SSE event arrives (status flips to completed via store),
 * - the session reaches a terminal state (completed / failed),
 * - a `resync_required` event requests full REST recovery.
 *
 * The map renders from the DeliverySpatialSnapshot projection, not from
 * ad-hoc SSE deltas. A snapshot_checksum change replaces the layers wholesale.
 */
export function useDeliverySync() {
  const sessionId = usePlanningStore((state) => state.sessionId);
  const status = usePlanningStore((state) => state.status);
  const resyncRequired = usePlanningStore((state) => state.resyncRequired);
  const deliveryStatus = usePlanningStore((state) => state.delivery?.delivery_status);
  const lastChecksumRef = useRef<string | null>(null);

  useEffect(() => {
    // Only sync when we have a session and either a terminal state, a
    // delivery_ready signal, or a resync request.
    const isTerminal = status === 'completed' || status === 'failed';
    const deliveryReadyViaStatus =
      deliveryStatus === 'complete' ||
      deliveryStatus === 'partial' ||
      deliveryStatus === 'diagnostic_only';
    if (!sessionId || (!isTerminal && !deliveryReadyViaStatus && !resyncRequired)) {
      return;
    }

    const store = usePlanningStore.getState();
    let cancelled = false;

    (async () => {
      try {
        const [delivery, mapLayers] = await Promise.all([
          planningApi.getDelivery(sessionId),
          planningApi.getRenderLayers(sessionId).catch(() => null),
        ]);
        if (cancelled) return;

        store.setDelivery({
          available: delivery.available,
          delivery_status: delivery.delivery_status,
          statutory_complete: delivery.statutory_complete,
          snapshot_checksum: delivery.snapshot_checksum,
          deferral_summary: delivery.deferral_summary,
          diagnostic_summary: delivery.diagnostic_summary,
          deliverables: delivery.deliverables,
          downloads: delivery.downloads,
        });

        // Whole-snapshot replacement keyed by checksum.
        const checksum = delivery.snapshot_checksum || mapLayers?.snapshot_checksum || null;
        if (mapLayers?.layers?.length) {
          const layers = normalizeV1MapLayers(
            mapLayers.layers.map((layer) => ({
              layer_type: layer.layerType as 'current' | 'planned' | 'overlay' | 'constraint',
              layer_name: layer.layerName,
              geojson: layer.data,
            })),
          );
          if (layers.length > 0) {
            store.applyMapLayers(layers, checksum ?? undefined);
            lastChecksumRef.current = checksum;
          }
        }

        // Consumed the resync flag after a successful full REST recovery.
        if (resyncRequired) {
          store.setResyncRequired(false);
        }
      } catch (error) {
        console.warn('[useDeliverySync] Failed to fetch delivery projection:', error);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [sessionId, status, resyncRequired, deliveryStatus]);
}