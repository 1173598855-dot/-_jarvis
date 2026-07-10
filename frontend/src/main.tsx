/**
 * J.A.R.V.I.S. Dashboard — Solid.js 入口
 * Phase 9: 赛博朋克 UI 重构
 */

import { render } from 'solid-js/web';
import { App } from './App';
import './styles/tokens.css';
import './styles/global.css';
import './styles/widget.css';
import './styles/components.css';

render(() => <App />, document.getElementById('app')!);
