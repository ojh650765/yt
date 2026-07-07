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

function addMonths(date, months) {
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  const day = date.getUTCDate();
  const result = new Date(Date.UTC(year, month + Number(months), 1));
  const lastDay = new Date(Date.UTC(result.getUTCFullYear(), result.getUTCMonth() + 1, 0)).getUTCDate();
  result.setUTCDate(Math.min(day, lastDay));
  return result;
}

function getChargeDate(year, month, day) {
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  return new Date(Date.UTC(year, month, Math.min(Math.max(Number(day) || 1, 1), lastDay)));
}

function getChargeEvents(charges, start, end) {
  const events = [];
  const from = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate()));
  const to = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), end.getUTCDate()));
  const cursor = new Date(Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), 1));
  const endMonth = new Date(Date.UTC(to.getUTCFullYear(), to.getUTCMonth() + 1, 1));

  while (cursor < endMonth) {
    charges.forEach((charge) => {
      const date = getChargeDate(cursor.getUTCFullYear(), cursor.getUTCMonth(), charge.day);
      if (date > from && date <= to) {
        events.push({
          date,
          name: charge.name,
          amount: Number(charge.amount) || 0,
        });
      }
    });
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }

  return events.sort((a, b) => a.date - b.date);
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
      const start = !coverEnd || paidDate > coverEnd ? paidDate : coverEnd;
      coverEnd = addMonths(start, payment.months);
    });

    members.push({
      name,
      daysLeft: Math.round((coverEnd - today) / DAY_MS),
    });
  }

  return members.sort((a, b) => a.daysLeft - b.daysLeft);
}

function computeBalance(balance, today) {
  const charges = Array.isArray(balance.charges) ? balance.charges : [];
  const baseDate = balance.updated ? parseDate(balance.updated) : today;
  const paidEvents = getChargeEvents(charges, baseDate, today);
  const paidTotal = paidEvents.reduce((sum, event) => sum + event.amount, 0);
  const currentAmount = (Number(balance.amount) || 0) - paidTotal;
  const monthlyTotal = charges.reduce((sum, charge) => sum + (Number(charge.amount) || 0), 0);
  const futureEnd = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() + 1, today.getUTCDate()));
  const upcoming = getChargeEvents(charges, today, futureEnd);
  const nextCharge = upcoming[0] || null;

  let runningAmount = currentAmount;
  let insufficiency = null;
  upcoming.forEach((event) => {
    runningAmount -= event.amount;
    if (runningAmount < 0 && !insufficiency) insufficiency = event;
  });

  return {
    currentAmount,
    updated: fmtDate(baseDate),
    today: fmtDate(today),
    paidTotal,
    monthlyTotal,
    upcoming,
    nextCharge,
    insufficiency,
  };
}

function applyBalanceUpdate(balance, balanceStatus, today) {
  if (balanceStatus.paidTotal <= 0) return false;
  balance.amount = balanceStatus.currentAmount;
  balance.updated = fmtDate(today);
  fs.writeFileSync('balance.json', `${JSON.stringify(balance, null, 2)}\n`, 'utf8');
  return true;
}

function formatMemberLine(member) {
  if (member.daysLeft < 0) return `⚫ ${member.name} — ${Math.abs(member.daysLeft)}일 초과`;
  if (member.daysLeft === 0) return `🔴 ${member.name} — 오늘 만료!`;
  return `🟢 ${member.name} — D-${member.daysLeft}`;
}

function formatBalance(balanceStatus) {
  const lines = ['', `💰 INR 잔액: ₹${balanceStatus.currentAmount.toLocaleString()}`];
  lines.push(`   기준: ${balanceStatus.today} KST / 마지막 반영: ${balanceStatus.updated}`);

  if (balanceStatus.paidTotal > 0) {
    lines.push(`   지난 결제 차감: ₹${balanceStatus.paidTotal.toLocaleString()}`);
  }

  if (balanceStatus.upcoming.length > 0) {
    let runningAmount = balanceStatus.currentAmount;
    lines.push('   다음 결제:');
    balanceStatus.upcoming.slice(0, 3).forEach((event) => {
      runningAmount -= event.amount;
      lines.push(`   - ${fmtDate(event.date)} ${event.name} ₹${event.amount.toLocaleString()} → ₹${runningAmount.toLocaleString()}`);
    });
  }

  if (balanceStatus.insufficiency) {
    lines.push(`🚨 잔액 부족! ${fmtDate(balanceStatus.insufficiency.date)} ${balanceStatus.insufficiency.name} ₹${balanceStatus.insufficiency.amount} 결제 불가!`);
  } else if (balanceStatus.nextCharge && balanceStatus.currentAmount < balanceStatus.nextCharge.amount) {
    lines.push(`🚨 잔액 부족! ${fmtDate(balanceStatus.nextCharge.date)} ${balanceStatus.nextCharge.name} ₹${balanceStatus.nextCharge.amount} 결제 불가!`);
  } else if (balanceStatus.currentAmount < balanceStatus.monthlyTotal) {
    lines.push(`⚠️ 이번 달 결제액(₹${balanceStatus.monthlyTotal.toLocaleString()}) 부족 예상`);
  }

  return lines.join('\n');
}

function buildMessage(options = {}) {
  const payments = JSON.parse(fs.readFileSync('data.json', 'utf8'));
  const today = getKstToday();
  const members = computeMembers(payments, today);
  const lines = [
    'YouTube Premium 결제 현황',
    '',
    ...members.map(formatMemberLine),
  ];

  try {
    const balance = JSON.parse(fs.readFileSync('balance.json', 'utf8'));
    const balanceStatus = computeBalance(balance, today);
    lines.push(formatBalance(balanceStatus));
    if (options.writeBalance) applyBalanceUpdate(balance, balanceStatus, today);
  } catch (error) {
    // Keep the D-day notification working even if balance.json is unavailable.
  }

  return lines.join('\n');
}

if (require.main === module) {
  console.log(buildMessage({ writeBalance: process.argv.includes('--write-balance') }));
}

module.exports = {
  addMonths,
  computeBalance,
  computeMembers,
  applyBalanceUpdate,
  getChargeEvents,
  getKstToday,
  parseDate,
  buildMessage,
};
