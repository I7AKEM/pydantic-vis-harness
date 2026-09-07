// Shared by the server renderer and the standalone page.
export function makeFormatter(desc) {
  const { thousands = true, decimals = null, compact = false, unit = null, digits = 'western' } = desc || {};
  const arabic = ['٠', '١', '٢', '٣', '٤', '٥', '٦', '٧', '٨', '٩'];
  const toDigits = s => digits === 'arabic'
    ? s.replace(/[0-9]/g, d => arabic[+d]).replace(/,/g, '٬').replace(/\./g, '٫') : s;
  return value => {
    if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return String(value ?? '');
    let n = Number(value), suffix = '';
    if (compact && Math.abs(n) >= 1000) {
      for (const [label, size] of [['B', 1e9], ['M', 1e6], ['K', 1e3]]) {
        if (Math.abs(n) >= size) { n /= size; suffix = label; break; }
      }
    }
    let text = decimals === null
      ? (Number.isInteger(n) ? String(n) : n.toFixed(suffix ? 1 : 2).replace(/\.?0+$/, ''))
      : n.toFixed(decimals);
    if (thousands) {
      const [i, f] = text.split('.');
      text = i.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (f ? '.' + f : '');
    }
    text += suffix;
    if (unit) text += unit === '%' ? '%' : ' ' + unit;
    return toDigits(text);
  };
}
