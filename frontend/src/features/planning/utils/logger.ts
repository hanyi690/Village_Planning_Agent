/**
 * Unified Logger for Frontend
 * Provides consistent logging format with session tracking and performance metrics
 */

export enum LogLevel {
  DEBUG = 'DEBUG',
  INFO = 'INFO',
  WARN = 'WARN',
  ERROR = 'ERROR'
}

export class Logger {
  private module: string;

  constructor(module: string) {
    this.module = module;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private log(level: LogLevel, action: string, details?: any, sessionId?: string | null) {
    const timestamp = new Date().toISOString();
    const sessionIdStr = sessionId ? ` [${sessionId.slice(0, 12)}...]` : '';
    const detailsStr = details ? ` ${JSON.stringify(details)}` : '';
    console.log(`[${timestamp}] [${level}] [${this.module}]${sessionIdStr} ${action}${detailsStr}`);
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  info(action: string, details?: any, sessionId?: string | null) {
    this.log(LogLevel.INFO, action, details, sessionId);
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  warn(action: string, details?: any, sessionId?: string | null) {
    this.log(LogLevel.WARN, action, details, sessionId);
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  error(action: string, details?: any, sessionId?: string | null) {
    this.log(LogLevel.ERROR, action, details, sessionId);
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  debug(action: string, details?: any, sessionId?: string | null) {
    this.log(LogLevel.DEBUG, action, details, sessionId);
  }
}

export const logger = {
  chatPanel: new Logger('ChatPanel'),
  sse: new Logger('SSE'),
  context: new Logger('PlanningContext'),
  api: new Logger('API'),
  form: new Logger('Form')
};
