# 代码编辑规范

## 编辑文件时的核心原则

### 1. 最小化匹配范围
使用 `edit_file` 或 `Edit` 工具时，`oldText` **禁止**包含大段多行文本。
- ✅ 正确：只提取 1-2 行最核心、无歧义、**不包含中文注释**的代码
- ❌ 错误：匹配包含中文、Emoji、复杂标点的整行注释

### 2. 避开行尾符陷阱
遇到匹配失败时：
1. 停止重试相同的精确匹配
2. 改用 `sed` 等 CLI 工具通过行号精准修改
3. 或使用 `mcp__filesystem__edit_file` 工具

### 3. 代码与注释分离
避免在同一行写包含复杂中文和 Emoji 的注释。

**推荐写法**:
```typescript
// 🔧 暂停状态：status === 'paused'
isPaused: boolean;
```

**不推荐写法**:
```typescript
isPaused: boolean;  // 🔧 暂停状态：status === 'paused'
```

### 4. 使用短锚点定位
当需要修改多行时，使用独特的短字符串定位，而非完整代码块。

示例：
```
将 "setIsPaused: undefined;" 替换为 "setIsPaused: (paused: boolean) => void;"
```

### 5. 底层命令兜底
当文件编辑工具反复失败时，直接使用底层命令：
```bash
sed -i '67c\  setIsPaused: (paused: boolean) => void;' file.tsx
```

## 项目配置说明

- 换行符：**LF** (Unix 风格)，Windows 批处理文件例外 (.bat, .cmd 使用 CRLF)
- 缩进：**2 空格** (Python 使用 4 空格)
- 引号：**单引号** (前端), 双引号 (Python)
- 行尾：自动删除 trailing whitespace

## 常用命令参考

### TypeScript/JavaScript 格式化
```bash
npx prettier --write "frontend/src/**/*.tsx"
npx prettier --write "frontend/src/**/*.ts"
```

### 检查换行符
```bash
file frontend/src/**/*.tsx | grep CRLF  # 查找仍使用 CRLF 的文件
```

### 批量转换换行符
```bash
find frontend/src -name "*.tsx" -exec sed -i 's/\r$//' {} \;
```
