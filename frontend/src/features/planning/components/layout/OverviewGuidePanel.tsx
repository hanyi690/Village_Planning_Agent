'use client';

import React, { useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faArrowRight,
  faChartPie,
  faChevronDown,
  faChevronUp,
  faCompass,
  faFileAlt,
  faLayerGroup,
  faLightbulb,
  faSpinner,
  faWandMagicSparkles,
} from '@fortawesome/free-solid-svg-icons';

import { DIMENSIONS_BY_LAYER, getDimensionName } from '@/features/planning/config/dimensions';

type GuideVariant =
  | 'analysis-intro'
  | 'analysis-pending'
  | 'document-intro'
  | 'document-waiting'
  | 'document-ready'
  | 'document-generating'
  | 'evaluation-intro';

interface OverviewGuidePanelProps {
  variant: GuideVariant;
  onGoToTask?: () => void;
  onRetryGenerate?: () => void;
  completedDimensions?: number;
  totalDimensions?: number;
  progressPercent?: number;
  isGenerating?: boolean;
  notice?: string | null;
  error?: string | null;
}

const LAYER_META = [
  {
    layer: 1 as const,
    label: 'L1 现状分析',
    subtitle: '摸清家底 · 资源禀赋',
    icon: faChartPie,
    accent: 'border-t-[#3fb288] bg-gradient-to-b from-[#f0faf5] to-white',
    badge: 'bg-[#e8f5ef] text-[#2d8c6d]',
    dot: 'bg-[#3fb288]',
    chip: 'border-[#d9eee4] bg-white/90 text-[#4d7d6c] hover:border-[#9fd4bc] hover:bg-[#f6fcf9]',
  },
  {
    layer: 2 as const,
    label: 'L2 规划思路',
    subtitle: '定位目标 · 策略路径',
    icon: faLightbulb,
    accent: 'border-t-[#5b9fd4] bg-gradient-to-b from-[#f3f8fc] to-white',
    badge: 'bg-[#e8f1f8] text-[#3d6f9a]',
    dot: 'bg-[#5b9fd4]',
    chip: 'border-[#dbe8f2] bg-white/90 text-[#4d6d85] hover:border-[#a8c8e0] hover:bg-[#f6fafd]',
  },
  {
    layer: 3 as const,
    label: 'L3 详细规划',
    subtitle: '空间布局 · 项目落地',
    icon: faCompass,
    accent: 'border-t-[#8b7fd4] bg-gradient-to-b from-[#f6f4fc] to-white',
    badge: 'bg-[#eeebf8] text-[#5c52a8]',
    dot: 'bg-[#8b7fd4]',
    chip: 'border-[#e4dff2] bg-white/90 text-[#5c5685] hover:border-[#c4b8e8] hover:bg-[#faf9fe]',
  },
];

const DOCUMENT_STEPS = [
  { title: '完成 28 个专题分析', detail: '智能体逐维生成 L1/L2/L3 报告' },
  { title: '汇总专题成果', detail: '自动整合各维度分析结论' },
  { title: '生成法定规划文档', detail: '输出目录式规划文本成果' },
];

function PanelShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-[#f7fbf9]">
      <div className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-[#dff3ea]/50 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-24 -left-12 h-48 w-48 rounded-full bg-[#e8eef8]/60 blur-3xl" />
      <div className="relative flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 lg:p-5">
        {children}
      </div>
    </div>
  );
}

function HeroCard({
  icon,
  iconWrap,
  eyebrow,
  title,
  description,
  action,
}: {
  icon: typeof faLayerGroup;
  iconWrap: string;
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-[0_8px_30px_rgba(38,95,74,0.06)]">
      <div className="bg-gradient-to-r from-[#f3faf7] via-white to-[#f8fbfa] px-5 py-4 lg:px-6 lg:py-5">
        <div className="flex flex-wrap items-start gap-4">
          <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl shadow-sm ${iconWrap}`}>
            <FontAwesomeIcon icon={icon} style={{ width: 20, height: 20 }} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[12px] font-semibold uppercase tracking-[0.14em] text-[#7aa896]">{eyebrow}</div>
            <h2 className="mt-1 text-[20px] font-bold tracking-tight text-[#1f4a3d] lg:text-[22px]">{title}</h2>
            <p className="mt-2 max-w-2xl text-[14px] leading-7 text-[#628578]">{description}</p>
          </div>
          {action}
        </div>
      </div>
    </div>
  );
}

function PrimaryButton({ onClick, children }: { onClick?: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-[#3fb288] px-4 py-2.5 text-[13px] font-semibold text-white shadow-md transition hover:bg-[#359f7b] hover:shadow-lg"
    >
      {children}
      <FontAwesomeIcon icon={faArrowRight} style={{ width: 12, height: 12 }} />
    </button>
  );
}

function LayerCard({
  layer,
  label,
  subtitle,
  icon,
  accent,
  badge,
  dot,
  chip,
  dimPreview,
}: {
  layer: 1 | 2 | 3;
  label: string;
  subtitle: string;
  icon: typeof faChartPie;
  accent: string;
  badge: string;
  dot: string;
  chip: string;
  dimPreview: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const dims = DIMENSIONS_BY_LAYER[layer];
  const hasMore = dims.length > dimPreview;
  const visibleDims = expanded ? dims : dims.slice(0, dimPreview);

  return (
    <div
      className={`flex min-h-[220px] flex-col overflow-hidden rounded-2xl border border-[#e3efe9] border-t-[3px] shadow-sm ${accent}`}
    >
      <div className="flex items-start justify-between gap-3 px-4 pt-4">
        <div className="flex items-start gap-3">
          <div className={`mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${badge}`}>
            <FontAwesomeIcon icon={icon} style={{ width: 16, height: 16 }} />
          </div>
          <div>
            <div className="text-[14px] font-bold text-[#284f43]">{label}</div>
            <div className="mt-0.5 text-[12px] text-[#7d9a8f]">{subtitle}</div>
          </div>
        </div>
        <span className="rounded-full bg-white/90 px-2.5 py-1 text-[11px] font-semibold text-[#6d8f82] shadow-sm">
          {dims.length} 专题
        </span>
      </div>
      <div className="mt-3 flex-1 space-y-1.5 px-3 pb-3">
        {visibleDims.map((dimKey) => (
          <div
            key={dimKey}
            className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-[12px] transition-colors ${chip}`}
          >
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
            <span className="leading-5">{getDimensionName(dimKey)}</span>
          </div>
        ))}
      </div>
      {hasMore && (
        <div className="border-t border-white/60 px-3 py-2">
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-white/80 px-3 py-2 text-[12px] font-medium text-[#4d7d6c] transition hover:bg-white hover:text-[#2d8c6d]"
          >
            <span>{expanded ? '收起专题' : `展开全部（还有 ${dims.length - dimPreview} 个）`}</span>
            <FontAwesomeIcon
              icon={expanded ? faChevronUp : faChevronDown}
              style={{ width: 11, height: 11 }}
            />
          </button>
        </div>
      )}
      {!hasMore && <div className="pb-3" />}
    </div>
  );
}

function LayerPreviewGrid({ dimPreview = 5 }: { dimPreview?: number }) {
  return (
    <div className="grid min-h-0 gap-3 lg:grid-cols-3">
      {LAYER_META.map(({ layer, label, subtitle, icon, accent, badge, dot, chip }) => (
        <LayerCard
          key={layer}
          layer={layer}
          label={label}
          subtitle={subtitle}
          icon={icon}
          accent={accent}
          badge={badge}
          dot={dot}
          chip={chip}
          dimPreview={dimPreview}
        />
      ))}
    </div>
  );
}

function DocumentPipeline() {
  return (
    <div className="grid gap-3 lg:grid-cols-3">
      {DOCUMENT_STEPS.map((step, index) => (
        <div
          key={step.title}
          className="relative overflow-hidden rounded-2xl border border-[#e3edf5] bg-white p-4 shadow-sm"
        >
          <div className="absolute right-3 top-3 text-[32px] font-black leading-none text-[#edf3f8]">
            {index + 1}
          </div>
          <div className="relative">
            <div className="mb-3 inline-flex h-8 w-8 items-center justify-center rounded-full bg-[#e8f1f8] text-[12px] font-bold text-[#4a6fa5]">
              {index + 1}
            </div>
            <div className="text-[14px] font-bold text-[#2f4a68]">{step.title}</div>
            <p className="mt-1.5 text-[12px] leading-6 text-[#7a92ad]">{step.detail}</p>
          </div>
          {index < DOCUMENT_STEPS.length - 1 && (
            <div className="absolute -right-2 top-1/2 hidden h-px w-4 -translate-y-1/2 bg-[#d7e3ef] lg:block" />
          )}
        </div>
      ))}
    </div>
  );
}

function ProgressCard({
  completedDimensions,
  totalDimensions,
  progressPercent,
  isGenerating,
  error,
  notice,
}: {
  completedDimensions: number;
  totalDimensions: number;
  progressPercent: number;
  isGenerating?: boolean;
  error?: string | null;
  notice?: string | null;
}) {
  return (
    <div className="rounded-2xl border border-[#dcebe4] bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="text-[13px] font-semibold text-[#5d7f72]">分层分析进度</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-[30px] font-bold tabular-nums text-[#2d8c6d]">{completedDimensions}</span>
            <span className="text-[15px] text-[#8aa59a]">/ {totalDimensions} 专题</span>
          </div>
        </div>
        <div className="flex h-[4.5rem] w-[4.5rem] items-center justify-center rounded-full border-4 border-[#e7f2ed] bg-[#f8fcfa]">
          <span className="text-[14px] font-bold tabular-nums text-[#3a8f6f]">{progressPercent}%</span>
        </div>
      </div>
      <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-[#e7f2ed]">
        <div
          className="h-full rounded-full bg-gradient-to-r from-[#7fd4b0] via-[#4fbf93] to-[#3fb288] transition-all duration-700"
          style={{ width: `${progressPercent}%` }}
        />
      </div>
      {notice && (
        <p className="mt-3 rounded-xl bg-[#f3faf7] px-3 py-2 text-[13px] leading-6 text-[#5d7f72]">{notice}</p>
      )}
      {isGenerating && (
        <div className="mt-3 flex items-center gap-2 rounded-xl bg-[#f0faf5] px-3 py-2.5 text-[13px] text-[#3a8f6f]">
          <FontAwesomeIcon icon={faSpinner} spin style={{ width: 13, height: 13 }} />
          <span>正在汇总专题报告并生成文档…</span>
        </div>
      )}
      {error && <p className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</p>}
    </div>
  );
}

export default function OverviewGuidePanel({
  variant,
  onGoToTask,
  onRetryGenerate,
  completedDimensions = 0,
  totalDimensions = 28,
  progressPercent = 0,
  isGenerating = false,
  notice,
  error,
}: OverviewGuidePanelProps) {
  const goTaskButton = onGoToTask ? (
    <PrimaryButton onClick={onGoToTask}>前往任务设置</PrimaryButton>
  ) : null;

  if (variant === 'analysis-intro' || variant === 'analysis-pending') {
    const isPending = variant === 'analysis-pending';
    return (
      <PanelShell>
        <HeroCard
          icon={faLayerGroup}
          iconWrap="bg-[#dff3ea] text-[#2d8c6d]"
          eyebrow="Planning Analysis"
          title={isPending ? '尚未开始分层分析' : '分层分析工作台'}
          description={
            isPending
              ? '请先在任务设置中填写项目信息并点击「开始规划」。启动后，智能体将按 L1/L2/L3 三层、共 28 个专题逐维生成分析报告。'
              : '启动规划后，智能体将按 L1 现状、L2 思路、L3 详规三层结构，逐维完成 28 个专题分析并生成报告。'
          }
          action={goTaskButton}
        />
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-[14px] font-bold text-[#284f43]">分析维度预览</h3>
            <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-medium text-[#7d9a8f] shadow-sm">
              共 28 个专题
            </span>
          </div>
          <LayerPreviewGrid />
        </div>
      </PanelShell>
    );
  }

  if (variant === 'evaluation-intro') {
    return (
      <PanelShell>
        <HeroCard
          icon={faWandMagicSparkles}
          iconWrap="bg-[#eef8f3] text-[#2d8c6d]"
          eyebrow="Quality Evaluation"
          title="规划质量评估"
          description="启动规划并完成分层分析后，可在此对 28 个专题报告进行自动化质量检测：文本忠实度、内容深度与法规引用真实性核验。"
          action={goTaskButton}
        />
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            { title: '忠实度', detail: '陈述是否被 RAG 上下文支持' },
            { title: '内容深度', detail: '指标、法规与技术方法覆盖' },
            { title: '引用核验', detail: '对照 RAG 文档库溯源' },
          ].map((item) => (
            <div
              key={item.title}
              className="rounded-2xl border border-[#e3efe9] bg-white px-4 py-3 shadow-sm"
            >
              <div className="text-[13px] font-semibold text-[#284f43]">{item.title}</div>
              <div className="mt-1 text-[12px] leading-5 text-[#7d9a8f]">{item.detail}</div>
            </div>
          ))}
        </div>
      </PanelShell>
    );
  }

  if (variant === 'document-intro') {
    return (
      <PanelShell>
        <HeroCard
          icon={faFileAlt}
          iconWrap="bg-[#e8eef8] text-[#4a6fa5]"
          eyebrow="Planning Document"
          title="规划文本成果"
          description="分层分析全部完成后，可在审查确认专题成果后手动生成结构完整、目录清晰的法定规划文档。"
          action={goTaskButton}
        />
        <div>
          <h3 className="mb-3 text-[14px] font-bold text-[#284f43]">生成流程</h3>
          <DocumentPipeline />
        </div>
        <div className="rounded-2xl border border-dashed border-[#d6e8df] bg-white/70 px-4 py-3 text-[13px] leading-6 text-[#6d8f82]">
          规划文本不会提前生成。请先在分层分析工作台完成审查与修改，再手动点击「生成规划文本」。
        </div>
      </PanelShell>
    );
  }

  const isGeneratingVariant = variant === 'document-generating';
  const isReadyVariant = variant === 'document-ready';

  return (
    <PanelShell>
      <HeroCard
        icon={isGeneratingVariant ? faWandMagicSparkles : faFileAlt}
        iconWrap={isGeneratingVariant ? 'bg-[#e8f5ef] text-[#2d8c6d]' : isReadyVariant ? 'bg-[#e8eef8] text-[#4a6fa5]' : 'bg-[#f3f8f5] text-[#8aa59a]'}
        eyebrow="Planning Document"
        title={
          isGeneratingVariant
            ? (isGenerating ? '正在生成规划文本' : '准备生成规划文本')
            : isReadyVariant
              ? '可生成规划文本'
              : '等待分层分析完成'
        }
        description={
          notice
          || (variant === 'document-waiting'
            ? '规划文本将基于智能体完成的 28 个专题报告汇总生成，分析未完成前不会生成。'
            : isReadyVariant
              ? '分层分析已完成。请先在审查工作台确认或修改专题成果，再手动生成规划文本。'
              : '分层分析已完成，系统正在汇总各专题智能体报告并生成法定规划文档。')
        }
        action={
          (isReadyVariant || (isGeneratingVariant && !isGenerating)) && onRetryGenerate ? (
            <button
              type="button"
              onClick={onRetryGenerate}
              className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-[#c9e8db] bg-white px-4 py-2.5 text-[13px] font-semibold text-[#2d8c6d] shadow-sm transition hover:bg-[#f3fbf7]"
            >
              生成规划文本
            </button>
          ) : undefined
        }
      />

      <div className="grid min-h-0 gap-4 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <ProgressCard
          completedDimensions={completedDimensions}
          totalDimensions={totalDimensions}
          progressPercent={progressPercent}
          isGenerating={isGeneratingVariant && isGenerating}
          error={error}
          notice={isReadyVariant ? '审查确认后，点击上方按钮开始生成规划文本。' : !isGeneratingVariant ? '完成全部分析后，可在此手动生成规划文本。' : notice}
        />
        <div>
          <h3 className="mb-3 text-[14px] font-bold text-[#284f43]">专题结构</h3>
          <LayerPreviewGrid dimPreview={4} />
        </div>
      </div>
    </PanelShell>
  );
}
