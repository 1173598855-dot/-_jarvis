/**
 * J.A.R.V.I.S. Dashboard — Solid.js 入口
 * Phase 9: 赛博朋克 UI 重构
 */

import { render } from 'solid-js/web';
import { App } from './App';
import './styles/global.css';
import './styles/widget.css';

render(() => <App />, document.getElementById('app')!);
