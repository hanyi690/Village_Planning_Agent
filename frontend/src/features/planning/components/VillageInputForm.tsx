'use client';

import { memo, useState, useCallback, useEffect, FormEvent } from 'react';
import { motion } from 'framer-motion';
import {
  faMapMarkerAlt,
  faChartBar,
  faClipboardList,
  faCog,
  faRocket,
  faPaperclip,
  faTimes,
} from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { FILE_ACCEPT } from '@/features/planning/constants';

export interface UploadedFileInfo {
  filename: string;
  content: string;
  size: number;
}

export interface VillageInputData {
  projectName: string;
  // 行政区划和规划期限
  province?: string;
  city?: string;
  county?: string;
  township?: string;
  planningPeriod?: string;
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
// Animation variants
// ============================================

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.08, delayChildren: 0.1 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { type: 'spring' as const, stiffness: 100, damping: 12 },
  },
};

// ============================================
// Sub-components
// ============================================

type FileType = 'task' | 'constraint' | 'villageData';

interface FileTagsProps {
  files: File[];
  type: FileType;
  onRemove: (type: FileType, index: number) => void;
}

const FileTags = memo(function FileTags({ files, type, onRemove }: FileTagsProps) {
  if (files.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {files.map((file, index) => (
        <motion.span
          key={index}
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          className="inline-flex items-center gap-2 px-3 py-1.5 bg-amber-50 text-amber-700 text-xs rounded-lg border border-amber-200"
        >
          <FontAwesomeIcon icon={faPaperclip} className="text-amber-500" style={{ width: 10, height: 10 }} />
          <span className="max-w-[140px] truncate" title={file.name}>
            {file.name}
          </span>
          <button
            type="button"
            onClick={() => onRemove(type, index)}
            className="w-4 h-4 flex items-center justify-center rounded-full hover:bg-amber-200 transition-colors"
            title="移除文件"
          >
            <FontAwesomeIcon icon={faTimes} style={{ width: 8, height: 8 }} />
          </button>
        </motion.span>
      ))}
    </div>
  );
});

interface InputFieldProps {
  id: string;
  label: string;
  icon: React.ReactNode;
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
  helpText?: string;
  compact?: boolean;
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
  isFocused: _isFocused,
  onFocus,
  onBlur,
  onRemoveFile,
  helpText,
  compact = false,
}: InputFieldProps) {
  const inputClasses = compact
    ? "w-full px-3 py-2 text-sm bg-slate-50/50 border border-slate-200 rounded-lg text-slate-900 placeholder-slate-400 transition-all duration-200 focus:bg-white focus:border-amber-300 focus:ring-2 focus:ring-amber-100"
    : "w-full px-5 py-4 bg-slate-50/50 border-2 border-slate-200 rounded-2xl text-slate-900 placeholder-slate-400 transition-all duration-300 focus:bg-white focus:border-amber-300 focus:ring-4 focus:ring-amber-100";

  const textareaClasses = compact
    ? "w-full px-3 py-2 text-sm bg-slate-50/50 border border-slate-200 rounded-lg text-slate-900 placeholder-slate-400 resize-none transition-all duration-200 focus:bg-white focus:border-amber-300 focus:ring-2 focus:ring-amber-100"
    : "w-full px-5 py-4 pr-14 bg-slate-50/50 border-2 border-slate-200 rounded-2xl text-slate-900 placeholder-slate-400 resize-none transition-all duration-300 focus:bg-white focus:border-amber-300 focus:ring-4 focus:ring-amber-100";

  const labelClasses = compact
    ? "flex items-center gap-1.5 text-xs font-medium text-slate-600 mb-1"
    : "flex items-center gap-2 text-sm font-medium text-slate-700 mb-2";

  return (
    <motion.div variants={itemVariants} className="w-full">
      <label
        htmlFor={id}
        className={labelClasses}
      >
        {icon}
        <span>{label}</span>
        {required && <span className="text-red-400">*</span>}
      </label>

      <div className="relative group">
        {isTextarea && fileType && (
          <motion.label
            htmlFor={`${id}-file-upload`}
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.9 }}
            className="absolute right-4 top-4 z-10 w-9 h-9 flex items-center justify-center rounded-lg cursor-pointer transition-colors text-slate-400 hover:text-amber-500 hover:bg-amber-50"
            title="上传文件"
          >
            <FontAwesomeIcon icon={faPaperclip} style={{ width: 14, height: 14 }} />
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
            className={textareaClasses}
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
            className={inputClasses}
          />
        )}
      </div>

      {helpText && (
        <p className="mt-2 text-xs text-slate-400">{helpText}</p>
      )}

      {isTextarea && files && onRemoveFile && (
        <FileTags files={files} type={fileType!} onRemove={onRemoveFile} />
      )}
    </motion.div>
  );
});

// ============================================
// Main Form Component
// ============================================

const VillageInputForm = memo(function VillageInputForm({ onSubmit, onLoadSession: _onLoadSession }: VillageInputFormProps) {
  const [projectName, setProjectName] = useState('');
  // 行政区划字段
  const [province, setProvince] = useState('');
  const [city, setCity] = useState('');
  const [county, setCounty] = useState('');
  const [township, setTownship] = useState('');
  const [planningPeriod, setPlanningPeriod] = useState('2022-2035年');
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
      // 行政区划和规划期限
      province: province.trim(),
      city: city.trim(),
      county: county.trim(),
      township: township.trim(),
      planningPeriod: planningPeriod.trim(),
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

  return (
    <motion.form
      onSubmit={handleSubmit}
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className="w-full"
    >
      {/* Form Card */}
      <motion.div
        variants={itemVariants}
        className="bg-white rounded-2xl shadow-sm border border-slate-200/60 p-6"
      >
          {/* Hidden file inputs */}
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

          {/* Form fields */}
          <div className="space-y-5">
            {/* Section: 基本信息 */}
            <div>
              <div className="flex items-center gap-2 mb-4">
                <div className="w-6 h-px bg-gradient-to-r from-amber-300 to-transparent" />
                <span className="text-xs font-medium text-amber-600 uppercase tracking-wider">基本信息</span>
                <div className="flex-1 h-px bg-gradient-to-l from-amber-300 to-transparent" />
              </div>

              <InputField
                id="projectName"
                label="项目名称"
                icon={<FontAwesomeIcon icon={faMapMarkerAlt} className="text-amber-500" style={{ width: 14, height: 14 }} />}
                required
                value={projectName}
                onChange={setProjectName}
                placeholder="例如：杭州市余杭区李家村"
                isFocused={focusedField === 'projectName'}
                onFocus={() => setFocusedField('projectName')}
                onBlur={() => setFocusedField(null)}
              />

              {/* 行政区划和规划期限 */}
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mt-4">
                <InputField
                  id="province"
                  label="省份"
                  icon={<FontAwesomeIcon icon={faMapMarkerAlt} className="text-blue-500" style={{ width: 12, height: 12 }} />}
                  value={province}
                  onChange={setProvince}
                  placeholder="广东省"
                  isFocused={focusedField === 'province'}
                  onFocus={() => setFocusedField('province')}
                  onBlur={() => setFocusedField(null)}
                  compact
                />
                <InputField
                  id="city"
                  label="地级市"
                  icon={<FontAwesomeIcon icon={faMapMarkerAlt} className="text-blue-400" style={{ width: 12, height: 12 }} />}
                  value={city}
                  onChange={setCity}
                  placeholder="梅州市"
                  isFocused={focusedField === 'city'}
                  onFocus={() => setFocusedField('city')}
                  onBlur={() => setFocusedField(null)}
                  compact
                />
                <InputField
                  id="county"
                  label="县/区"
                  icon={<FontAwesomeIcon icon={faMapMarkerAlt} className="text-blue-300" style={{ width: 12, height: 12 }} />}
                  value={county}
                  onChange={setCounty}
                  placeholder="平远县"
                  isFocused={focusedField === 'county'}
                  onFocus={() => setFocusedField('county')}
                  onBlur={() => setFocusedField(null)}
                  compact
                />
                <InputField
                  id="township"
                  label="乡镇"
                  icon={<FontAwesomeIcon icon={faMapMarkerAlt} className="text-blue-200" style={{ width: 12, height: 12 }} />}
                  value={township}
                  onChange={setTownship}
                  placeholder="泗水镇"
                  isFocused={focusedField === 'township'}
                  onFocus={() => setFocusedField('township')}
                  onBlur={() => setFocusedField(null)}
                  compact
                />
                <InputField
                  id="planningPeriod"
                  label="规划期限"
                  icon={<FontAwesomeIcon icon={faClipboardList} className="text-purple-500" style={{ width: 12, height: 12 }} />}
                  value={planningPeriod}
                  onChange={setPlanningPeriod}
                  placeholder="2022-2035年"
                  isFocused={focusedField === 'planningPeriod'}
                  onFocus={() => setFocusedField('planningPeriod')}
                  onBlur={() => setFocusedField(null)}
                  compact
                />
              </div>
            </div>

            {/* Section: 村庄数据 */}
            <div>
              <div className="flex items-center gap-2 mb-4">
                <div className="w-6 h-px bg-gradient-to-r from-cyan-300 to-transparent" />
                <span className="text-xs font-medium text-cyan-600 uppercase tracking-wider">村庄数据</span>
                <div className="flex-1 h-px bg-gradient-to-l from-cyan-300 to-transparent" />
              </div>

              <InputField
                id="villageData"
                label="村庄基础数据"
                icon={<FontAwesomeIcon icon={faChartBar} className="text-cyan-500" style={{ width: 14, height: 14 }} />}
                value={villageData}
                onChange={setVillageData}
                placeholder="请描述村庄的基本情况，如人口、面积、地理位置、产业现状等..."
                isTextarea
                rows={4}
                files={villageDataFiles}
                fileType="villageData"
                isFocused={focusedField === 'villageData'}
                onRemoveFile={removeFile}
                onFocus={() => setFocusedField('villageData')}
                onBlur={() => setFocusedField(null)}
                helpText="支持上传文件或直接输入数据"
              />
            </div>

            {/* Section: 规划要求 */}
            <div>
              <div className="flex items-center gap-2 mb-4">
                <div className="w-6 h-px bg-gradient-to-r from-emerald-300 to-transparent" />
                <span className="text-xs font-medium text-emerald-600 uppercase tracking-wider">规划要求</span>
                <div className="flex-1 h-px bg-gradient-to-l from-emerald-300 to-transparent" />
              </div>

              <div className="space-y-5">
                <InputField
                  id="taskDescription"
                  label="任务描述"
                  icon={<FontAwesomeIcon icon={faClipboardList} className="text-emerald-500" style={{ width: 14, height: 14 }} />}
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
                  icon={<FontAwesomeIcon icon={faCog} className="text-slate-500" style={{ width: 14, height: 14 }} />}
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
            </div>
          </div>

          {/* Submit button */}
          <motion.div variants={itemVariants} className="mt-6 flex justify-center">
            <motion.button
              type="submit"
              whileHover={{ scale: 1.02, y: -2 }}
              whileTap={{ scale: 0.98 }}
              className="relative px-8 py-3 rounded-xl font-semibold text-white overflow-hidden group"
              style={{
                background: 'linear-gradient(135deg, #f59e0b 0%, #ea580c 100%)',
                boxShadow: '0 4px 24px rgba(245, 158, 11, 0.35)',
              }}
            >
              <span className="relative z-10 flex items-center gap-2">
                <span>开始规划</span>
                <FontAwesomeIcon icon={faRocket} style={{ width: 14, height: 14 }} />
              </span>
              <div className="absolute inset-0 bg-white/20 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
            </motion.button>
          </motion.div>
        </motion.div>
      </motion.form>
  );
});

export default VillageInputForm;