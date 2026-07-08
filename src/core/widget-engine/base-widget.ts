/**
 * BaseWidget — Widget 引擎基类
 * 所有 Widget 必须继承此类
 * 提供：状态管理、生命周期钩子、异步刷新、错误边界
 */

export interface WidgetState {
  [key: string]: unknown;
}

export abstract class BaseWidget {
  public abstract id: string;
  public abstract title: string;
  public abstract permissions: string[];
  public abstract dimensions: {
    minW: number;
    minH: number;
    defaultW: number;
    defaultH: number;
  };

  protected state: WidgetState = {};
  private _mounted = false;
  private _errorHandler: ((error: Error) => void) | null = null;

  // ============================================================
  // 状态管理
  // ============================================================

  /**
   * 更新组件状态，触发重新渲染
   * 使用原子化状态更新，避免部分更新导致的不一致
   */
  setState(partial: Partial<WidgetState>): void {
    this.state = { ...this.state, ...partial };
    this.scheduleRender();
  }

  /**
   * 获取当前状态
   */
  getState(): WidgetState {
    return { ...this.state };
  }

  // ============================================================
  // 生命周期钩子（子类可覆盖）
  // ============================================================

  /**
   * 挂载时调用 — 启动定时器、订阅数据源
   */
  onMount(): void {
    this._mounted = true;
  }

  /**
   * 卸载时调用 — 清理定时器、取消订阅
   */
  onUnmount(): void {
    this._mounted = false;
  }

  /**
   * 数据刷新 — 子类必须实现异步数据获取
   * 禁止阻塞 UI 主线程
   */
  abstract onRefresh(): Promise<void>;

  /**
   * 渲染 — 子类必须实现
   */
  abstract render(): JSX.Element;

  // ============================================================
  // 工具方法
  // ============================================================

  /**
   * 触发重新渲染（使用 requestAnimationFrame 避免布局抖动）
   */
  protected scheduleRender(): void {
    if (typeof window !== 'undefined') {
      window.requestAnimationFrame(() => {
        if (this._mounted) {
          this.render();
        }
      });
    }
  }

  /**
   * 注册错误处理器
   */
  setErrorHandler(handler: (error: Error) => void): void {
    this._errorHandler = handler;
  }

  /**
   * 内部错误处理 — 防止 Widget 崩溃影响整个系统
   */
  protected handleError(error: Error): void {
    console.error(`[${this.id}] Widget error:`, error);
    if (this._errorHandler) {
      this._errorHandler(error);
    }
    // 设置错误状态，UI 显示错误信息
    this.setState({ error: error.message });
  }

  /**
   * 检查权限
   */
  hasPermission(permission: string): boolean {
    return this.permissions.includes(permission);
  }

  /**
   * 获取 Widget 尺寸
   */
  getDimensions() {
    return this.dimensions;
  }
}
