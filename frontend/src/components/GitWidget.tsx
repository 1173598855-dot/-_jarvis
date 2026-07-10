import { Component, createSignal, onCleanup, onMount } from 'solid-js';

interface GitStatus {
  branch: string;
  clean: boolean;
  changedFiles: Array<{ status: string; file: string; staged: boolean }>;
  count: number;
}

interface GitCommit {
  hash: string;
  author: string;
  email: string;
  date: string;
  subject: string;
}

export const GitWidget: Component = () => {
  const [status, setStatus] = createSignal<GitStatus | null>(null);
  const [commits, setCommits] = createSignal<GitCommit[]>([]);
  let intervalId: number | undefined;

  const normalizeStatus = (raw: string) => raw.trim() || 'M';

  const fetchStatus = async () => {
    try {
      const [statusRes, logRes] = await Promise.all([
        fetch('/api/git/status'),
        fetch('/api/git/log?limit=4'),
      ]);
      if (statusRes.ok) setStatus(await statusRes.json());
      if (logRes.ok) {
        const data = await logRes.json();
        setCommits(data.commits || []);
      }
    } catch (err) {
      console.error('[GitWidget] fetch failed:', err);
    }
  };

  onMount(() => {
    fetchStatus();
    intervalId = window.setInterval(fetchStatus, 15000);
  });

  onCleanup(() => {
    if (intervalId) window.clearInterval(intervalId);
  });

  return (
    <section class="panel compact-panel">
      <div class="panel-header">
        <div>
          <p class="eyebrow">Repository</p>
          <h2>Git</h2>
        </div>
        <button class="icon-button" type="button" onClick={fetchStatus} title="Refresh Git status">
          <span aria-hidden="true">R</span>
        </button>
      </div>

      {status() ? (
        <>
          <div class="split-status">
            <span class="branch-pill">{status()!.branch}</span>
            <span class={`status-pill ${status()!.clean ? 'online' : 'warning'}`}>
              <span class="status-dot" />
              {status()!.clean ? 'Clean' : `${status()!.count} changes`}
            </span>
          </div>

          {!status()!.clean && (
            <div class="file-list">
              {status()!.changedFiles.slice(0, 6).map((file) => (
                <div class="file-row">
                  <span class="file-status">{normalizeStatus(file.status)}</span>
                  <span class="file-name">{file.file}</span>
                  {file.staged && <span class="file-flag">staged</span>}
                </div>
              ))}
            </div>
          )}

          <div class="commit-list">
            {commits().map((commit) => (
              <div class="commit-row">
                <span class="commit-hash">{commit.hash}</span>
                <span class="commit-subject">{commit.subject}</span>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div class="loading-state">Loading repository state...</div>
      )}
    </section>
  );
};
