// The existing adapter's static card drawing path. All number strings come
// from Python; this file only measures and paints text.
export function drawIndicator(config, createCanvas) {
  const width = config.width ?? (config.cards?.length === 1 ? 460 : 800), ratio = 3, maxHeight = 2400;
  if (!Number.isInteger(width) || width < 240 || width > 2400 ||
      (config.height != null && (!Number.isInteger(config.height) || config.height < 160 || config.height > maxHeight))) {
    throw new Error('indicator dimensions must be width 240–2400 and height 160–2400');
  }
  if (!Array.isArray(config.cards) || config.cards.length < 1 || config.cards.length > 6) {
    throw new Error('an indicator requires one to six cards');
  }
  const measuring = createCanvas(width, 1).getContext('2d');
  const dark = config.theme === 'dark', rtl = config.direction === 'rtl';
  const ink = dark ? '#f3f5f9' : '#182435', muted = dark ? '#bac6d7' : '#506176';
  const surface = dark ? '#202938' : '#ffffff', border = dark ? '#465368' : '#d5deeb';
  const accent = config.accent || (dark ? '#91b7ff' : '#2265c5');
  const margin = 20, gap = 16, padding = 20;
  const count = config.cards.length;
  const normalizedLabel = text => String(text ?? '').normalize('NFKC').trim().replace(/\s+/g, ' ').toLowerCase();
  const columns = count === 1 ? 1 : width >= 1100 && count >= 3 ? 3 : width >= 620 ? 2 : 1;
  const cardWidth = (width - margin * 2 - (columns - 1) * gap) / columns;
  const innerWidth = cardWidth - padding * 2;
  if (innerWidth < 110) throw new Error('indicator width leaves insufficient space for metric text');
  const font = (size, bold = false) => `${bold ? '600' : '400'} ${size}px sans-serif`;
  const painted = (text, role, direction) => {
    if (direction === 'ltr') return `\u202d${text}\u202c`;
    if (['value', 'support', 'exact'].includes(role)) {
      // Isolate the number, not its unit: LRO over an Arabic unit would reverse
      // its letters. Include exponent signs and % in the protected run.
      return text.replace(/^([+\-]?[0-9٠-٩٬٫,.]+(?:[eE][+\-]?[0-9٠-٩]+)?[KMB]?%?)/u,
        numeric => `\u202d${numeric}\u202c`);
    }
    return text;
  };
  const measure = (text, size, bold) => {
    measuring.font = font(size, bold);
    return measuring.measureText(text).width;
  };
  const wrap = (text, size, bold, limit) => {
    const lines = [];
    for (const paragraph of String(text).split('\n')) {
      let line = '';
      for (const word of paragraph.split(/\s+/).filter(Boolean)) {
        if (measure(word, size, bold) > limit) throw new Error('indicator contains a label too wide for the requested dimensions');
        const next = line ? `${line} ${word}` : word;
        if (line && measure(next, size, bold) > limit) { lines.push(line); line = word; }
        else line = next;
      }
      if (line) lines.push(line);
    }
    return lines;
  };
  const header = [], planned = [];
  let headerHeight = margin;
  const duplicateTitle = count === 1 && normalizedLabel(config.cards[0].value.label) === normalizedLabel(config.title);
  for (const [text, size, bold] of [[duplicateTitle ? null : config.title, count === 1 ? 20 : 24, true],
    [config.subtitle, 15, false], [count === 1 ? null : config.description, 13, false]]) {
    if (!text) continue;
    for (const line of wrap(text, size, bold, width - margin * 2)) {
      header.push({ text: line, size, bold, top: headerHeight, role: 'title' });
      headerHeight += size * 1.4;
    }
    headerHeight += 5;
  }
  if (header.length) headerHeight += 14;
  for (const [index, card] of config.cards.entries()) {
    let y = padding;
    const blocks = [];
    const add = (text, size, bold, role, column, allowWrap = true, direction = null) => {
      let lines;
      if (allowWrap) lines = wrap(text, size, bold, innerWidth);
      else {
        // Metric digits are never clipped, ellipsized, or split across lines.
        const minimum = role === 'value' ? 22 : 12;
        const drawText = painted(text, role, direction);
        while (measure(drawText, size, bold) > innerWidth && size > minimum) size -= 1;
        if (measure(drawText, size, bold) > innerWidth) throw new Error('indicator metric cannot fit legibly in the requested dimensions');
        lines = [text];
      }
      for (const line of lines) {
        blocks.push({ text: line, size, bold, top: y, role, card: index, column, direction });
        y += size * 1.4;
      }
    };
    const addMetric = (metric, size, role) => {
      const text = role === 'exact' ? metric.exactNumber : metric.number;
      const unitText = metric.unitLabel;
      const bold = role !== 'exact', unitSize = role === 'value' ? 18 : 12;
      const metricGap = unitText ? 7 : 0;
      const unitWidth = unitText ? measure(unitText, unitSize, false) : 0;
      const drawText = painted(text, role, null);
      const minimum = role === 'value' ? 22 : 12;
      while (measure(drawText, size, bold) + metricGap + unitWidth > innerWidth && size > minimum) size -= 1;
      if (measure(drawText, size, bold) + metricGap + unitWidth > innerWidth) {
        throw new Error('indicator metric and unit cannot fit legibly in the requested dimensions');
      }
      blocks.push({ text, size, bold, top: y, role, card: index, column: metric.column,
        unit: unitText ? { text: unitText, size: unitSize, bold: false,
          role: role === 'value' ? 'unit' : `${role}_unit`, gap: metricGap } : null });
      y += Math.max(size, unitSize) * 1.35;
    };
    add(card.value.label, 15, false, 'label', card.value.column);
    for (const context of card.context) {
      y += 6;
      add(context.label, 12, false, 'label', context.column);
      // Numeric dates are a single left-to-right token, even in an RTL card.
      // Keeping the value separate prevents Arabic context labels from making
      // ١٤٤٧-٠٩ appear as ٠٩-١٤٤٧ without parsing a non-Gregorian date.
      const direction = /^[\p{N}TZ :./+\-]+$/u.test(context.text) ? 'ltr' : null;
      add(context.text, 14, false, 'context', context.column, true, direction);
    }
    y += 8;
    addMetric(card.value, count === 1 ? 42 : 34, 'value');
    if (card.value.exactNumber) {
      y += 4;
      add(config.language === 'ar' ? 'القيمة الدقيقة' : 'Exact value', 12, false, 'label', card.value.column);
      addMetric(card.value, 13, 'exact');
    }
    for (const support of card.support) {
      y += 12;
      add(support.label, 13, false, 'label', support.column);
      addMetric(support, 17, 'support');
      if (support.exactNumber) addMetric(support, 12, 'exact');
    }
    const redundantDescription = [card.value.label, config.title].some(
      heading => normalizedLabel(heading) === normalizedLabel(config.description));
    if (count === 1 && config.description && !redundantDescription) {
      y += 12;
      add(config.description, 12, false, 'description', null);
    }
    planned.push({ blocks, height: y + padding });
  }
  const rows = Math.ceil(count / columns), rowHeights = [];
  for (let row = 0; row < rows; row++) rowHeights.push(Math.max(...planned.slice(row * columns, (row + 1) * columns).map(card => card.height)));
  const required = Math.ceil(headerHeight + rowHeights.reduce((sum, height) => sum + height, 0) + (rows - 1) * gap + margin);
  const height = config.height ?? Math.max(count === 1 ? 180 : 260, required);
  if (height < required || height > maxHeight) throw new Error(`indicator needs at least ${required}px height to keep all metric and context text readable`);
  const canvas = createCanvas(width * ratio, height * ratio), ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);
  ctx.fillStyle = config.background || (dark ? '#141b26' : '#f3f6fb');
  ctx.fillRect(0, 0, width, height);
  // Header color follows its actual background, including a custom background.
  const pixel = ctx.getImageData(0, 0, 1, 1).data;
  const linear = value => value / 255 <= .04045 ? value / 255 / 12.92 : ((value / 255 + .055) / 1.055) ** 2.4;
  const lightBackground = linear(pixel[0]) * .2126 + linear(pixel[1]) * .7152 + linear(pixel[2]) * .0722 > .179;
  const headerInk = config.background ? (lightBackground ? '#000000' : '#ffffff')
    : (lightBackground ? '#182435' : '#f3f5f9');
  const texts = [], textBounds = [], cardBounds = [];
  function paint(block, left, top, available, color) {
    const { text, size, bold } = block;
    if (block.unit) {
      const numericWidth = measure(painted(text, block.role, block.direction), size, bold);
      const unitWidth = measure(block.unit.text, block.unit.size, false);
      // A percent sign belongs to the LTR numeric run, even in an RTL card.
      // Count nouns remain separate and retain the surrounding text direction.
      const percent = block.unit.text === '%';
      const numericLeft = rtl ? left + available - numericWidth - (percent ? unitWidth + block.unit.gap : 0) : left;
      paint({ ...block, unit: null }, numericLeft, top, numericWidth, color);
      const unitLeft = rtl && !percent ? numericLeft - block.unit.gap - unitWidth : numericLeft + numericWidth + block.unit.gap;
      paint({ ...block.unit, top: block.top + size - block.unit.size, card: block.card, column: block.column },
        unitLeft, top, unitWidth, muted);
      return;
    }
    ctx.font = font(size, bold);
    ctx.direction = block.direction || (rtl ? 'rtl' : 'ltr');
    ctx.textAlign = rtl ? 'right' : 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = color;
    const x = rtl ? left + available : left, y = top + block.top + size;
    // Pango-backed canvas versions do not all honor context.direction.
    const paintedText = painted(text, block.role, block.direction);
    const measured = ctx.measureText(paintedText);
    const bounds = { x: (x - measured.actualBoundingBoxLeft) * ratio,
      y: (y - measured.actualBoundingBoxAscent) * ratio,
      width: (measured.actualBoundingBoxLeft + measured.actualBoundingBoxRight) * ratio,
      height: (measured.actualBoundingBoxAscent + measured.actualBoundingBoxDescent) * ratio };
    if (bounds.x < 0 || bounds.y < 0 || bounds.x + bounds.width > width * ratio || bounds.y + bounds.height > height * ratio) {
      throw new Error('indicator text would fall outside the canvas');
    }
    ctx.fillText(paintedText, x, y);
    texts.push(text);
    textBounds.push({ ...bounds, text, paintedText, role: block.role, card: block.card ?? null, column: block.column ?? null });
  }
  for (const block of header) paint(block, margin, 0, width - margin * 2, headerInk);
  let rowTop = headerHeight;
  for (let row = 0; row < rows; row++) {
    for (let position = 0; position < columns; position++) {
      const index = row * columns + position;
      if (index >= count) break;
      const visualPosition = rtl ? columns - position - 1 : position;
      const x = margin + visualPosition * (cardWidth + gap), h = rowHeights[row];
      ctx.fillStyle = surface;
      ctx.fillRect(x, rowTop, cardWidth, h);
      ctx.strokeStyle = border;
      ctx.lineWidth = 1;
      ctx.strokeRect(x + .5, rowTop + .5, cardWidth - 1, h - 1);
      if (config.accent) {
        ctx.fillStyle = accent;
        ctx.fillRect(x, rowTop, cardWidth, 3);
      }
      cardBounds.push({ card: index, x: x * ratio, y: rowTop * ratio, width: cardWidth * ratio, height: h * ratio });
      for (const block of planned[index].blocks) paint(block, x + padding, rowTop, innerWidth,
        ['value', 'support'].includes(block.role) ? ink : muted);
    }
    rowTop += rowHeights[row] + gap;
  }
  return { buffer: canvas.toBuffer('image/png'), width: width * ratio, height: height * ratio,
    logicalWidth: width, logicalHeight: height, texts, textBounds, cardBounds };
}
