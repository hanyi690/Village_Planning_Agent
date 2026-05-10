'use client';

import { memo, useState, useCallback, useEffect, FormEvent } from 'react';
import { motion } from 'framer-motion';
import { FILE_ACCEPT } from '@/features/planning/constants';

export interface UploadedFileInfo {
  filename: string;
  content: string;
  size: number;
}

export interface VillageInputData {
  projectName: string;
  taskDescription: string;
  constraints: string;
  villageData?: string;
  taskDescriptionFiles?: UploadedFileInfo[];
  constraintsFiles?: UploadedFileInfo[];
  villageDataFiles?: File[];
  taskFiles?: File[];
  constraintFiles?: File[];
}

interface VillageInputFormProps {
  onSubmit: (data: VillageInputData) => void;
  onLoadSession?: (villageName: string, sessionId: string) => void;
}

// ============================================
// Extracted sub-components (stable identity)
// ============================================

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { type: 'spring' as const, stiffness: 100, damping: 12 },
  },
};

type FileType = 'task' | 'constraint' | 'villageData';

interface FileTagsProps {
  files: File[];
  type: FileType;
  onRemove: (type: FileType, index: number) => void;
}

const FileTags = memo(function FileTags({ files, type, onRemove }: FileTagsProps) {
  if (files.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {files.map((file, index) => (
        <span
          key={index}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-cyan-50 text-cyan-700 text-xs rounded-full border border-cyan-200"
        >
          <i className="fas fa-file-alt text-cyan-500" />
          <span className="max-w-[120px] truncate" title={file.name}>
            {file.name}
          </span>
          <button
            type="button"
            onClick={() => onRemove(type, index)}
            className="ml-1 w-4 h-4 flex items-center justify-center rounded-full hover:bg-cyan-200 transition-colors"
            title="移除文件"
          >
            <i className="fas fa-times text-[10px] text-cyan-600" />
          </button>
        </span>
      ))}
    </div>
  );
});

interface InputFieldProps {
  id: string;
  label: string;
  icon: string;
  required?: boolean;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  isTextarea?: boolean;
  rows?: number;
  files?: File[];
  fileType?: FileType;
  isFocused: boolean;
  onFocus: () => void;
  onBlur: () => void;
  onRemoveFile?: (type: FileType, index: number) => void;
}

const InputField = memo(function InputField({
  id,
  label,
  icon,
  required,
  value,
  onChange,
  placeholder,
  isTextarea = false,
  rows = 3,
  files,
  fileType,
  isFocused,
  onFocus,
  onBlur,
  onRemoveFile,
}: InputFieldProps) {
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
        {isTextarea && fileType && (
          <motion.label
            htmlFor={`${id}-file-upload`}
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.9 }}
            className="absolute right-3 top-3 z-10 w-8 h-8 flex items-center justify-center rounded-full cursor-pointer transition-colors text-gray-400 hover:text-cyan-500 hover:bg-cyan-50"
            title="上传文件"
          >
            <i className="fas fa-paperclip" />
          </motion.label>
        )}

        {isTextarea ? (
          <textarea
            id={id}
            rows={rows}
            value={value}
            onChange={(e) => {
              if (!(e.nativeEvent as InputEvent).isComposing) {
                onChange(e.target.value);
              }
            }}
            onCompositionEnd={(e) => {
              onChange((e.target as HTMLTextAreaElement).value);
            }}
            onFocus={onFocus}
            onBlur={onBlur}
            placeholder={placeholder}
            className="w-full px-4 py-3 pr-12 bg-cyan-50/30 border-0 rounded-2xl text-gray-900 placeholder-gray-500 resize-none transition-all duration-300 focus:bg-white focus:ring-2 focus:ring-cyan-500/20 focus:shadow-[0_0_0_4px_rgba(8,145,178,0.1)]"
          />
        ) : (
          <input
            id={id}
            type="text"
            value={value}
            onChange={(e) => {
              if (!(e.nativeEvent as InputEvent).isComposing) {
                onChange(e.target.value);
              }
            }}
            onCompositionEnd={(e) => {
              onChange((e.target as HTMLInputElement).value);
            }}
            onFocus={onFocus}
            onBlur={onBlur}
            placeholder={placeholder}
            className="w-full px-4 py-3.5 bg-cyan-50/30 border-0 rounded-2xl text-gray-900 placeholder-gray-500 transition-all duration-300 focus:bg-white focus:ring-2 focus:ring-cyan-500/20 focus:shadow-[0_0_0_4px_rgba(8,145,178,0.1)]"
          />
        )}
        <div
          className={`absolute bottom-0 left-4 right-4 h-0.5 rounded-full transition-all duration-300 ${
            isFocused
              ? 'bg-gradient-to-r from-cyan-500 via-teal-500 to-emerald-500 opacity-100'
              : 'opacity-0'
          }`}
        />
      </div>

      {isTextarea && files && onRemoveFile && (
        <FileTags files={files} type={fileType!} onRemove={onRemoveFile} />
      )}
    </motion.div>
  );
});

// ============================================
// VillageInputForm
// ============================================

const VillageInputForm = memo(function VillageInputForm({ onSubmit, onLoadSession }: VillageInputFormProps) {
  const [projectName, setProjectName] = useState('');
  const [taskDescription, setTaskDescription] = useState('');
  const [constraints, setConstraints] = useState('');
  const [villageData, setVillageData] = useState('');
  const [focusedField, setFocusedField] = useState<string | null>(null);

  const [taskFiles, setTaskFiles] = useState<File[]>([]);
  const [constraintFiles, setConstraintFiles] = useState<File[]>([]);
  const [villageDataFiles, setVillageDataFiles] = useState<File[]>([]);

  useEffect(() => {
    console.log('VillageInputForm mounted');
    return () => console.log('VillageInputForm unmounted');
  }, []);

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
      villageData: villageData.trim() || undefined,
      villageDataFiles: villageDataFiles.length > 0 ? villageDataFiles : undefined,
      taskFiles: taskFiles.length > 0 ? taskFiles : undefined,
      constraintFiles: constraintFiles.length > 0 ? constraintFiles : undefined,
    });
  };

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>, type: FileType) => {
      const files = e.target.files;
      if (!files || files.length === 0) return;

      const setFiles = {
        task: setTaskFiles,
        constraint: setConstraintFiles,
        villageData: setVillageDataFiles,
      }[type];

      const newFiles = Array.from(files);
      setFiles((prev) => [...prev, ...newFiles]);
      e.target.value = '';
    },
    []
  );

  const removeFile = useCallback(
    (type: FileType, index: number) => {
      const setFiles = {
        task: setTaskFiles,
        constraint: setConstraintFiles,
        villageData: setVillageDataFiles,
      }[type];
      setFiles((prev) => prev.filter((_, i) => i !== index));
    },
    []
  );

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: { staggerChildren: 0.1, delayChildren: 0.2 },
    },
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

        <motion.div
          variants={itemVariants}
          className="bg-white rounded-2xl shadow-xl shadow-cyan-100/50 border border-cyan-100 p-6 sm:p-8"
        >
          <input
            type="file"
            multiple
            accept={FILE_ACCEPT}
            onChange={(e) => handleFileSelect(e, 'task')}
            className="hidden"
            id="taskDescription-file-upload"
          />
          <input
            type="file"
            multiple
            accept={FILE_ACCEPT}
            onChange={(e) => handleFileSelect(e, 'constraint')}
            className="hidden"
            id="constraints-file-upload"
          />
          <input
            type="file"
            multiple
            accept={FILE_ACCEPT}
            onChange={(e) => handleFileSelect(e, 'villageData')}
            className="hidden"
            id="villageData-file-upload"
          />

          <div className="space-y-6">
            <InputField
              id="projectName"
              label="村庄名称"
              icon="📍"
              required
              value={projectName}
              onChange={setProjectName}
              placeholder="例如：杭州市余杭区李家村"
              isFocused={focusedField === 'projectName'}
              onFocus={() => setFocusedField('projectName')}
              onBlur={() => setFocusedField(null)}
            />

            <InputField
              id="villageData"
              label="村庄基础数据"
              icon="📊"
              value={villageData}
              onChange={setVillageData}
              placeholder="请描述村庄的基本情况，如人口、面积、地理位置、产业现状等..."
              isTextarea
              rows={3}
              files={villageDataFiles}
              fileType="villageData"
              isFocused={focusedField === 'villageData'}
              onRemoveFile={removeFile}
              onFocus={() => setFocusedField('villageData')}
              onBlur={() => setFocusedField(null)}
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
              files={taskFiles}
              fileType="task"
              isFocused={focusedField === 'taskDescription'}
              onRemoveFile={removeFile}
              onFocus={() => setFocusedField('taskDescription')}
              onBlur={() => setFocusedField(null)}
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
              files={constraintFiles}
              fileType="constraint"
              isFocused={focusedField === 'constraints'}
              onRemoveFile={removeFile}
              onFocus={() => setFocusedField('constraints')}
              onBlur={() => setFocusedField(null)}
            />

          </div>

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
              <div className="absolute inset-0 bg-white/20 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
            </motion.button>
          </motion.div>
        </motion.div>

        <motion.p variants={itemVariants} className="text-center text-gray-400 text-xs mt-6">
          AI 将基于您的输入生成专业的村庄规划方案
        </motion.p>
      </motion.form>
    </div>
  );
});

export default VillageInputForm;
