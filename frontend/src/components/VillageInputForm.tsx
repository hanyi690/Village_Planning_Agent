'use client';

import { useState, FormEvent } from 'react';
import { motion } from 'framer-motion';

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
  const [focusedField, setFocusedField] = useState<string | null>(null);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();

    if (!projectName.trim()) {
      alert('请输入村庄名称');
      return;
    }

    onSubmit({
      projectName: projectName.trim(),
      taskDescription: taskDescription.trim(),
      constraints: constraints.trim(),
    });
  };

  // Animation variants
  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.1,
        delayChildren: 0.2,
      },
    },
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: {
      opacity: 1,
      y: 0,
      transition: {
        type: 'spring' as const,
        stiffness: 100,
        damping: 12,
      },
    },
  };

  const InputField = ({
    id,
    label,
    icon,
    required,
    value,
    onChange,
    placeholder,
    isTextarea = false,
    rows = 3,
  }: {
    id: string;
    label: string;
    icon: string;
    required?: boolean;
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
    isTextarea?: boolean;
    rows?: number;
  }) => {
    const isFocused = focusedField === id;

    return (
      <motion.div variants={itemVariants} className="w-full">
        <label
          htmlFor={id}
          className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2"
        >
          <span>{icon}</span>
          {label}
          {required && <span className="text-red-400">*</span>}
        </label>
        <div className="relative group">
          {isTextarea ? (
            <textarea
              id={id}
              rows={rows}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onFocus={() => setFocusedField(id)}
              onBlur={() => setFocusedField(null)}
              placeholder={placeholder}
              className="w-full px-4 py-3 bg-emerald-50/30 border-0 rounded-2xl text-gray-900 placeholder-gray-500 resize-none transition-all duration-300 focus:bg-white focus:ring-2 focus:ring-emerald-500/20 focus:shadow-[0_0_0_4px_rgba(16,185,129,0.1)]"
            />
          ) : (
            <input
              id={id}
              type="text"
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onFocus={() => setFocusedField(id)}
              onBlur={() => setFocusedField(null)}
              placeholder={placeholder}
              className="w-full px-4 py-3.5 bg-emerald-50/30 border-0 rounded-2xl text-gray-900 placeholder-gray-500 transition-all duration-300 focus:bg-white focus:ring-2 focus:ring-emerald-500/20 focus:shadow-[0_0_0_4px_rgba(16,185,129,0.1)]"
            />
          )}
          {/* 底部渐变线 */}
          <div
            className={`absolute bottom-0 left-4 right-4 h-0.5 rounded-full transition-all duration-300 ${
              isFocused
                ? 'bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500 opacity-100'
                : 'opacity-0'
            }`}
          />
        </div>
      </motion.div>
    );
  };

  return (
    <div className="w-full min-h-[80vh] flex items-center justify-center p-4 bg-gradient-to-b from-emerald-50/50 to-white">
      <motion.form
        onSubmit={handleSubmit}
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="w-full max-w-xl"
      >
        {/* 渐变欢迎标题 */}
        <motion.div variants={itemVariants} className="text-center mb-8">
          <h1 className="text-3xl sm:text-4xl font-bold mb-3">
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-600 via-teal-500 to-cyan-600">
              规划新村庄
            </span>
          </h1>
          <p className="text-gray-500 text-sm sm:text-base">
            填写基础信息，AI 助手将为您生成定制化规划方案
          </p>
        </motion.div>

        {/* 表单卡片 */}
        <motion.div
          variants={itemVariants}
          className="bg-white rounded-3xl shadow-xl shadow-gray-200/50 border border-gray-100 p-6 sm:p-8"
        >
          {/* 表单字段 */}
          <div className="space-y-6">
            <InputField
              id="projectName"
              label="村庄名称"
              icon="📍"
              required
              value={projectName}
              onChange={setProjectName}
              placeholder="例如：杭州市余杭区李家村"
            />

            <InputField
              id="taskDescription"
              label="任务描述"
              icon="📝"
              value={taskDescription}
              onChange={setTaskDescription}
              placeholder="请描述本次规划的主要目标、重点改造区域以及发展愿景..."
              isTextarea
              rows={4}
            />

            <InputField
              id="constraints"
              label="约束条件"
              icon="⚙️"
              value={constraints}
              onChange={setConstraints}
              placeholder="例如：预算需控制在 500 万以内；保留村口百年古树..."
              isTextarea
              rows={3}
            />
          </div>

          {/* 提交按钮 */}
          <motion.div variants={itemVariants} className="mt-8 flex justify-center">
            <motion.button
              type="submit"
              whileHover={{ scale: 1.02, y: -2 }}
              whileTap={{ scale: 0.98 }}
              className="relative px-8 py-3.5 rounded-full font-semibold text-white overflow-hidden group"
              style={{
                background: 'linear-gradient(135deg, #10b981 0%, #14b8a6 50%, #0891b2 100%)',
                boxShadow: '0 4px 20px rgba(16, 185, 129, 0.4)',
              }}
            >
              <span className="relative z-10 flex items-center gap-2">
                <span>开始规划</span>
                <span>🚀</span>
              </span>
              {/* Hover 光晕效果 */}
              <div className="absolute inset-0 bg-white/20 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
            </motion.button>
          </motion.div>
        </motion.div>

        {/* 底部提示 */}
        <motion.p
          variants={itemVariants}
          className="text-center text-gray-400 text-xs mt-6"
        >
          AI 将基于您的输入生成专业的村庄规划方案
        </motion.p>
      </motion.form>
    </div>
  );
}