export interface WidgetDimensions {
  minW: number;
  minH: number;
  defaultW: number;
  defaultH: number;
}

export type WidgetPermission = 'network' | 'system_monitor' | 'llm_access';

export interface IXiaoYiWidget {
  id: string;
  title: string;
  dimensions: WidgetDimensions;
  permissions: WidgetPermission[];
  render(): Promise<string>;
  onRefresh?(): Promise<void>;
}
