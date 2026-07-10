import { render } from 'solid-js/web';
import { App } from './App';
import './styles/tokens.css';
import './styles/global.css';
import './styles/widget.css';
import './styles/components.css';

render(() => <App />, document.getElementById('app')!);
