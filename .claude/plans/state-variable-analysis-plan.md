# 状态与变量管理综合分析方案

## 一、Agent命名规范基准（建议采纳）

基于Agent层是SSOT（Single Source of Truth）的原则，建议以Agent命名为准。

### 1.1 核心字段命名规范（snake_case）

Agent层在 `src/orchestration/state.py` 和 `routing.py` 中的一致使用：

| Agent字段 | 类型 | 用途 | 使用位置 |
|-----------|------|------|----------|
| `phase` | str | 规划阶段 | routing.py:90, dimension_node.py:19 |
| `current_wave` | int | 当前执行波次 | routing.py:91 |
| `reports` | Dict | 层级报告 | routing.py:239, dimension_node.py:198 |
| `completed_dimensions` | Dict | 已完成维度 | routing.py:160, 266 |
| `step_mode` | bool | 分步执行开关 | routing.py:316 |
| `pause_after_step` | bool | 层级完成后暂停标志 | routing.py:99, 292 |
| `previous_layer` | int | 刚完成的层级编号 | routing.py:94, 293 |
| `pending_review` | bool | 待审查标志 | routing.py:62（状态检查） |
| `need_revision` | bool | 需修订标志 | routing.py:62, 132 |
| `revision_target_dimensions` | List | 修订目标维度 | - |

### 1.2 PlanningPhase使用分析

**现状**: 存在两套定义，但**routing.py和dimension_node.py只使用简化版**

```python
# routing.py 第14-22行导入
from .state import (
    PlanningPhase,  # 来自 state.py 简化版
    get_layer_dimensions,
    ...
)

# dimension_node.py 第19行导入
from ..state import PlanningPhase, ...  # 来自 state.py 简化版
```

**关键发现**: 
- `checkpoint_types.py` 的详细版 PlanningPhase（14个值）**仅用于检查点标记**
- 实际路由逻辑使用 `state.py` 的简化版（5个值）
- 这导致语义模糊：`layer1` 既表示"执行中"又表示"刚完成等待审查"

**证据（routing.py 第284-294行）**:
```python
# Layer 1/2 完成时，phase 保持不变！
# 不推进 phase，保持当前阶段表示"刚完成，等待审查"
logger.info(f"[收集] {phase} 完成，设置暂停等待审查（phase 保持不变）")
updates["pause_after_step"] = True
updates["previous_layer"] = layer
```

### 1.3 Phase到Layer映射规则（Agent实现）

```python
# state.py 第204-210行
phase_to_layer_map = {
    PlanningPhase.INIT.value: 0,      # INIT 返回 0 表示未开始
    PlanningPhase.LAYER1.value: 1,
    PlanningPhase.LAYER2.value: 2,
    PlanningPhase.LAYER3.value: 3,
}
# COMPLETED 和未知阶段返回 None
```

---

## 二、识别的关键问题

### 问题1: 两套PlanningPhase语义冲突 [HIGH]

**位置**: 
- `src/orchestration/state.py` 第21-27行（简化版，实际路由使用）
- `src/core/checkpoint_types.py` 第23-50行（详细版，检查点标记）

**冲突细节**:
| 场景 | state.py | checkpoint_types.py | 实际使用 |
|------|----------|---------------------|----------|
| Layer1执行中 | layer1 | layer1_analyzing | routing使用layer1 |
| Layer1完成等待 | layer1 | layer1_completed | routing保持layer1 |
| Layer1修订完成 | - | layer1_revision_completed | 无对应 |

**影响**: 
- routing.py 在层级完成时不推进phase（第284-294行）
- 依赖 `pause_after_step` + `previous_layer` 来区分"执行中"和"完成等待"
- 详细版在checkpoint_types.py中仅作元数据标记，不参与路由

**代码证据（routing.py 第136-148行）**:
```python
# Layer 1/2/3 路由判断
if phase == PlanningPhase.LAYER1.value:
    return _check_layer_completion(state, layer=1)
elif phase == PlanningPhase.LAYER2.value:
    return _route_wave_layer(state, layer=2, current_wave=current_wave)
# 无法区分"执行中"还是"已完成等待审查"
```

### 问题2: 前端stepMode双重存储 [HIGH]

**位置**: `frontend/src/stores/planningStore.ts`

**代码**:
```typescript
// 第79行 - Agent状态字段（snake_case）
step_mode: boolean;

// 第105行 - UI状态字段（camelCase）
stepMode: boolean;

// 第901-902行 - syncBackendState中双重同步
state.step_mode = backendData.step_mode ?? state.step_mode;
state.stepMode = backendData.step_mode ?? state.stepMode;

// 第933-934行 - setStepMode只更新UI字段
setStepMode: (stepMode) => set((state) => {
  state.stepMode = stepMode;  // 不更新 step_mode！
});
```

**影响**: 
- `setStepMode` 不更新Agent字段，导致状态分裂
- 应使用计算属性而非双重存储

### 问题3: 状态枚举值不一致 [MEDIUM]

**对比表**:
| 场景 | 前端(PlanningStatus) | 后端(TaskStatus) | Agent(phase+flags) |
|------|---------------------|------------------|-------------------|
| 初始 | idle | pending | init |
| 执行 | planning | running | layer1 + pause=False |
| 暂停 | paused | paused | layer1 + pause_after_step=True |
| 审查 | reviewing | reviewing | layer1 + pending_review=True |
| 修订 | revising | revising | layer1 + need_revision=True |
| 完成 | completed | completed | completed |

**关键差异**: Agent使用**phase+flags组合**而非单一状态枚举

### 问题4: Phase到Layer映射差异 [MEDIUM]

**前端当前实现** (`planningStore.ts` 第138-145行):
```typescript
function phaseToLayer(phase: string): number | null {
  const mapping: Record<string, number> = {
    layer1: 1,
    layer2: 2,
    layer3: 3,
  };
  return mapping[phase] ?? null;  // init -> null, completed -> null
}
```

**Agent实现** (`state.py` 第204-210行):
```python
# INIT -> 0 表示未开始
# COMPLETED -> None（但前端应显示Layer 3）
```

**影响**: 
- init状态下前端currentLayer为null，与Agent返回0不一致
- completed状态下前端显示null而非3

### 问题5: currentWave命名混用 [LOW]

**前端Store**: `currentWave` (camelCase，第75行)
**Agent/Backend**: `current_wave` (snake_case)

**影响**: 
- syncBackendState缺少对current_wave的同步
- 导致波次状态不完整

### 问题6: SSE事件中的命名不一致 [LOW]

**event_factory.py 中的事件字段**:
```python
# create_layer_completed_event
{
    "layer": layer,
    "phase": phase,
    "pause_after_step": pause_after_step,  # snake_case
    "previous_layer": previous_layer,      # snake_case
}

# create_pause_event  
{
    "step_mode": step_mode,                # snake_case
    "previous_layer": previous_layer,
}
```

**前端SSE处理** (`planningStore.ts` 第560-567行):
```typescript
state.phase = layerData.phase || state.phase;
state.pause_after_step = layerData.pause_after_step ?? state.pause_after_step;
state.previous_layer = layerData.previous_layer ?? state.previous_layer;
// 正确使用 snake_case 字段名
```

---

## 三、改进方案

### 方案A: 统一PlanningPhase为详细版 [P1 - HIGH]

**步骤**:
1. 废弃 `src/orchestration/state.py` 中的简化版 PlanningPhase
2. 在 routing.py 和 dimension_node.py 导入 checkpoint_types.py 的详细版
3. 更新路由逻辑使用详细版

**修改**:

```python
# routing.py 导入改为
from ..core.checkpoint_types import PlanningPhase

# 收集结果时推进到详细完成阶段
# routing.py 第284行附近
if layer and layer < 3:
    # 推进到完成阶段
    phase_map = {
        1: PlanningPhase.LAYER1_COMPLETED.value,
        2: PlanningPhase.LAYER2_COMPLETED.value,
    }
    updates["phase"] = phase_map[layer]
    updates["pause_after_step"] = True
```

**好处**:
- phase语义清晰，不再依赖flags组合
- 前端可直接从phase判断状态

### 方案B: 消除stepMode双重存储 [P1 - HIGH]

**修改**: `frontend/src/stores/planningStore.ts`

```typescript
// 移除第105行的 stepMode 字段
// 将 stepMode 作为计算属性

// 修改第901-902行 syncBackendState
state.step_mode = backendData.step_mode ?? state.step_mode;
// 不再同步到 stepMode

// 修改第933-934行 setStepMode
setStepMode: (stepMode) => set((state) => {
  state.step_mode = stepMode;  // 只更新Agent字段
});

// 新增 selector（第1010行附近）
export const useStepMode = () => usePlanningStore((s) => s.step_mode);
```

### 方案C: 统一Phase到Layer映射 [P2 - MEDIUM]

**修改**: `frontend/src/stores/planningStore.ts` 第138-145行

```typescript
function phaseToLayer(phase: string): number {
  // 与Agent state.py 一致
  const mapping: Record<string, number> = {
    'init': 0,
    'layer1': 1,
    'layer2': 2,
    'layer3': 3,
    // 详细版支持
    'layer1_analyzing': 1,
    'layer1_completed': 1,
    'layer2_concepting': 2,
    'layer2_completed': 2,
    'layer3_planning': 3,
    'layer3_completed': 3,
    'completed': 3,
  };
  return mapping[phase] ?? 0;
}
```

### 方案D: 创建Agent状态到前端状态的映射工具 [P2 - MEDIUM]

**新增**: `frontend/src/lib/status-mapping.ts`

```typescript
import { PlanningStatus } from './constants';

interface AgentFlags {
  pause_after_step?: boolean;
  pending_review?: boolean;
  need_revision?: boolean;
}

/**
 * Agent phase+flags -> Frontend PlanningStatus 映射
 */
export function agentPhaseToStatus(
  phase: string, 
  flags: AgentFlags
): PlanningStatus {
  // 优先检查flags
  if (flags.need_revision) return 'revising';
  if (flags.pending_review) return 'reviewing';
  if (flags.pause_after_step) return 'paused';
  
  // phase映射
  const statusMap: Record<string, PlanningStatus> = {
    'init': 'idle',
    'layer1': 'planning',
    'layer1_analyzing': 'planning',
    'layer1_completed': 'paused',
    'layer2': 'planning',
    'layer2_concepting': 'planning',
    'layer2_completed': 'paused',
    'layer3': 'planning',
    'layer3_planning': 'planning',
    'layer3_completed': 'completed',
    'completed': 'completed',
  };
  return statusMap[phase] ?? 'idle';
}
```

### 方案E: 同步缺失的current_wave字段 [P3 - LOW]

**修改**: `frontend/src/stores/planningStore.ts`

```typescript
// 第75行修改命名（改为snake_case与Agent一致）
current_wave: number;

// syncBackendState中添加同步（约第898行）
if (backendData.current_wave !== undefined) {
  state.current_wave = backendData.current_wave;
}

// 更新所有使用 currentWave 的地方改为 current_wave
```

---

## 四、优先级排序

| 优先级 | 问题 | 方案 | 影响 | 文件数 |
|--------|------|------|------|--------|
| P1-HIGH | PlanningPhase语义冲突 | 方案A | 核心状态定义混乱 | 3 |
| P1-HIGH | stepMode双重存储 | 方案B | 状态不一致风险 | 1 |
| P2-MEDIUM | Phase到Layer映射差异 | 方案C | UI显示错误 | 1 |
| P2-MEDIUM | 状态枚举值不一致 | 方案D | 状态判断复杂 | 1（新增） |
| P3-LOW | currentWave命名混用 | 方案E | 命名一致性 | 多处 |

---

## 五、实施顺序建议

### 第一阶段：统一核心定义（P1）
1. **合并PlanningPhase到checkpoint_types.py**
   - 修改 `routing.py` 导入
   - 修改 `dimension_node.py` 导入
   - 更新路由逻辑使用详细阶段
   
2. **消除stepMode双重存储**
   - 移除 planningStore.ts 的 stepMode 字段
   - 修改 setStepMode 只更新 step_mode
   - 添加 useStepMode selector

### 第二阶段：统一映射规则（P2）
3. **修复Phase到Layer映射**
   - 更新 phaseToLayer 函数
   - 添加详细版phase支持
   
4. **创建状态映射工具**
   - 新增 status-mapping.ts
   - 实现 agentPhaseToStatus 函数

### 第三阶段：统一命名风格（P3）
5. **将currentWave改为current_wave**
   - Store字段重命名
   - 更新所有引用
   - 添加syncBackendState同步

---

## 六、关键发现总结

### Agent命名基准（snake_case）

Agent层在所有核心文件中使用一致的snake_case命名：
- `routing.py`: phase, current_wave, step_mode, pause_after_step, previous_layer
- `dimension_node.py`: 同样导入和使用state.py的定义
- `state.py`: 所有字段定义使用snake_case

### 状态语义关键点

Agent使用 **phase + flags 组合** 来表示复杂状态：
- `phase=layer1` + `pause_after_step=False` = 执行中
- `phase=layer1` + `pause_after_step=True` + `previous_layer=1` = Layer1完成等待审查
- `phase=layer1` + `need_revision=True` = 修订中

这与前端单一状态枚举（PlanningStatus）的设计不同，是映射混乱的根源。

### SSE事件命名一致性

SSE事件字段使用snake_case（与Agent一致），前端SSE处理也正确使用snake_case字段名。这部分无需修改。

---

### Critical Files for Implementation

1. **`src/orchestration/state.py`** - Agent核心状态定义，需要废弃简化版PlanningPhase
2. **`src/core/checkpoint_types.py`** - 目标统一PlanningPhase定义位置
3. **`frontend/src/stores/planningStore.ts`** - 前端状态管理，需要消除stepMode双重存储，修复phaseToLayer
4. **`src/orchestration/routing.py`** - 路由逻辑，需要更新导入和phase推进逻辑
5. **`frontend/src/lib/constants.ts`** - PlanningStatus定义，需要添加映射工具