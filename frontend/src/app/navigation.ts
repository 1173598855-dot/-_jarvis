import MonitorActivity from 'lucide-solid/icons/activity';
import Bot from 'lucide-solid/icons/bot';
import Boxes from 'lucide-solid/icons/boxes';
import GitBranch from 'lucide-solid/icons/git-branch';
import MemoryStick from 'lucide-solid/icons/memory-stick';
import MessageSquare from 'lucide-solid/icons/message-square';

export type ViewId =
  | 'chat'
  | 'runtime'
  | 'repository'
  | 'models'
  | 'memory'
  | 'plugins';

export const navigation = [
  { id: 'chat', label: '对话', icon: MessageSquare, mobile: 'primary' },
  { id: 'runtime', label: '运行监控', icon: MonitorActivity, mobile: 'primary' },
  { id: 'repository', label: '代码仓库', icon: GitBranch, mobile: 'primary' },
  { id: 'models', label: '本地模型', icon: Bot, mobile: 'more' },
  { id: 'memory', label: '记忆', icon: MemoryStick, mobile: 'more' },
  { id: 'plugins', label: '插件与工具', icon: Boxes, mobile: 'more' },
] as const;

export function navigationItem(view: ViewId) {
  return navigation.find((item) => item.id === view) || navigation[0];
}
