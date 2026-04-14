import { chromium } from 'playwright';
import ical from 'ical-generator';
import { createHash } from 'crypto';
import { writeFileSync } from 'fs';

const PORTAL_URL = process.env.VULCAN_URL || 'https://uonetplus.vulcan.net.pl/torun';
const USERNAME = process.env.VULCAN_USERNAME || '';
const PASSWORD = process.env.VULCAN_PASSWORD || '';
const SCHOOL_UNIT_ID = process.env.VULCAN_SCHOOL_UNIT_ID || '002085';

const SYMBOL = PORTAL_URL.replace(/\/$/, '').split('/').pop();
const UCZEN_URL = `https://uonetplus-uczen.vulcan.net.pl/${SYMBOL}/${SCHOOL_UNIT_ID}/App`;

const EXAM_EMOJI = '📝';
const HOMEWORK_EMOJI = '📚';

async function login(page) {
  console.log(`Navigating to ${PORTAL_URL}...`);
  await page.goto(PORTAL_URL, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  console.log('Logging in...');
  await page.fill('#Username', USERNAME);
  await page.fill('#Password', PASSWORD);
  await page.click('button:has-text("ZALOGUJ")');
  await page.waitForTimeout(5000);

  if (page.url().includes('LoginPage')) {
    throw new Error('Login failed - check credentials');
  }
  console.log('Logged in successfully');
}

async function navigateToUczen(page) {
  console.log(`Navigating to Uczeń app...`);
  await page.goto(UCZEN_URL, { waitUntil: 'networkidle' });
  // Wait for the student combobox to be populated (the "{class} {year} - {name}" input).
  await page.waitForFunction(
    () => [...document.querySelectorAll('input')].some(i => /^\S+\s+\d{4}\s+-\s+/.test(i.value || '')),
    null,
    { timeout: 20000 },
  ).catch(() => { /* single-student accounts may not have this combobox */ });
  await page.waitForTimeout(1500);
}

// Student appears in an ExtJS combobox with value like "6B 2025 - Tymon Lachowski".
const STUDENT_VAL_RE = /^\S+\s+\d{4}\s+-\s+(.+)$/;

async function discoverStudents(page) {
  // Find the student combobox by scanning all inputs for one whose current value
  // matches the "{class} {year} - {FirstName} {LastName}" pattern.
  const current = await page.evaluate((reSrc) => {
    const re = new RegExp(reSrc);
    const inputs = [...document.querySelectorAll('input')];
    for (const i of inputs) {
      if (i.value && re.test(i.value)) {
        return { id: i.id, value: i.value };
      }
    }
    return null;
  }, STUDENT_VAL_RE.source);

  if (!current) {
    console.log('No student combobox detected — assuming single-student account');
    return [{ label: null, value: null }];
  }

  // Click to open dropdown, then harvest all option texts.
  await page.click(`#${current.id}`);
  await page.waitForTimeout(1000);

  const options = await page.evaluate((reSrc) => {
    const re = new RegExp(reSrc);
    const out = new Set();
    document.querySelectorAll('*').forEach(el => {
      if (el.children.length) return;
      const t = (el.textContent || '').trim();
      if (re.test(t)) out.add(t);
    });
    return [...out];
  }, STUDENT_VAL_RE.source);

  // Close the dropdown by clicking away.
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);

  const list = (options.length ? options : [current.value]).map(v => {
    const fullName = v.match(STUDENT_VAL_RE)[1].trim();
    return { firstName: fullName.split(/\s+/)[0], value: v };
  });
  console.log(`Found ${list.length} students: ${list.map(s => s.firstName).join(', ')}`);
  return list;
}

async function selectStudent(page, student) {
  if (!student.value) return;
  // Re-open combobox and click the matching option.
  const input = await page.evaluate((reSrc) => {
    const re = new RegExp(reSrc);
    const i = [...document.querySelectorAll('input')].find(x => x.value && re.test(x.value));
    return i ? i.id : null;
  }, STUDENT_VAL_RE.source);

  if (!input) {
    console.warn('Student combobox missing on re-select');
    return;
  }

  const currentVal = await page.inputValue(`#${input}`);
  if (currentVal === student.value) {
    console.log(`Already on ${student.firstName}`);
    return;
  }

  await page.click(`#${input}`);
  await page.waitForTimeout(800);
  await page.click(`text="${student.value}"`);
  await page.waitForTimeout(3000);
  console.log(`Selected student: ${student.firstName}`);
}

function parseDate(dateStr) {
  // DD.MM.YYYY -> Date at UTC midnight so all-day events land on the right day
  const [day, month, year] = dateStr.split('.');
  return new Date(Date.UTC(parseInt(year), parseInt(month) - 1, parseInt(day)));
}

function makeUid(summary, dateStr) {
  return createHash('md5').update(summary + dateStr).digest('hex');
}

async function scrapeExams(page) {
  console.log('Scraping exams...');
  await page.click('button:has-text("Sprawdziany, zadania")');
  await page.waitForTimeout(1000);
  await page.click('button:has-text("Sprawdziany")');
  await page.waitForTimeout(3000);

  const exams = [];

  for (let week = 0; week < 2; week++) {
    const text = await page.innerText('body');
    const lines = text.split('\n');

    let currentDate = null;
    for (const rawLine of lines) {
      const line = rawLine.trim();
      const dateMatch = line.match(/^(\d{2}\.\d{2}\.\d{4})$/);
      if (dateMatch) {
        currentDate = dateMatch[1];
      } else if (
        currentDate &&
        line &&
        line === line.toUpperCase() &&
        line.length > 2 &&
        !['TYDZIEŃ', 'SPRAWDZIAN', 'CZTERY', 'PONIEDZIAŁEK', 'WTOREK',
          'ŚRODA', 'CZWARTEK', 'PIĄTEK', 'ZADANIA', 'KOLEJNY', 'POPRZEDNI',
          'DOMOWE', 'COPYRIGHT'].some(k => line.includes(k))
      ) {
        const key = `${currentDate}:${line}`;
        if (!exams.find(e => `${e.date}:${e.subject}` === key)) {
          exams.push({ date: currentDate, subject: line });
        }
        currentDate = null;
      }
    }

    if (week < 1) {
      const nextBtn = await page.$('button:has-text("Kolejny tydzień")');
      if (nextBtn) {
        await nextBtn.click({ force: true });
        await page.waitForTimeout(2000);
      }
    }
  }

  console.log(`Found ${exams.length} exams`);
  return exams;
}

async function scrapeHomework(page) {
  console.log('Scraping homework...');
  await page.evaluate(() => {
    const btns = document.querySelectorAll('button');
    for (const b of btns) {
      if (b.textContent.trim() === 'Zadania domowe') { b.click(); return; }
    }
  });
  await page.waitForTimeout(3000);

  const homework = [];

  for (let week = 0; week < 2; week++) {
    const text = await page.innerText('body');
    const lines = text.split('\n');

    let currentDate = null;
    for (const rawLine of lines) {
      const line = rawLine.trim();
      const dayMatch = line.match(/^.+,\s+(\d{2}\.\d{2}\.\d{4})$/);
      if (dayMatch) {
        currentDate = dayMatch[1];
      } else if (currentDate && line && !line.includes('Nie zlecono') && line.length > 3
                 && !line.match(/^\w+,\s+\d{2}\.\d{2}\.\d{4}$/)) {
        if (!['Pokaż', 'POPRZEDNI', 'KOLEJNY', 'Copyright', 'Deklaracja',
              'Klauzula', 'Polityka', 'Zmień', 'Zmniejsz', 'Zwiększ',
              'SZKOŁA', 'Witryna', 'Uczeń'].some(k => line.startsWith(k))) {
          const key = `${currentDate}:${line}`;
          if (!homework.find(h => `${h.date}:${h.content}` === key)) {
            homework.push({ date: currentDate, content: line });
          }
        }
      }
    }

    if (week < 1) {
      await page.evaluate(() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
          if (b.textContent.trim() === 'Kolejny tydzień') { b.click(); return; }
        }
      });
      await page.waitForTimeout(2000);
    }
  }

  console.log(`Found ${homework.length} homework items`);
  return homework;
}

function addStudentEvents(cal, firstName, exams, homework) {
  const tag = firstName ? ` (${firstName})` : '';

  for (const exam of exams) {
    const dt = parseDate(exam.date);
    const summary = `${EXAM_EMOJI} ${exam.subject}/sprawdzian${tag}`;
    cal.createEvent({
      id: makeUid(summary, exam.date),
      summary,
      start: dt,
      end: new Date(dt.getTime() + 86400000),
      allDay: true,
      stamp: new Date(),
    });
  }

  for (const hw of homework) {
    const dt = parseDate(hw.date);
    const summary = `${HOMEWORK_EMOJI} ${hw.content}/praca domowa${tag}`;
    cal.createEvent({
      id: makeUid(summary, hw.date),
      summary,
      description: hw.content,
      start: dt,
      end: new Date(dt.getTime() + 86400000),
      allDay: true,
      stamp: new Date(),
    });
  }
}

async function main() {
  if (!USERNAME || !PASSWORD) {
    console.error('Set VULCAN_USERNAME and VULCAN_PASSWORD environment variables');
    process.exit(1);
  }

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const cal = ical({ name: 'vulcan' });

  try {
    await login(page);
    await navigateToUczen(page);
    const students = await discoverStudents(page);

    for (let i = 0; i < students.length; i++) {
      const s = students[i];
      console.log(`\n=== Exporting ${s.firstName || 'student'} (${i + 1}/${students.length}) ===`);
      if (i > 0) await navigateToUczen(page);
      await selectStudent(page, s);
      const exams = await scrapeExams(page);
      const homework = await scrapeHomework(page);
      addStudentEvents(cal, s.firstName, exams, homework);

      if (s.firstName) {
        const perKid = ical({ name: `vulcan ${s.firstName}` });
        addStudentEvents(perKid, s.firstName, exams, homework);
        const fname = `vulcan_${s.firstName.toLowerCase()}.ics`;
        writeFileSync(fname, perKid.toString());
        console.log(`Saved ${fname}`);
      }
    }
  } finally {
    await browser.close();
  }

  writeFileSync('vulcan.ics', cal.toString());
  console.log('Saved vulcan.ics');
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
