import { Component, createSignal, onCleanup, onMount } from 'solid-js';
import { ChatWidget } from './components/ChatWidget';
import { GitWidget } from './components/GitWidget';
import { OllamaMonitorWidget } from './components/OllamaMonitorWidget';
import { SystemMonitorWidget } from './components/SystemMonitorWidget';
import { TokenWidget } from './components/TokenWidget';
import { GithubIntelligenceWidget } from './components/GithubIntelligenceWidget';
import { TokenUsageDashboardWidget } from './components/TokenUsageDashboardWidget';

const navItems = ['Chat', 'Telemetry', 'Repository', 'Models', 'Memory', 'Tools'];

export const App: Component = () => {
  const [time, setTime] = createSignal('');
  let intervalId: number | undefined;

  onMount(() => {
    const updateClock = () => {
      setTime(new Intl.DateTimeFormat('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      }).format(new Date()));
    };
    updateClock();
    intervalId = window.setInterval(updateClock, 1000);
  });

  onCleanup(() => {
    if (intervalId) window.clearInterval(intervalId);
  });

  return (
    <div class="app-shell">
      <aside class="side-rail" aria-label="JARVIS navigation">
        <div class="brand-lockup">
          <div class="brand-mark">J</div>
          <div>
            <div class="brand-name">J.A.R.V.I.S.</div>
            <div class="brand-subtitle">Local AI OS</div>
          </div>
        </div>

        <nav class="nav-list">
          {navItems.map((item) => (
            <button class={`nav-item ${item === 'Chat' ? 'active' : ''}`} type="button">
              <span class="nav-glyph" aria-hidden="true" />
              <span>{item}</span>
            </button>
          ))}
        </nav>

        <div class="rail-footer">
          <div class="rail-label">Protocol</div>
          <div class="rail-value">Phase 10-11</div>
          <div class="rail-label">Runtime</div>
          <div class="rail-value">Solid + Express</div>
        </div>
      </aside>

      <main class="workspace">
        <header class="topbar">
          <div>
            <h1>Command Center</h1>
            <p>Local model chat, system telemetry, and repository state in one control surface.</p>
          </div>
          <div class="topbar-actions">
            <span class="status-pill online">
              <span class="status-dot" />
              Local model online
            </span>
            <span class="clock-readout">{time()}</span>
          </div>
        </header>

        <section class="content-grid" aria-label="JARVIS dashboard">
          <div class="primary-column">
            <ChatWidget />
            <GithubIntelligenceWidget />
            <TokenWidget />
            <TokenUsageDashboardWidget />
          </div>

          <aside class="telemetry-column" aria-label="Telemetry">
            <OllamaMonitorWidget />
            <SystemMonitorWidget />
            <GitWidget />
          </aside>
        </section>
      </main>
    </div>
  );
};
