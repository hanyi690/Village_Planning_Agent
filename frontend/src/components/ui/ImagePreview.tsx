'use client';

/**
 * ImagePreview - 图片预览组件
 * 支持全尺寸图片显示、缩放/平移控制、Lightbox 模式弹窗
 */

import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faTimes,
  faSearchPlus,
  faSearchMinus,
  faExpand,
  faUndo,
} from '@fortawesome/free-solid-svg-icons';

interface ImagePreviewProps {
  imageBase64: string;
  imageFormat: string;
  filename: string;
  thumbnailBase64?: string;
  imageWidth?: number;
  imageHeight?: number;
  className?: string;
}

export default function ImagePreview({
  imageBase64,
  imageFormat,
  filename,
  imageWidth,
  imageHeight,
  className = '',
}: ImagePreviewProps) {
  const [isLightboxOpen, setIsLightboxOpen] = useState(false);
  const [scale, setScale] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const imageRef = useRef<HTMLImageElement>(null);

  // Construct image data URI (memoized to avoid recalculation on every render)
  const imageSrc = useMemo(
    () => `data:image/${imageFormat};base64,${imageBase64}`,
    [imageFormat, imageBase64]
  );

  // Format dimensions display
  const dimensionsDisplay = useMemo(
    () => (imageWidth && imageHeight ? `${imageWidth} x ${imageHeight}` : ''),
    [imageWidth, imageHeight]
  );

  // Reset state when closing lightbox
  const closeLightbox = useCallback(() => {
    setIsLightboxOpen(false);
    setScale(1);
    setPosition({ x: 0, y: 0 });
  }, []);

  // Handle keyboard events for lightbox
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isLightboxOpen) return;
      if (e.key === 'Escape') closeLightbox();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isLightboxOpen, closeLightbox]);

  // Zoom controls
  const handleZoomIn = () => setScale((s) => Math.min(s * 1.5, 5));
  const handleZoomOut = () => setScale((s) => Math.max(s / 1.5, 0.5));
  const handleResetZoom = () => {
    setScale(1);
    setPosition({ x: 0, y: 0 });
  };

  // Drag handlers for panning
  const handleDragStart = (e: React.MouseEvent) => {
    if (scale <= 1) return;
    setIsDragging(true);
    dragStart.current = {
      x: e.clientX - position.x,
      y: e.clientY - position.y,
    };
  };

  const handleDragMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    setPosition({
      x: e.clientX - dragStart.current.x,
      y: e.clientY - dragStart.current.y,
    });
  };

  const handleDragEnd = () => setIsDragging(false);

  return (
    <>
      {/* Thumbnail / Preview in sidebar */}
      <div className={`relative group ${className}`}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          ref={imageRef}
          src={imageSrc}
          alt={filename}
          className="w-full h-auto rounded-lg shadow-sm cursor-pointer transition-transform hover:scale-[1.02]"
          onClick={() => setIsLightboxOpen(true)}
          loading="lazy"
        />

        {/* Metadata overlay */}
        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent px-3 py-2 rounded-b-lg opacity-0 group-hover:opacity-100 transition-opacity">
          <p className="text-white text-sm font-medium truncate">{filename}</p>
          {dimensionsDisplay && (
            <p className="text-white/80 text-xs">{dimensionsDisplay}</p>
          )}
        </div>

        {/* Expand button */}
        <motion.button
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.9 }}
          onClick={() => setIsLightboxOpen(true)}
          className="absolute top-2 right-2 w-8 h-8 bg-white/90 rounded-full flex items-center justify-center shadow-md opacity-0 group-hover:opacity-100 transition-opacity"
          title="打开大图"
        >
          <FontAwesomeIcon icon={faExpand} className="text-gray-700" />
        </motion.button>
      </div>

      {/* Lightbox Modal */}
      <AnimatePresence>
        {isLightboxOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/90 z-[10000] flex flex-col"
            onClick={closeLightbox}
          >
            {/* Header */}
            <div
              className="flex justify-between items-center px-4 py-3 bg-black/50"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="text-white">
                <p className="font-medium">{filename}</p>
                {dimensionsDisplay && (
                  <p className="text-sm text-white/70">{dimensionsDisplay}</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {/* Zoom controls */}
                <motion.button
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                  onClick={handleZoomOut}
                  className="w-8 h-8 bg-white/20 rounded-full flex items-center justify-center text-white hover:bg-white/30"
                  title="缩小"
                >
                  <FontAwesomeIcon icon={faSearchMinus} />
                </motion.button>
                <span className="text-white text-sm w-12 text-center">
                  {Math.round(scale * 100)}%
                </span>
                <motion.button
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                  onClick={handleZoomIn}
                  className="w-8 h-8 bg-white/20 rounded-full flex items-center justify-center text-white hover:bg-white/30"
                  title="放大"
                >
                  <FontAwesomeIcon icon={faSearchPlus} />
                </motion.button>
                <motion.button
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                  onClick={handleResetZoom}
                  className="w-8 h-8 bg-white/20 rounded-full flex items-center justify-center text-white hover:bg-white/30"
                  title="重置"
                >
                  <FontAwesomeIcon icon={faUndo} />
                </motion.button>
                {/* Close button */}
                <motion.button
                  whileHover={{ scale: 1.1, rotate: 90 }}
                  whileTap={{ scale: 0.9 }}
                  onClick={closeLightbox}
                  className="w-8 h-8 bg-white/20 rounded-full flex items-center justify-center text-white hover:bg-white/30 ml-2"
                  title="关闭"
                >
                  <FontAwesomeIcon icon={faTimes} />
                </motion.button>
              </div>
            </div>

            {/* Image container */}
            <div
              className="flex-1 flex items-center justify-center overflow-hidden"
              onMouseDown={handleDragStart}
              onMouseMove={handleDragMove}
              onMouseUp={handleDragEnd}
              onMouseLeave={handleDragEnd}
              onClick={(e) => e.stopPropagation()}
              style={{ cursor: scale > 1 ? (isDragging ? 'grabbing' : 'grab') : 'default' }}
            >
              <motion.img
                src={imageSrc}
                alt={filename}
                className="max-w-full max-h-full object-contain select-none"
                style={{
                  transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
                  transition: isDragging ? 'none' : 'transform 0.1s ease-out',
                }}
                draggable={false}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}