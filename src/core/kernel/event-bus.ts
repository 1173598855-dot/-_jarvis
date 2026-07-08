/**
 * EventBus — 小奕 J.A.R.V.I.S. 事件总线
 * @core/kernel
 *
 * 功能：
 * 1. 模块间解耦通信
 * 2. 事件订阅/发布/取消
 * 3. 异步事件处理
 * 4. 事件历史记录
 * 5. 错误隔离（单个处理器失败不影响其他）
 *
 * 萃取自 EventEmitter2 架构设计，重写为小奕原生实现
 */

// ============================================================
// 类型定义
// ============================================================

export interface EventBusEvent<T = unknown> {
  type: string;
  payload: T;
  timestamp: number;
  source?: string;
  correlationId?: string;
}

export type EventHandler<T = unknown> = (event: EventBusEvent<T>) => void | Promise<void>;

export interface EventSubscription {
  id: string;
  eventType: string;
  handler: EventHandler;
  once: boolean;
  active: boolean;
}

export interface EventBusConfig {
  maxHistory: number;
  enableAsync: boolean;
  errorStrategy: 'log' | 'ignore' | 'propagate';
}

// ============================================================
// EventBus 实现
// ============================================================

export class EventBus {
  private subscriptions: Map<string, EventSubscription[]> = new Map();
  private history: EventBusEvent[] = [];
  private config: EventBusConfig;
  private subscriptionIdCounter = 0;

  constructor(config: Partial<EventBusConfig> = {}) {
    this.config = {
      maxHistory: config.maxHistory ?? 1000,
      enableAsync: config.enableAsync ?? true,
      errorStrategy: config.errorStrategy ?? 'log',
    };
  }

  // ============================================================
  // 订阅管理
  // ============================================================

  /**
   * 订阅事件
   * @param eventType 事件类型（支持通配符 '*'）
   * @param handler 事件处理器
   * @param once 是否仅触发一次
   * @returns 订阅 ID（可用于取消订阅）
   */
  subscribe<T = unknown>(
    eventType: string,
    handler: EventHandler<T>,
    once: boolean = false,
  ): string {
    const subscriptionId = `sub_${++this.subscriptionIdCounter}`;

    const subscription: EventSubscription = {
      id: subscriptionId,
      eventType,
      handler: handler as EventHandler,
      once,
      active: true,
    };

    const existing = this.subscriptions.get(eventType) || [];
    existing.push(subscription);
    this.subscriptions.set(eventType, existing);

    return subscriptionId;
  }

  /**
   * 取消订阅
   */
  unsubscribe(subscriptionId: string): boolean {
    for (const [eventType, subs] of this.subscriptions.entries()) {
      const index = subs.findIndex(s => s.id === subscriptionId);
      if (index !== -1) {
        subs[index].active = false;
        subs.splice(index, 1);
        return true;
      }
    }
    return false;
  }

  /**
   * 取消某个事件类型的所有订阅
   */
  unsubscribeAll(eventType: string): number {
    const subs = this.subscriptions.get(eventType);
    if (!subs) return 0;
    const count = subs.length;
    subs.forEach(s => (s.active = false));
    this.subscriptions.delete(eventType);
    return count;
  }

  // ============================================================
  // 事件发布
  // ============================================================

  /**
   * 发布事件（同步）
   */
  emit<T = unknown>(eventType: string, payload: T, source?: string): void {
    const event: EventBusEvent<T> = {
      type: eventType,
      payload,
      timestamp: Date.now(),
      source,
    };

    // 记录历史
    this._recordHistory(event);

    // 触发处理器
    this._dispatch(event);
  }

  /**
   * 发布事件（异步）
   */
  async emitAsync<T = unknown>(
    eventType: string,
    payload: T,
    source?: string,
  ): Promise<void> {
    const event: EventBusEvent<T> = {
      type: eventType,
      payload,
      timestamp: Date.now(),
      source,
    };

    this._recordHistory(event);
    await this._dispatchAsync(event);
  }

  // ============================================================
  // 内部方法
  // ============================================================

  private _dispatch(event: EventBusEvent): void {
    // 精确匹配
    const handlers = this.subscriptions.get(event.type) || [];

    // 通配符匹配
    const wildcardHandlers = this.subscriptions.get('*') || [];

    const allHandlers = [...handlers, ...wildcardHandlers];

    for (const sub of allHandlers) {
      if (!sub.active) continue;

      try {
        sub.handler(event);

        if (sub.once) {
          sub.active = false;
        }
      } catch (error) {
        this._handleError(error, sub, event);
      }
    }
  }

  private async _dispatchAsync(event: EventBusEvent): Promise<void> {
    const handlers = this.subscriptions.get(event.type) || [];
    const wildcardHandlers = this.subscriptions.get('*') || [];
    const allHandlers = [...handlers, ...wildcardHandlers];

    const promises = allHandlers
      .filter(sub => sub.active)
      .map(async sub => {
        try {
          const result = sub.handler(event);
          if (result instanceof Promise) {
            await result;
          }

          if (sub.once) {
            sub.active = false;
          }
        } catch (error) {
          this._handleError(error, sub, event);
        }
      });

    await Promise.allSettled(promises);
  }

  private _handleError(error: unknown, sub: EventSubscription, event: EventBusEvent): void {
    const errorMessage = error instanceof Error ? error.message : String(error);

    switch (this.config.errorStrategy) {
      case 'log':
        console.error(`[EventBus] 处理器错误 (${sub.id}):`, errorMessage, {
          eventType: event.type,
          handler: sub.handler,
        });
        break;
      case 'ignore':
        // 静默忽略
        break;
      case 'propagate':
        throw error;
    }
  }

  private _recordHistory(event: EventBusEvent): void {
    this.history.push(event);

    // 限制历史大小
    while (this.history.length > this.config.maxHistory) {
      this.history.shift();
    }
  }

  // ============================================================
  // 查询方法
  // ============================================================

  /**
   * 获取事件历史
   */
  getHistory(eventType?: string, limit: number = 100): EventBusEvent[] {
    let events = this.history;

    if (eventType) {
      events = events.filter(e => e.type === eventType || eventType === '*');
    }

    return events.slice(-limit);
  }

  /**
   * 获取订阅数量
   */
  getSubscriptionCount(eventType?: string): number {
    if (eventType) {
      return (this.subscriptions.get(eventType) || []).filter(s => s.active).length;
    }

    let count = 0;
    for (const subs of this.subscriptions.values()) {
      count += subs.filter(s => s.active).length;
    }
    return count;
  }

  /**
   * 清除历史
   */
  clearHistory(): void {
    this.history = [];
  }

  /**
   * 销毁事件总线
   */
  destroy(): void {
    this.subscriptions.clear();
    this.history = [];
    this.subscriptionIdCounter = 0;
  }
}

// ============================================================
// 单例导出
// ============================================================

export const globalEventBus = new EventBus();
