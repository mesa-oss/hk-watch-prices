/* Quick diagnostic — shows exactly what WhatsApp Web has available.
   Paste into DevTools console BEFORE running the extractor. */
(() => {
  const msgs = document.querySelectorAll('[data-pre-plain-text]');
  const byDate = {};
  const senders = new Set();
  let oldest = null, newest = null;

  msgs.forEach(el => {
    const meta = el.getAttribute('data-pre-plain-text');
    const m = meta.match(/^\[(\d{1,2}:\d{2}(?::\d{2})?),\s*(\d{1,2}\/\d{1,2}\/\d{4})\]\s*(.+?):\s*$/);
    if (!m) return;
    const [, time, date, sender] = m;
    byDate[date] = (byDate[date] || 0) + 1;
    senders.add(sender);
    const d = new Date(
      date.split('/').reverse().join('-') + 'T' + time.padEnd(8, ':00')
    );
    if (!oldest || d < oldest) oldest = d;
    if (!newest || d > newest) newest = d;
  });

  console.log(`📊 WhatsApp Web has ${msgs.length} messages loaded in the DOM right now`);
  console.log(`📅 Oldest: ${oldest ? oldest.toISOString() : 'n/a'}`);
  console.log(`📅 Newest: ${newest ? newest.toISOString() : 'n/a'}`);
  console.log(`👥 Unique senders: ${senders.size}`);
  console.log(`\n📈 Messages per day:`);
  Object.entries(byDate).sort().forEach(([d, n]) => {
    console.log(`  ${d}: ${n}`);
  });

  if (msgs.length < 200) {
    console.warn(
      '\n⚠️  Only <200 messages loaded. To get more:\n' +
      '  1. Open WhatsApp on your PHONE (not just Web)\n' +
      '  2. Open the WDG group there\n' +
      '  3. Scroll UP slowly — pause every 5 seconds so the server can push older batches\n' +
      '     Keep going until you see messages from a week ago\n' +
      '  4. Come back to Chrome, reload web.whatsapp.com (⌘R)\n' +
      '  5. Reopen WDG in Web — you should see much more history now\n' +
      '  6. Re-run this diagnostic to confirm'
    );
  }
})();
