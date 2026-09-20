// Display-only callbacks, shared by server rendering and the exported interactive page.
export function makeDisplay(display = {}, formatter = String, formatter2 = formatter) {
  const descriptors = new WeakMap();
  const fields = display.fields || {}, columns = display.columns || {};
  const columnLabel = field => Object.hasOwn(columns, field) ? columns[field] : field;
  const label = (field, value) => value != null && Object.hasOwn(fields, field)
    && Object.hasOwn(fields[field], String(value)) ? fields[field][String(value)] : value;
  const cell = (datum, field) => datum && Object.hasOwn(datum, field) ? datum[field]
    : datum?.data && Object.hasOwn(datum.data, field) ? datum.data[field]
    : field === 'name' ? datum?.path?.at(-1) : undefined;
  function callback(desc) {
    const { kind, field } = desc;
    let fn;
    if (kind === 'value') fn = value => label(field, value);
    if (kind === 'datum') fn = datum => label(field, cell(datum, field));
    if (kind === 'pie') fn = datum => `${label('category', datum.category)}: ${formatter(datum.value)}`;
    if (kind === 'constant') fn = () => desc.value;
    if (kind === 'column') fn = value => columnLabel(String(value));
    if (kind === 'tick') fn = (_, index) => !(desc.index !== 0 && index === 0);
    if (kind === 'tooltip') fn = datum => {
      const raw = cell(datum, field), value = label(field, raw);
      return { name: columnLabel(field),
        value: desc.numeric && typeof raw === 'number'
          ? (desc.numeric === 'value2' ? formatter2 : formatter)(raw) : value };
    };
    if (!fn) throw new Error(`Unknown display callback: ${kind}`);
    descriptors.set(fn, desc);
    return fn;
  }
  return { label, callback, descriptor: fn => descriptors.get(fn) };
}

export function applyDisplay(options, display, callbacks, chartType, inherited = {}) {
  const fields = display.fields || {}, columns = display.columns || {};
  const encode = { ...inherited, ...options.encode };
  const categorical = field => typeof field === 'string' && Object.hasOwn(fields, field);
  const make = callbacks.callback;
  for (const channel of ['x', 'y']) {
    const field = encode[channel];
    if (categorical(field) && options.axis !== false) {
      options.axis ||= {};
      if (options.axis[channel] !== false) {
        options.axis[channel] = { ...options.axis[channel], labelFormatter: make({ kind: 'value', field }) };
        if (Array.isArray(options.data) && options.data.some(row => typeof row[field] === 'number')) {
          options.scale ||= {};
          options.scale[channel] = { type: ['interval', 'boxplot'].includes(options.type) ? 'band' : 'point', ...options.scale[channel] };
        }
      }
    }
  }
  const color = encode.color;
  if (categorical(color) && options.legend !== false && options.legend?.color !== false) {
    options.legend = { ...options.legend, color: { ...options.legend?.color,
      title: columns[color] || false, labelFormatter: make({ kind: 'value', field: color }) } };
  }
  for (const label of options.labels || []) {
    if (categorical(label.text)) label.formatter = make({ kind: 'value', field: label.text });
  }
  if (options.type === 'treemap' && fields.name) {
    options.style = { ...options.style, labelText: make({ kind: 'datum', field: 'name' }) };
  }
  if (options.type === 'wordCloud' && fields.text) {
    // Layout measures the translated glyphs; color identity remains the original word.
    options.data = options.data.map(row => ({ ...row, __vis_raw_text: row.text }));
    options.encode.color = '__vis_raw_text';
    options.layout = { ...options.layout, text: make({ kind: 'datum', field: 'text' }) };
  }
  if (options.coordinate?.type === 'radar') {
    for (const [index, field] of (encode.position || []).entries()) {
      const axis = options.axis[`position${index || ''}`];
      axis.title = callbacks.label('name', field);
      axis.tickFilter = make({ kind: 'tick', index });
    }
  }
  if (chartType === 'dual-axes' && typeof options.encode?.color === 'function') {
    const field = options.encode.y;
    options.encode.color = make({ kind: 'constant', value: field });
    if (options.axis.y.title === field) options.axis.y.title = columns[field] || field;
    options.legend = { ...options.legend, color: { ...options.legend?.color,
      itemMarker: options.type === 'line' ? 'smooth' : 'rect',
      labelFormatter: make({ kind: 'column' }) } };
  }
  const tooltipFields = [...new Set([encode.x, encode.y, encode.color]
    .filter(field => typeof field === 'string' && (Object.hasOwn(columns, field) || categorical(field))))];
  if (options.tooltip !== false && tooltipFields.length) {
    const titleField = [encode.x, encode.color].find(categorical);
    options.tooltip = { ...options.tooltip,
      ...(titleField ? { title: make({ kind: 'datum', field: titleField }) } : {}),
      items: tooltipFields.map(field => make({ kind: 'tooltip', field,
        numeric: field === encode.y ? (chartType === 'dual-axes' && options.type === 'line' ? 'value2' : 'value') : undefined })) };
  }
  for (const child of options.children || []) applyDisplay(child, display, callbacks, chartType, encode);
}
