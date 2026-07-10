/**
 * WidgetContainer — Widget 容器组件
 * 直接渲染 Solid.js 组件，生命周期由 Solid.js 自动管理
 */

import { Component } from 'solid-js';

export const WidgetContainer: Component<{ widget: any }> = (props) => {
  const WidgetComponent = props.widget;
  return (
    <div class="widget-container">
      <WidgetComponent />
    </div>
  );
};
