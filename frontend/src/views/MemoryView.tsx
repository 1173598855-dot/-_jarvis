import * as Dialog from '@kobalte/core/dialog';
import { Plus, Search } from 'lucide-solid';
import {
  For,
  Show,
  createMemo,
  createSignal,
} from 'solid-js';
import { useRuntimeResources } from '../app/runtime-resources';
import { createPollingResource } from '../primitives/create-polling-resource';
import { jarvisApi } from '../services/jarvis-api';
import { ResourceState } from '../components/ui/ResourceState';
import { useToast } from '../components/ui/ToastHost';

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

function tagsFor(entry: { tags?: string[] }) {
  return entry.tags || [];
}

export function MemoryView() {
  const resources = useRuntimeResources();
  const toast = useToast();
  const [query, setQuery] = createSignal('');
  const [typeFilter, setTypeFilter] = createSignal('all');
  const [tagFilter, setTagFilter] = createSignal('');
  const [dialogOpen, setDialogOpen] = createSignal(false);
  const [title, setTitle] = createSignal('');
  const [type, setType] = createSignal('user');
  const [tags, setTags] = createSignal('');
  const [content, setContent] = createSignal('');
  const [saving, setSaving] = createSignal(false);

  const coreAvailable = () => (
    resources.capabilities.data()?.core_api.available === true
  );
  const memories = createPollingResource({
    load: jarvisApi.memories,
    intervalMs: 30_000,
    enabled: coreAvailable,
    classify: (value) => value.entries.length ? 'ready' : 'empty',
  });

  const filteredEntries = createMemo(() => {
    const normalizedQuery = query().trim().toLocaleLowerCase();
    const requiredTags = tagFilter()
      .split(',')
      .map((tag) => tag.trim().toLocaleLowerCase())
      .filter(Boolean);

    return (memories.data()?.entries || []).filter((entry) => {
      const entryTags = tagsFor(entry).map((tag) => tag.toLocaleLowerCase());
      const matchesQuery = !normalizedQuery || [
        entry.title,
        entry.content,
        entry.type,
        ...entryTags,
      ].some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
      const matchesType = typeFilter() === 'all' || entry.type === typeFilter();
      const matchesTags = requiredTags.every((tag) => entryTags.includes(tag));
      return matchesQuery && matchesType && matchesTags;
    });
  });

  const resetForm = () => {
    setTitle('');
    setType('user');
    setTags('');
    setContent('');
  };

  const submitMemory = async (event: SubmitEvent) => {
    event.preventDefault();
    if (!title().trim() || !content().trim() || saving()) return;
    setSaving(true);
    try {
      await jarvisApi.storeMemory({
        type: type(),
        title: title().trim(),
        content: content().trim(),
        tags: tags().split(',').map((tag) => tag.trim()).filter(Boolean),
      });
      await memories.refresh();
      toast.success('记忆已保存');
      setDialogOpen(false);
      resetForm();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '记忆保存失败');
    } finally {
      setSaving(false);
    }
  };

  const capabilityLoading = () => resources.capabilities.phase() === 'loading';

  return (
    <div class="view-stack">
      <header class="view-heading view-heading--with-status">
        <div>
          <h1>记忆</h1>
          <p>浏览、筛选并写入本地结构化记忆。</p>
        </div>
        <Dialog.Root open={dialogOpen()} onOpenChange={setDialogOpen}>
          <Dialog.Trigger
            class="button button--primary memory-create-button"
            disabled={!coreAvailable()}
          >
            <Plus size={16} strokeWidth={1.8} aria-hidden="true" />
            新建记忆
          </Dialog.Trigger>
          <Dialog.Portal>
            <Dialog.Overlay class="dialog-overlay" />
            <div class="dialog-positioner">
              <Dialog.Content class="dialog-content memory-dialog">
                <Dialog.Title class="dialog-title">新建记忆</Dialog.Title>
                <Dialog.Description class="dialog-description">
                  保存到 Core API 管理的本地记忆目录。
                </Dialog.Description>
                <form class="memory-form" onSubmit={submitMemory}>
                  <label>
                    <span>标题</span>
                    <input
                      aria-label="标题"
                      value={title()}
                      onInput={(event) => setTitle(event.currentTarget.value)}
                      required
                    />
                  </label>
                  <label>
                    <span>类型</span>
                    <select
                      aria-label="类型"
                      value={type()}
                      onChange={(event) => setType(event.currentTarget.value)}
                    >
                      <option value="user">user</option>
                      <option value="project">project</option>
                      <option value="system">system</option>
                      <option value="session">session</option>
                    </select>
                  </label>
                  <label>
                    <span>标签</span>
                    <input
                      aria-label="标签"
                      value={tags()}
                      onInput={(event) => setTags(event.currentTarget.value)}
                      placeholder="testing, frontend"
                    />
                  </label>
                  <label>
                    <span>内容</span>
                    <textarea
                      aria-label="内容"
                      value={content()}
                      onInput={(event) => setContent(event.currentTarget.value)}
                      rows={6}
                      required
                    />
                  </label>
                  <div class="dialog-actions">
                    <Dialog.CloseButton class="button button--secondary">
                      取消
                    </Dialog.CloseButton>
                    <button
                      type="submit"
                      class="button button--primary"
                      aria-label="保存记忆"
                      disabled={saving()}
                    >
                      {saving() ? '保存中…' : '保存记忆'}
                    </button>
                  </div>
                </form>
              </Dialog.Content>
            </div>
          </Dialog.Portal>
        </Dialog.Root>
      </header>

      <Show
        when={coreAvailable()}
        fallback={(
          <div class="capability-state" role="status">
            <strong>{capabilityLoading() ? '正在检查 Core API' : 'Core API 未连接'}</strong>
            <span>记忆浏览与写入暂不可用。</span>
          </div>
        )}
      >
        <section class="view-section" aria-labelledby="memory-list-title">
          <div class="section-heading">
            <div>
              <h2 id="memory-list-title">记忆库</h2>
              <p>{memories.data()?.entries.length || 0} 条记录</p>
            </div>
          </div>
          <div class="filter-bar">
            <label class="search-field">
              <Search size={16} strokeWidth={1.8} aria-hidden="true" />
              <input
                aria-label="搜索记忆"
                value={query()}
                onInput={(event) => setQuery(event.currentTarget.value)}
                placeholder="搜索标题、内容或标签"
              />
            </label>
            <select
              aria-label="筛选记忆类型"
              value={typeFilter()}
              onChange={(event) => setTypeFilter(event.currentTarget.value)}
            >
              <option value="all">全部类型</option>
              <option value="user">user</option>
              <option value="project">project</option>
              <option value="system">system</option>
              <option value="session">session</option>
            </select>
            <input
              aria-label="筛选标签"
              value={tagFilter()}
              onInput={(event) => setTagFilter(event.currentTarget.value)}
              placeholder="标签，逗号分隔"
            />
          </div>
          <ResourceState
            phase={memories.phase()}
            title={memories.phase() === 'empty' ? '暂无记忆' : '记忆列表不可用'}
            description={memories.error()?.message}
            onRetry={() => void memories.refresh()}
          >
            <Show
              when={filteredEntries().length > 0}
              fallback={<p class="filtered-empty">没有匹配的记忆</p>}
            >
              <div class="memory-list" role="list">
                <For each={filteredEntries()}>
                  {(entry) => (
                    <article class="memory-row" role="listitem">
                      <div class="memory-row__heading">
                        <div>
                          <span class="memory-row__type">{entry.type}</span>
                          <strong>{entry.title}</strong>
                        </div>
                        <time>{formatDate(entry.created_at)}</time>
                      </div>
                      <p>{entry.content}</p>
                      <Show when={tagsFor(entry).length > 0}>
                        <div class="tag-list" aria-label="标签列表">
                          <For each={tagsFor(entry)}>
                            {(tag) => <code>{tag}</code>}
                          </For>
                        </div>
                      </Show>
                    </article>
                  )}
                </For>
              </div>
            </Show>
          </ResourceState>
        </section>
      </Show>
    </div>
  );
}
