import { Component, onMount } from 'solid-js';
import { GithubDashboardWidget } from '../core/brain/github-dashboard-widget';

export const GithubIntelligenceWidget: Component = () => {
  let root!: HTMLDivElement;

  onMount(async () => {
    const widget = new GithubDashboardWidget();
    root.innerHTML = await widget.render();
  });

  return <div ref={root} class="panel" />;
};
