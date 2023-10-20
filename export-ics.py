import asyncio
import json
import os

from uuid import uuid4
from datetime import datetime
from datetime import date
from datetime import timedelta

from vulcan import Account
from vulcan import Keystore
from vulcan import Vulcan

from icalendar import Calendar, Event

async def main():

    with open("keystore.json") as f:
        keystore = Keystore.load(f)
    
    with open("account.json") as f:
        account = Account.load(f)

    client = Vulcan(keystore, account)

    try:
        students = await client.get_students()

        selected_student = [ s for s in students if s.pupil.first_name == os.environ['VULCAN_STUDENT'] ][0]
        client.student = selected_student

        a_week_ago = date.today() + timedelta(days = -7)

        exams = await client.data.get_exams(last_sync=a_week_ago)
        exams = [ e async for e in exams ]
        
        cal_display_name = f'Sprawdziany {selected_student.class_}'
        create_calendar(cal_display_name, exams, exam_to_event)

        homework = await client.data.get_homework(last_sync=a_week_ago)
        homework = [ h async for h in homework ]
        cal_display_name = f'Praca domowa {selected_student.class_}'
        create_calendar(cal_display_name, homework, homework_to_event)

        #lessons = await client.get_lessons(date_to = datetime.today + timedelta(days = 14))
    finally:
        await client.close()

def homework_to_event(homework):
    event = Event()
    event.add('summary', f'{homework.subject.name} / praca domowa')
    event.add('dtstart', homework.deadline.date_time)
    event.add('dtend', homework.deadline.date_time + timedelta(minutes=45))
    event.add('dtstamp', datetime.utcnow())
    event.add('description', homework.content)
    event['uid'] = str(uuid4())
    return event

def exam_to_event(exam):
    event = Event()
    event.add('summary', f'{exam.subject.name} / {exam.type}')
    event.add('dtstart', exam.deadline.date_time)
    event.add('dtend', exam.deadline.date_time + timedelta(minutes=45))
    event.add('dtstamp', exam.date_modified.date_time)
    event.add('description', exam.topic)
    event['uid'] = str(uuid4())
    return event

def create_calendar(name, items, to_event):
    cal = Calendar()
    cal.add('prodid', name)
    cal.add('version', '2.0')

    for item in items:
        event = to_event(item)
        cal.add_component(event)

    with open(f'{name.lower().replace(" ", "_")}.ics', 'wb') as f:
        f.write(cal.to_ical())


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())

