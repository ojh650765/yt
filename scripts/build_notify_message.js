const fs = require('fs');

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

function getKstToday() {
  const now = new Date();
  const kst = new Date(now.getTime() + KST_OFFSET_MS);
  return new Date(Date.UTC(kst.getUTCFullYear(), kst.getUTCMonth(), kst.getUTCDate()));
}

function parseDate(value) {
  const [year, month, day] = String(value).split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function fmtDate(date) {
  return date.toISOString().slice(0, 10);
}

function fmtDday(daysLeft) {
  if (daysLeft < 0) return `D+${Math.abs(daysLeft)}`;
  if (daysLeft === 0) return 'D-Day';
  return `D-${daysLeft}`;
}

function addMonths(date, months) {
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  const day = date.getUTCDate();
  const result = new Date(Date.UTC(year, month + Number(months), 1));
  const lastDay = new Date(Date.UTC(result.getUTCFullYear(), result.getUTCMonth() + 1, 0)).getUTCDate();
  result.setUTCDate(Math.min(day, lastDay));
  return result;
}

function addDays(date, days) {
  return new Date(date.getTime() + (Number(days) || 0) * DAY_MS);
}

function getChargeDate(year, month, day) {
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  return new Date(Date.UTC(year, month, Math.min(Math.max(Number(day) || 1, 1), lastDay)));
}

function getNextChargeDate(day, today) {
  const year = today.getUTCFullYear();
  const month = today.getUTCMonth();
  const thisMonth = getChargeDate(year, month, day);
  return thisMonth > today ? thisMonth : getChargeDate(year, month + 1, day);
}

function computeMembers(payments, today) {
  const groups = {};
  payments.forEach((payment) => {
    if (!groups[payment.name]) groups[payment.name] = [];
    groups[payment.name].push(payment);
  });

  const members = [];
  for (const name in groups) {
    const list = groups[name].sort((a, b) => a.date.localeCompare(b.date));
    let coverEnd = null;

    list.forEach((payment) => {
      const paidDate = parseDate(payment.date);
      if (payment.type === 'conversion') {
        // 요금 전환: 이전 만료일을 버리고 전환일 + 환산 잔여일로 다시 정한다.
        coverEnd = addDays(paidDate, payment.days);
        return;
      }
      const start = !coverEnd || paidDate > coverEnd ? paidDate : coverEnd;
      coverEnd = addDays(addMonths(start, payment.months), payment.days);
    });

    members.push({
      name,
      daysLeft: Math.round((coverEnd - today) / DAY_MS),
    });
  }

  return members.sort((a, b) => a.daysLeft - b.daysLeft);
}

function formatMemberLine(member) {
  if (member.daysLeft < 0) return `⚫ ${member.name} — ${Math.abs(member.daysLeft)}일 초과`;
  if (member.daysLeft === 0) return `🔴 ${member.name} — 오늘 만료!`;
  return `🟢 ${member.name} — D-${member.daysLeft}`;
}

function formatBilling(billing, today) {
  const lines = [''];
  (billing.charges || []).forEach((charge) => {
    const next = getNextChargeDate(charge.day, today);
    const daysLeft = Math.round((next - today) / DAY_MS);
    lines.push(`💴 ${charge.name}: ¥${Number(charge.amount).toLocaleString()}/월`);
    lines.push(`   다음 결제: ${fmtDate(next)} (${fmtDday(daysLeft)})`);
  });
  return lines.join('\n');
}

function buildMessage() {
  const payments = JSON.parse(fs.readFileSync('data.json', 'utf8'));
  const today = getKstToday();
  const members = computeMembers(payments, today);
  const lines = [
    'YouTube Premium 결제 현황',
    '',
    ...members.map(formatMemberLine),
  ];

  try {
    const billing = JSON.parse(fs.readFileSync('billing.json', 'utf8'));
    lines.push(formatBilling(billing, today));
  } catch (error) {
    // Keep the D-day notification working even if billing.json is unavailable.
  }

  return lines.join('\n');
}

if (require.main === module) {
  console.log(buildMessage());
}

module.exports = {
  addDays,
  addMonths,
  computeMembers,
  formatBilling,
  getKstToday,
  getNextChargeDate,
  parseDate,
  buildMessage,
};
