'use client';

import { useState, FormEvent } from 'react';

export interface VillageInputData {
  projectName: string;
  taskDescription: string;
  constraints: string;
}

interface VillageInputFormProps {
  onSubmit: (data: VillageInputData) => void;
}

export default function VillageInputForm({ onSubmit }: VillageInputFormProps) {
  const [projectName, setProjectName] = useState('');
  const [taskDescription, setTaskDescription] = useState('');
  const [constraints, setConstraints] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();

    if (!projectName.trim()) {
      // 可以替换为更优雅的提示方式
      const nameInput = document.getElementById('projectName');
      nameInput?.focus();
      return;
    }

    setIsSubmitting(true);
    onSubmit({
      projectName: projectName.trim(),
      taskDescription: taskDescription.trim(),
      constraints: constraints.trim(),
    });
  };

  return (
    <div className="min-h-[calc(100vh-56px)] flex items-center justify-center p-4 bg-gradient-mesh">
      {/* Decorative background elements */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-green-500/5 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-blue-500/5 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-xl animate-scale-in">
        {/* Main form card */}
        <div className="bg-[#1a1a1a]/90 backdrop-blur-xl border border-[#2d2d2d] rounded-3xl shadow-2xl overflow-hidden">
          
          {/* Header with gradient accent */}
          <div className="relative px-6 py-8 text-center border-b border-[#2d2d2d]">
            <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-green-500 via-green-400 to-cyan-500" />
            
            {/* Icon */}
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-green-500/20 to-green-600/10 border border-green-500/30 mb-4">
              <svg className="w-8 h-8 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            
            <h2 className="text-2xl font-bold text-white mb-2">
              创建规划任务
            </h2>
            <p className="text-zinc-400 text-sm">
              请填写以下基础信息，AI 助手将为您生成定制化方案
            </p>
          </div>

          {/* Form body */}
          <form onSubmit={handleSubmit} className="p-6 space-y-6">
            
            {/* Village Name */}
            <div className="space-y-2">
              <label htmlFor="projectName" className="flex items-center gap-2 text-sm font-medium text-zinc-300">
                <svg className="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                村庄名称 <span className="text-red-400">*</span>
              </label>
              <input
                id="projectName"
                type="text"
                className="w-full bg-[#242424] border border-[#3f3f46] rounded-xl px-4 py-3 text-white placeholder-zinc-500 focus:outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20 transition-all duration-200"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="例如：杭州市余杭区李家村"
                required
              />
            </div>

            {/* Task Description */}
            <div className="space-y-2">
              <label htmlFor="taskDescription" className="flex items-center gap-2 text-sm font-medium text-zinc-300">
                <svg className="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
                任务描述
              </label>
              <textarea
                id="taskDescription"
                rows={4}
                className="w-full bg-[#242424] border border-[#3f3f46] rounded-xl px-4 py-3 text-white placeholder-zinc-500 focus:outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20 transition-all duration-200 resize-none"
                value={taskDescription}
                onChange={(e) => setTaskDescription(e.target.value)}
                placeholder="请描述本次规划的主要目标、重点改造区域以及发展愿景..."
              />
            </div>

            {/* Constraints */}
            <div className="space-y-2">
              <label htmlFor="constraints" className="flex items-center gap-2 text-sm font-medium text-zinc-300">
                <svg className="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                </svg>
                约束条件
              </label>
              <textarea
                id="constraints"
                rows={3}
                className="w-full bg-[#242424] border border-[#3f3f46] rounded-xl px-4 py-3 text-white placeholder-zinc-500 focus:outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20 transition-all duration-200 resize-none"
                value={constraints}
                onChange={(e) => setConstraints(e.target.value)}
                placeholder="例如：预算需控制在 500 万以内；保留村口百年古树..."
              />
            </div>

            {/* Submit Button */}
            <div className="pt-4">
              <button
                type="submit"
                disabled={isSubmitting}
                className="relative w-full group flex items-center justify-center gap-3 px-6 py-4 bg-gradient-to-r from-green-600 to-green-500 hover:from-green-500 hover:to-green-400 text-white font-semibold rounded-xl transition-all duration-300 shadow-lg shadow-green-500/25 hover:shadow-green-500/40 disabled:opacity-70 disabled:cursor-not-allowed overflow-hidden"
              >
                {/* Shine effect */}
                <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent -translate-x-full group-hover:translate-x-full transition-transform duration-700" />
                
                <span className="relative z-10">
                  {isSubmitting ? '正在创建...' : '开始规划'}
                </span>
                
                {/* Arrow icon */}
                <svg className="relative z-10 w-5 h-5 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                </svg>
              </button>
            </div>

          </form>

          {/* Footer hint */}
          <div className="px-6 py-4 border-t border-[#2d2d2d] bg-[#151515]/50">
            <p className="text-xs text-zinc-500 text-center">
              💡 提示：描述越详细，AI 生成的规划方案将越精准
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}