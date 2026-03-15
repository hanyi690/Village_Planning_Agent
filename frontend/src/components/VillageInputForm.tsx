'use client';

import { useState, FormEvent } from 'react';
import { motion } from 'framer-motion';
import { fileApi } from '@/lib/api';
import { FILE_ACCEPT } from '@/lib/constants';

export interface UploadedFileInfo {
  filename: string;
  content: string;
  size: number;
}

export interface VillageInputData {
  projectName: string;
  taskDescription: string;
  constraints: string;
  taskDescriptionFiles?: UploadedFileInfo[];
  constraintsFiles?: UploadedFileInfo[];
}

interface VillageInputFormProps {
  onSubmit: (data: VillageInputData) => void;
}

export default function VillageInputForm({ onSubmit }: VillageInputFormProps) {
  const [projectName, setProjectName] = useState('');
  const [taskDescription, setTaskDescription] = useState('');
  const [constraints, setConstraints] = useState('');
  const [focusedField, setFocusedField] = useState<string | null>(null);

  // 文件上传状态
  const [isUploadingTaskFiles, setIsUploadingTaskFiles] = useState(false);
  const [isUploadingConstraintFiles, setIsUploadingConstraintFiles] = useState(false);

  // 已上传文件列表
  const [taskFiles, setTaskFiles] = useState<UploadedFileInfo[]>([]);
  const [constraintFiles, setConstraintFiles] = useState<UploadedFileInfo[]>([]);

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
      taskDescriptionFiles: taskFiles.length > 0 ? taskFiles : undefined,
      constraintsFiles: constraintFiles.length > 0 ? constraintFiles : undefined,
    });
  };

  // 文件上传处理
  const handleFileSelect = async (
    e: React.ChangeEvent<HTMLInputElement>,
    type: 'task' | 'constraint'
  ) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    const setUploading = type === 'task' ? setIsUploadingTaskFiles : setIsUploadingConstraintFiles;
    const setFiles = type === 'task' ? setTaskFiles : setConstraintFiles;

    try {
      setUploading(true);

      // 并行上传所有文件
      const uploadPromises = Array.from(files).map(async (file) => {
        const response = await fileApi.uploadFile(file);
        return {
          filename: file.name,
          content: response.content,
          size: response.size,
        };
      });

      const results = await Promise.all(uploadPromises);

      // 追加到已有文件列表
      setFiles((prev) => [...prev, ...results]);
    } catch (error) {
      console.error('文件上传失败:', error);
      alert('文件上传失败，请重试');
    } finally {
      setUploading(false);
      e.target.value = ''; // 重置 input
    }
  };

  // 删除已上传文件
  const removeFile = (type: 'task' | 'constraint', index: number) => {
    if (type === 'task') {
      setTaskFiles((prev) => prev.filter((_, i) => i !== index));
    } else {
      setConstraintFiles((prev) => prev.filter((_, i) => i !== index));
    }
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
    uploadedFiles,
    isUploading,
    fileType,
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
    uploadedFiles?: UploadedFileInfo[];
    isUploading?: boolean;
    fileType?: 'task' | 'constraint';
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
          {/* 文件上传按钮 - 仅 textarea 显示 */}
          {isTextarea && fileType && (
            <motion.label
              htmlFor={`${id}-file-upload`}
              whileHover={{ scale: 1.1 }}
              whileTap={{ scale: 0.9 }}
              className={`absolute right-3 top-3 z-10 w-8 h-8 flex items-center justify-center rounded-full cursor-pointer transition-colors ${
                isUploading
                  ? 'text-cyan-400 cursor-wait'
                  : 'text-gray-400 hover:text-cyan-500 hover:bg-cyan-50'
              }`}
              title="上传文件"
            >
              <i className={`fas ${isUploading ? 'fa-spinner fa-spin' : 'fa-paperclip'}`} />
            </motion.label>
          )}

          {isTextarea ? (
            <textarea
              id={id}
              rows={rows}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onFocus={() => setFocusedField(id)}
              onBlur={() => setFocusedField(null)}
              placeholder={placeholder}
              className="w-full px-4 py-3 pr-12 bg-cyan-50/30 border-0 rounded-2xl text-gray-900 placeholder-gray-500 resize-none transition-all duration-300 focus:bg-white focus:ring-2 focus:ring-cyan-500/20 focus:shadow-[0_0_0_4px_rgba(8,145,178,0.1)]"
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
              className="w-full px-4 py-3.5 bg-cyan-50/30 border-0 rounded-2xl text-gray-900 placeholder-gray-500 transition-all duration-300 focus:bg-white focus:ring-2 focus:ring-cyan-500/20 focus:shadow-[0_0_0_4px_rgba(8,145,178,0.1)]"
            />
          )}
          {/* 底部渐变线 */}
          <div
            className={`absolute bottom-0 left-4 right-4 h-0.5 rounded-full transition-all duration-300 ${
              isFocused
                ? 'bg-gradient-to-r from-cyan-500 via-teal-500 to-emerald-500 opacity-100'
                : 'opacity-0'
            }`}
          />
        </div>

        {/* 已上传文件列表 */}
        {isTextarea && uploadedFiles && uploadedFiles.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {uploadedFiles.map((file, index) => (
              <span
                key={index}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-cyan-50 text-cyan-700 text-xs rounded-full border border-cyan-200"
              >
                <i className="fas fa-file-alt text-cyan-500" />
                <span className="max-w-[120px] truncate" title={file.filename}>
                  {file.filename}
                </span>
                <button
                  type="button"
                  onClick={() => fileType && removeFile(fileType, index)}
                  className="ml-1 w-4 h-4 flex items-center justify-center rounded-full hover:bg-cyan-200 transition-colors"
                  title="移除文件"
                >
                  <i className="fas fa-times text-[10px] text-cyan-600" />
                </button>
              </span>
            ))}
          </div>
        )}
      </motion.div>
    );
  };

  return (
    <div className="w-full min-h-[80vh] flex items-center justify-center p-4 bg-gradient-to-b from-cyan-50/50 to-white">
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
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-600 via-teal-500 to-emerald-600">
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
          className="bg-white rounded-2xl shadow-xl shadow-cyan-100/50 border border-cyan-100 p-6 sm:p-8"
        >
          {/* 隐藏的文件输入元素 */}
          <input
            type="file"
            multiple
            accept={FILE_ACCEPT}
            onChange={(e) => handleFileSelect(e, 'task')}
            disabled={isUploadingTaskFiles}
            className="hidden"
            id="taskDescription-file-upload"
          />
          <input
            type="file"
            multiple
            accept={FILE_ACCEPT}
            onChange={(e) => handleFileSelect(e, 'constraint')}
            disabled={isUploadingConstraintFiles}
            className="hidden"
            id="constraints-file-upload"
          />

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
              uploadedFiles={taskFiles}
              isUploading={isUploadingTaskFiles}
              fileType="task"
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
              uploadedFiles={constraintFiles}
              isUploading={isUploadingConstraintFiles}
              fileType="constraint"
            />
          </div>

          {/* 提交按钮 */}
          <motion.div variants={itemVariants} className="mt-8 flex justify-center">
            <motion.button
              type="submit"
              whileHover={{ scale: 1.02, y: -2 }}
              whileTap={{ scale: 0.98 }}
              className="relative px-8 py-3.5 rounded-xl font-semibold text-white overflow-hidden group"
              style={{
                background: 'linear-gradient(135deg, #0891B2 0%, #22D3EE 100%)',
                boxShadow: '0 4px 20px rgba(8, 145, 178, 0.3)',
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
        <motion.p variants={itemVariants} className="text-center text-gray-400 text-xs mt-6">
          AI 将基于您的输入生成专业的村庄规划方案
        </motion.p>
      </motion.form>
    </div>
  );
}
