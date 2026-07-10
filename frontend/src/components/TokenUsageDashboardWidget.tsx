import { Component, onMount } from 'solid-js';
import { TokenUsageWidget } from '../core/brain/token-usage-widget';

export const TokenUsageDashboardWidget: Component = () => {
  let root!: HTMLDivElement;

  onMount(async () => {
    const widget = new TokenUsageWidget();
    root.innerHTML = await widget.render();
  });

  return <div ref={root} class="panel" />;
};
