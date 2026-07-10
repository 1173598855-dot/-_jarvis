import { For, Show } from 'solid-js';
import { RefreshCw } from 'lucide-solid';
import { useRuntimeResources } from '../app/runtime-resources';
import { createPollingResource } from '../primitives/create-polling-resource';
import { jarvisApi } from '../services/jarvis-api';
import { IconButton } from '../components/ui/IconButton';
import { ResourceState } from '../components/ui/ResourceState';
import { StatusIndicator } from '../components/ui/StatusIndicator';

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || '时间不可用';
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function formatTime(value: number | undefined) {
  if (value === undefined) return '尚未刷新';
  return new Date(value).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function RepositoryView() {
  const resources = useRuntimeResources();
  const log = createPollingResource({
    load: (signal) => jarvisApi.gitLog(20, signal),
    intervalMs: 30_000,
    classify: (value) => value.commits.length ? 'ready' : 'empty',
  });
  const status = () => resources.git.data();

  const refresh = () => {
    void resources.git.refresh();
    void log.refresh();
  };

  return (
    <div class="view-stack">
      <header class="view-heading view-heading--with-status">
        <div>
          <h1>代码仓库</h1>
          <p>只读查看分支、工作树变化和提交历史。</p>
        </div>
        <IconButton label="刷新仓库" icon={RefreshCw} onClick={refresh} />
      </header>

      <section class="view-section" aria-labelledby="worktree-title">
        <div class="section-heading">
          <div>
            <h2 id="worktree-title">工作树</h2>
            <p>最后刷新 {formatTime(resources.git.updatedAt())}</p>
          </div>
          <Show when={status()}>
            {(git) => (
              <StatusIndicator
                label={git().clean ? '工作区干净' : `${git().count} 个文件变更`}
                tone={git().clean ? 'success' : 'warning'}
              />
            )}
          </Show>
        </div>
        <ResourceState
          phase={resources.git.phase()}
          title="Git 状态不可用"
          description={resources.git.error()?.message}
          onRetry={() => void resources.git.refresh()}
        >
          <Show when={status()}>
            {(git) => (
              <>
                <div class="repository-branch">
                  <span>当前分支</span>
                  <code>{git().branch}</code>
                </div>
                <Show
                  when={!git().clean}
                  fallback={<p class="repository-clean">没有未提交变更</p>}
                >
                  <div class="changed-files" role="list" aria-label="变更文件">
                    <For each={git().changedFiles}>
                      {(file) => (
                        <div class="changed-file" role="listitem">
                          <code class="changed-file__status">{file.status.trim() || 'M'}</code>
                          <span class="changed-file__path">{file.file}</span>
                          <span class={`changed-file__stage ${file.staged ? 'is-staged' : ''}`}>
                            {file.staged ? '已暂存' : '未暂存'}
                          </span>
                        </div>
                      )}
                    </For>
                  </div>
                </Show>
              </>
            )}
          </Show>
        </ResourceState>
      </section>

      <section class="view-section" aria-labelledby="commit-history-title">
        <div class="section-heading">
          <div>
            <h2 id="commit-history-title">提交历史</h2>
            <p>最近 20 条提交</p>
          </div>
          <time>{formatTime(log.updatedAt())}</time>
        </div>
        <ResourceState
          phase={log.phase()}
          title={log.phase() === 'empty' ? '暂无提交记录' : '提交历史不可用'}
          description={log.error()?.message}
          onRetry={() => void log.refresh()}
        >
          <Show when={log.data()}>
            {(history) => (
              <div class="commit-list" role="list">
                <For each={history().commits}>
                  {(commit) => (
                    <article class="commit-row" role="listitem">
                      <code>{commit.hash}</code>
                      <div>
                        <strong>{commit.subject}</strong>
                        <span>{commit.author} · {formatDate(commit.date)}</span>
                      </div>
                    </article>
                  )}
                </For>
              </div>
            )}
          </Show>
        </ResourceState>
      </section>
    </div>
  );
}
