export interface StatusIndicatorProps {
  label: string;
  tone?: 'success' | 'warning' | 'error' | 'neutral';
  compact?: boolean;
}

export function StatusIndicator(props: StatusIndicatorProps) {
  return (
    <span
      class={`status-indicator status-indicator--${props.tone || 'neutral'} ${props.compact ? 'status-indicator--compact' : ''}`}
    >
      <span class="status-indicator__dot" aria-hidden="true" />
      <span>{props.label}</span>
    </span>
  );
}
