'use client';

/**
 * Dashboard - Demo System Main Layout
 *
 * Brutalist/Raw + Editorial Magazine aesthetic:
 * - Deep dark background (#0D0D0D)
 * - High contrast accent colors (#FF3D00, #00FFB3)
 * - Rough 2px borders, no rounded corners
 * - 30/70 split layout (dimensions left, map right)
 *
 * Features:
 * - Message panel slides in from right
 * - CascadePanel conditional render
 * - ChatInput fixed at bottom
 * - DimensionCard grid in left panel
 */

import React, { useState, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { faMessage, faMap, faPause, faPlay } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import '@fortawesome/fontawesome-svg-core/styles.css';

import { usePlanningStore, usePlanningActions } from '../store';
import {
  useStatus,
  useCurrentLayer,
  useIsPaused,
  useCascadeChain,
  useDimensionProgressAll,
  useExecutingDimensions,
  useCompletedLayers,
  useMessages,
} from '../hooks';
import MapView from './gis/MapView';
import DimensionCard from './DimensionCard';
import CascadePanel from './CascadePanel';
import MessagePanel from './MessagePanel';
import ChatInput from './ChatInput';

// Layer names for display
const LAYER_NAMES: Record<number, string> = {
  1: '现状分析',
  2: '规划布局',
  3: '详细方案',
};

// Wave names for display
const WAVE_NAMES: Record<number, string> = {
  1: 'Wave 1',
  2: 'Wave 2',
  3: 'Wave 3',
};

interface DashboardProps {
  onOpenLayerSidebar?: (layer: number) => void;
}

export default function Dashboard({ onOpenLayerSidebar }: DashboardProps) {
  // State
  const [messagePanelOpen, setMessagePanelOpen] = useState(false);
  const [mapVisible, setMapVisible] = useState(true);

  // Store
  const status = useStatus();
  const currentLayer = useCurrentLayer();
  const isPaused = useIsPaused();
  const cascadeChain = useCascadeChain();
  const dimensionProgress = useDimensionProgressAll();
  const executingDimensions = useExecutingDimensions();
  const completedLayers = useCompletedLayers();
  const messages = useMessages();
  const projectName = usePlanningStore((state) => state.projectName);
  const phase = usePlanningStore((state) => state.phase);
  const currentWave = usePlanningStore((state) => state.currentWave);
  const gisLayers = usePlanningStore((state) => state.gisLayers);
  const setPaused = usePlanningStore((state) => state.setPaused);

  // Handlers
  const handleToggleMessagePanel = useCallback(() => {
    setMessagePanelOpen((prev) => !prev);
  }, []);

  const handleToggleMap = useCallback(() => {
    setMapVisible((prev) => !prev);
  }, []);

  const handlePauseResume = useCallback(() => {
    if (isPaused) {
      setPaused(false);
      // TODO: Call resume API
    } else {
      setPaused(true);
      // TODO: Call pause API
    }
  }, [isPaused, setPaused]);

  // Progress calculation
  const progressPercent = useMemo(() => {
    if (!currentLayer) return 0;
    const layerProgress = Object.values(dimensionProgress).filter(
      (p) => p.layer === currentLayer && p.status === 'completed'
    ).length;
    const totalDimensions = Object.keys(dimensionProgress).filter(
      (k) => k.startsWith(`${currentLayer}_`)
    ).length;
    return totalDimensions > 0 ? (layerProgress / totalDimensions) * 100 : 0;
  }, [currentLayer, dimensionProgress]);

  // Get dimensions by layer
  const getDimensionsByLayer = useCallback(
    (layer: number) => {
      return Object.entries(dimensionProgress)
        .filter(([key]) => key.startsWith(`${layer}_`))
        .map(([key, item]) => ({ key, ...item }));
    },
    [dimensionProgress]
  );

  return (
    <div className="h-screen overflow-hidden bg-[#0D0D0D] font-sans">
      {/* ============================================ */}
      {/* Header - Brutalist Style */}
      {/* ============================================ */}
      <header className="fixed top-0 left-0 right-0 z-50 h-[60px] flex items-center justify-between px-4 bg-[#0D0D0D] border-b-2 border-[#333]">
        {/* Left: Project name & status */}
        <div className="flex items-center gap-4">
          <h1 className="font-display text-lg text-[#00FFB3] tracking-tight">
            {projectName || '村庄规划'}
          </h1>
          <div className="flex items-center gap-2 px-3 py-1 border-2 border-[#333] bg-[#1A1A1A]">
            <span className="text-xs text-[#666] uppercase">
              {phase?.toUpperCase() || 'IDLE'}
            </span>
            {currentWave > 1 && (
              <span className="text-xs text-[#00FFB3]">{WAVE_NAMES[currentWave]}</span>
            )}
          </div>
        </div>

        {/* Center: Progress bar */}
        <div className="flex-1 max-w-[300px] mx-4">
          <div className="flex items-center gap-2">
            <div className="flex-1 h-2 bg-[#1A1A1A] border border-[#333]">
              <motion.div
                className="h-full bg-[#00FFB3]"
                initial={{ width: 0 }}
                animate={{ width: `${progressPercent}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
            <span className="text-xs text-[#666] font-mono">{Math.round(progressPercent)}%</span>
          </div>
          {currentLayer && (
            <div className="text-xs text-[#888] mt-1">
              Layer {currentLayer}: {LAYER_NAMES[currentLayer]}
            </div>
          )}
        </div>

        {/* Right: Action buttons */}
        <div className="flex items-center gap-2">
          {/* Pause/Resume */}
          {status !== 'idle' && (
            <button
              onClick={handlePauseResume}
              className={`flex items-center gap-2 px-3 py-2 border-2 ${
                isPaused
                  ? 'border-[#FF3D00] bg-[#FF3D00]/20 text-[#FF3D00]'
                  : 'border-[#333] bg-[#1A1A1A] text-[#888]'
              } hover:border-[#FF3D00] transition-colors`}
            >
              <FontAwesomeIcon icon={isPaused ? faPlay : faPause} style={{ width: 12, height: 12 }} />
              <span className="text-sm">{isPaused ? '继续' : '暂停'}</span>
            </button>
          )}

          {/* Message toggle */}
          <button
            onClick={handleToggleMessagePanel}
            className={`flex items-center gap-2 px-3 py-2 border-2 ${
              messagePanelOpen
                ? 'border-[#00FFB3] bg-[#00FFB3]/20 text-[#00FFB3]'
                : 'border-[#333] bg-[#1A1A1A] text-[#888]'
            } hover:border-[#00FFB3] transition-colors`}
          >
            <FontAwesomeIcon icon={faMessage} style={{ width: 12, height: 12 }} />
            <span className="text-sm">消息</span>
          </button>

          {/* Map toggle */}
          <button
            onClick={handleToggleMap}
            className={`flex items-center gap-2 px-3 py-2 border-2 ${
              mapVisible
                ? 'border-[#333] bg-[#1A1A1A] text-[#888]'
                : 'border-[#FF3D00] bg-[#FF3D00]/20 text-[#FF3D00]'
            } hover:border-[#00FFB3] transition-colors`}
          >
            <FontAwesomeIcon icon={faMap} style={{ width: 12, height: 12 }} />
            <span className="text-sm">地图</span>
          </button>
        </div>
      </header>

      {/* ============================================ */}
      {/* Main Content - 30/70 Split */}
      {/* ============================================ */}
      <main className="pt-[60px] pb-[60px] h-full flex">
        {/* Left Panel (30%): Dimensions */}
        <div className="w-[30%] h-full bg-[#0D0D0D] border-r-2 border-[#333] overflow-y-auto">
          {/* Layer Sections */}
          {[1, 2, 3].map((layer) => {
            const dimensions = getDimensionsByLayer(layer);
            const isCompleted = completedLayers[layer as 1 | 2 | 3];
            const isCurrent = currentLayer === layer;

            // Skip empty layers
            if (dimensions.length === 0 && !isCurrent) return null;

            return (
              <div key={layer} className="mb-4">
                {/* Layer Header */}
                <div
                  className={`px-4 py-2 border-b-2 ${
                    isCurrent ? 'border-[#00FFB3] bg-[#00FFB3]/10' : 'border-[#333] bg-[#1A1A1A]'
                  }`}
                >
                  <h2 className="font-display text-sm uppercase tracking-wider">
                    <span className={isCurrent ? 'text-[#00FFB3]' : 'text-[#888]'}>
                      LAYER {layer}
                    </span>
                    <span className="text-[#666] ml-2">- {LAYER_NAMES[layer]}</span>
                    {isCompleted && (
                      <span className="text-[#00FFB3] ml-2 text-xs">DONE</span>
                    )}
                  </h2>
                </div>

                {/* Dimension Cards */}
                <div className="px-2 py-2 space-y-1">
                  {dimensions.map((dim) => (
                    <DimensionCard
                      key={dim.key}
                      dimensionKey={dim.key}
                      dimensionName={dim.dimensionName}
                      layer={dim.layer}
                      status={dim.status}
                      wordCount={dim.wordCount}
                      isExecuting={executingDimensions.includes(dim.key)}
                      isRevision={dim.isRevision}
                      onOpenLayerSidebar={onOpenLayerSidebar}
                    />
                  ))}

                  {/* Show placeholder for current layer if no dimensions yet */}
                  {isCurrent && dimensions.length === 0 && (
                    <div className="px-4 py-3 text-[#666] text-sm border-2 border-[#333] bg-[#1A1A1A]">
                      等待维度分析开始...
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Right Panel (70%): Map */}
        <AnimatePresence>
          {mapVisible && (
            <motion.div
              className="w-[70%] h-full bg-[#1A1A1A] border-l-2 border-[#333]"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              transition={{ duration: 0.3 }}
            >
              {/* Get layers from current dimension or all layers */}
              {currentLayer && gisLayers && Object.keys(gisLayers).length > 0 ? (
                <MapView
                  height="100%"
                  layers={Object.values(gisLayers).flat() as any[]}
                  showLegend={true}
                  legendPosition="bottom-right"
                />
              ) : (
                <div className="h-full w-full flex items-center justify-center text-[#666]">
                  <span className="text-sm">等待GIS数据加载...</span>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {/* ============================================ */}
      {/* CascadePanel - Conditional Render */}
      {/* ============================================ */}
      <AnimatePresence>
        {cascadeChain && (
          <motion.div
            className="fixed bottom-[60px] left-0 right-0 z-40"
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            transition={{ duration: 0.3 }}
          >
            <CascadePanel
              trigger={cascadeChain.trigger}
              impacted={cascadeChain.impacted}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {/* ============================================ */}
      {/* MessagePanel - Slide from Right */}
      {/* ============================================ */}
      <AnimatePresence>
        {messagePanelOpen && (
          <motion.div
            className="fixed top-[60px] right-0 bottom-[60px] w-[40%] z-40 bg-[#0D0D0D] border-l-2 border-[#333]"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ duration: 0.3, ease: 'easeOut' }}
          >
            <MessagePanel
              messages={messages}
              onClose={() => setMessagePanelOpen(false)}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {/* ============================================ */}
      {/* ChatInput - Fixed Bottom */}
      {/* ============================================ */}
      <div className="fixed bottom-0 left-0 right-0 h-[60px] bg-[#0D0D0D] border-t-2 border-[#333]">
        <ChatInput
          disabled={status === 'idle'}
          onSend={(message) => {
            // TODO: Implement send message
            console.log('Send message:', message);
          }}
        />
      </div>
    </div>
  );
}