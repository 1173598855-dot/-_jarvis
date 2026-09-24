import remarkGfm from 'remark-gfm';
import { SolidMarkdown } from 'solid-markdown';

export interface MarkdownContentProps {
  content: string;
}

export function MarkdownContent(props: MarkdownContentProps) {
  return (
    <SolidMarkdown
      children={props.content}
      renderingStrategy="reconcile"
      remarkPlugins={[remarkGfm]}
      skipHtml
    />
  );
}
