'use client';

import React from 'react';
import { LayerCompletedMessage } from '../../types';

interface LayerReportMessageProps {
  message: LayerCompletedMessage;
}

function LayerReportMessage({ message }: LayerReportMessageProps) {
  const dimensionCount = Object.keys(message.dimensionReports || {}).length;

  return (
    <div className="flex justify-start mb-3">
      <div className="px-4 py-2 bg-emerald-50 border border-emerald-200 rounded-lg text-sm text-emerald-700">
        <span className="font-medium">Layer {message.layer}</span>
        <span className="text-emerald-500 mx-1">·</span>
        <span>{dimensionCount} 个维度已完成</span>
      </div>
    </div>
  );
}

export default React.memo(LayerReportMessage);