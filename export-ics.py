import logging
import asyncio
import json
import os
import hashlib

from datetime import datetime
from datetime import date
from datetime import timedelta
import pytz

from vulcan import Account
from vulcan import Keystore
from vulcan import Vulcan

from icalendar import Calendar, Event

tz = pytz.timezone('Europe/Warsaw')

async def main():

    with open("keystore.json") as f:
        keystore = Keystore.load(f)
    
    with open("account.json") as f:
        account = Account.load(f)

    client = Vulcan(keystore, account, logging_level=logging.INFO)

    try:
        students = await client.get_students()

        selected_student = [ s for s in students if s.pupil.first_name == os.environ['VULCAN_STUDENT'] ][0]
        client.student = selected_student

        a_week_ago = date.today() + timedelta(days = -7)

        cal_events = []
        exams = await client.data.get_exams(last_sync=a_week_ago)
        for item in [ e async for e in exams ]:
            cal_events.append(exam_to_event(item))

        homework = await client.data.get_homework(last_sync=a_week_ago)
        for item in [ h async for h in homework ]:
            cal_events.append(homework_to_event(item))


        cal_display_name = f'{selected_student.pupil.first_name} {selected_student.pupil.last_name[0]}'
        create_calendar(cal_display_name, cal_events)

        #lessons = await client.get_lessons(date_to = datetime.today + timedelta(days = 14))
    except Exception as e:

        status = getattr(e, 'status')
        message = getattr(e, 'message')
        history = getattr(e, 'history')
        req_info = e.request_info

        print(f'{req_info.method} {req_info.url} ')
        for key in req_info.headers:
            print(f'{key}: {req_info.headers[key]}')

        print(f'{status} {message}\r\n')
        if len(history) > 0:
            print(f'{await history[-1].text("utf-8")}')

        raise
    finally:
        await client.close()

def homework_to_event(homework):
    event = Event()
    summary = f'{homework.subject.name}/praca domowa'
    event.add('summary', summary)
    event.add('dtstart', tz.localize(homework.deadline.date_time))
    event.add('dtend', tz.localize(homework.deadline.date_time + timedelta(days=1)))
    event.add('dtstamp', datetime.utcnow())
    event.add('description', homework.content)
    hashval = summary + str(homework.deadline.date_time)
    event['uid'] = hashlib.md5(hashval.encode('utf-8')).hexdigest()
    return event

def exam_to_event(exam):
    event = Event()
    summary = f'{exam.subject.name}/{exam.type}'
    event.add('summary', summary)
    event.add('dtstart', tz.localize(exam.deadline.date_time))
    event.add('dtend', tz.localize(exam.deadline.date_time + timedelta(days=1)))
    event.add('dtstamp', exam.date_modified.date_time)
    event.add('description', exam.topic)
    hashval = summary + str(exam.deadline.date_time)
    event['uid'] = hashlib.md5(hashval.encode('utf-8')).hexdigest()
    return event

def create_calendar(name, events):
    cal = Calendar()
    cal.add('prodid', name)
    cal.add('version', '2.0')

    for e in events:
        cal.add_component(e)

    with open(f'{name.lower().replace(" ", "_")}.ics', 'wb') as f:
        f.write(cal.to_ical())


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())

