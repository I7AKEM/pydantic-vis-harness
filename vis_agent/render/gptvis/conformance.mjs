import { readFileSync } from 'node:fs';
import { parse } from './node_modules/@antv/gpt-vis/dist/esm/syntax/parser.js';

console.log(JSON.stringify(parse(readFileSync(0, 'utf8'))));
