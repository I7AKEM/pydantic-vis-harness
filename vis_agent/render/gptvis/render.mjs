import { readFileSync } from 'node:fs';
import { writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { makeFormatter } from './format.js';

const plain = value => value !== null && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype;
function deepMerge(base, overrides) {
  const merged = { ...base };
  for (const [key, value] of Object.entries(overrides)) {
    if (value !== undefined) merged[key] = plain(value) ? deepMerge(plain(base?.[key]) ? base[key] : {}, value) : value;
  }
  return merged;
}

try {
  const { config, overrides = {}, format, format2, output, trace = false } = JSON.parse(readFileSync(0, 'utf8'));
  const require = createRequire(import.meta.url);
  require.extensions['.css'] = () => {};
  const g2 = require('@antv/g2-ssr');
  const { render } = require('@antv/gpt-vis-ssr');
  const { CanvasRenderingContext2D, createCanvas, loadImage } = require('canvas');
  const formatter = makeFormatter(format), pieLabel = d => `${d.category}: ${formatter(d.value)}`;
  const formatter2 = makeFormatter(format2);
  const ours = new WeakSet([formatter, formatter2, pieLabel]), functionPaths = [], formatPaths = [], texts = [];
  let captured = null;
  function applyFormat(options, path = '', activeFormatter = formatter) {
    if (overrides.labels?.length === 0) options.labels = [];
    if (overrides.legend === false) options.legend = false;
    if (overrides.legend === true) delete options.legend;
    for (const [key, axis] of Object.entries(options.axis || {})) {
      if ((key === 'y' || /^position\d*$/.test(key)) && plain(axis)) {
        axis.labelFormatter = activeFormatter;
        formatPaths.push(`${path}axis.${key}.labelFormatter`);
      }
    }
    for (const [i, label] of (options.labels || []).entries()) {
      if (label.text === 'value' || (typeof label.text === 'string' && label.text === options.encode?.y)) {
        label.formatter = activeFormatter; formatPaths.push(`${path}labels.${i}.formatter`);
      }
    }
    if (options.coordinate?.type === 'theta' && options.labels?.length) {
      options.labels[0].text = pieLabel;
      formatPaths.push(`${path}labels.0.text`);
    }
    for (const [i, child] of (options.children || []).entries()) {
      if (child.scale?.y && overrides.scale?.y) child.scale.y = deepMerge(child.scale.y, overrides.scale.y);
      const dual = config.type === 'dual-axes' && path === '';
      if (dual && i === 0 && config.axisYTitle != null) child.axis.y.title = config.axisYTitle;
      applyFormat(child, `${path}children.${i}.`, dual && i === 1 ? formatter2 : activeFormatter);
    }
  }
  function toJsonSafe(value, path = '') {
    if (typeof value === 'function') {
      if (ours.has(value)) return value === pieLabel ? { $label: 'category_value' } : { $format: value === formatter2 ? 'value2' : 'value' };
      functionPaths.push(path);
      return { $function: path };
    }
    if (Array.isArray(value)) return value.map((item, i) => toJsonSafe(item, `${path}.${i}`));
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
      .map(([key, item]) => [key, toJsonSafe(item, path ? `${path}.${key}` : key)]));
    return value;
  }
  const original = g2.createChart;
  g2.createChart = async options => {
    if (typeof options.title === 'string' && overrides.title) options.title = { title: options.title };
    const merged = deepMerge(options, overrides);
    applyFormat(merged);
    captured = toJsonSafe(merged);
    return original(merged);
  };
  if (trace) {
    const fillText = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function (text, ...args) {
      texts.push(String(text));
      return fillText.call(this, text, ...args);
    };
  }
  const start = performance.now();
  const vis = await render(config);
  let buffer;
  try { buffer = vis.toBuffer(); } finally { vis.destroy(); }
  const renderMs = performance.now() - start;
  await writeFile(process.argv[2] || output, buffer);
  const picture = await loadImage(buffer), { width, height } = picture;
  const context = createCanvas(width, height).getContext('2d');
  context.drawImage(picture, 0, 0);
  const { data } = context.getImageData(0, 0, width, height);
  let changed = 0, sampled = 0;
  for (let y = 0; y < height; y += 4) for (let x = 0; x < width; x += 4) {
    const i = (y * width + x) * 4;
    if ([0, 1, 2].some(c => Math.abs(data[i + c] - data[c]) > 8)) changed++;
    sampled++;
  }
  console.log(JSON.stringify({ renderMs, width, height, bytes: buffer.length,
    nonBackgroundShare: changed / sampled, g2: captured, functionPaths, formatPaths, texts }));
} catch (error) {
  console.error(JSON.stringify({ error: String(error.message || error) }));
  process.exitCode = 1;
}
