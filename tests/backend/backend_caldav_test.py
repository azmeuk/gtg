import re
from datetime import date, datetime, timedelta
from unittest import TestCase

import vobject
from caldav.lib.error import NotFoundError
from dateutil.tz import UTC
from GTG.backends.backend_caldav import (CATEGORIES, CHILDREN_FIELD,
                                         DAV_IGNORE, PARENT_FIELD, UID_FIELD,
                                         Backend, DueDateField, Translator)
from GTG.core.datastore import Datastore
from GTG.core.dates import LOCAL_TIMEZONE, Date
from GTG.core.tasks import Status
from GTG.core.tasks import Task
from unittest.mock import Mock, patch
from tests.test_utils import MockTimer

NAMESPACE = 'unittest'
VTODO_ROOT = """BEGIN:VTODO\r
CATEGORIES:my first category,my second category\r
COMPLETED:20201212T172558Z\r
CREATED:20201212T092155Z\r
DESCRIPTION;GTGCNTMD5=d48ef99fb21adab7cf5ddd85a4ecf343:my description\r
DTSTAMP:20201212T172830Z\r
LAST-MODIFIED:20201212T172558Z\r
STATUS:NEEDS-ACTION\r
SUMMARY:my summary\r
UID:ROOT\r
END:VTODO\r\n"""
VTODO_CHILD = """BEGIN:VTODO\r
COMPLETED:20201212T172558Z\r
CREATED:20201212T092155Z\r
DTSTAMP:20201212T172830Z\r
LAST-MODIFIED:20201212T172558Z\r
RELATED-TO;RELTYPE=PARENT:ROOT\r
SEQUENCE:1
STATUS:NEEDS-ACTION\r
SUMMARY:my child summary\r
UID:CHILD\r
X-APPLE-SORT-ORDER:1\r
END:VTODO\r\n"""
VTODO_CHILD_PARENT = """BEGIN:VTODO\r
COMPLETED:20201212T172558Z\r
CREATED:20201212T092155Z\r
DTSTAMP:20201212T172830Z\r
LAST-MODIFIED:20201212T172558Z\r
RELATED-TO;RELTYPE=PARENT:ROOT\r
RELATED-TO;RELTYPE=CHILD:GRAND-CHILD\r
SEQUENCE:1\r
STATUS:COMPLETED\r
SUMMARY:my child summary\r
X-APPLE-SORT-ORDER:2\r
UID:CHILD-PARENT\r
END:VTODO\r\n"""
VTODO_GRAND_CHILD = """BEGIN:VTODO\r
COMPLETED:20201212T172558Z\r
CREATED:20201212T092155Z\r
DESCRIPTION:my descriptio\r
DTSTAMP:20201212T172830Z\r
DUE;VALUE=DATE:20201224\r
LAST-MODIFIED:20201212T172558Z\r
RELATED-TO;RELTYPE=PARENT:CHILD-PARENT\r
STATUS:NEEDS-ACTION\r
SUMMARY:my child summary\r
UID:GRAND-CHILD\r
END:VTODO\r\n"""
VTODO_NEW_CHILD = """BEGIN:VTODO\r
COMPLETED:20201212T172558Z\r
CREATED:20201212T092155Z\r
DTSTAMP:20201212T172830Z\r
LAST-MODIFIED:20201212T172558Z\r
RELATED-TO;RELTYPE=PARENT:ROOT\r
SEQUENCE:1
STATUS:NEEDS-ACTION\r
SUMMARY:my new child summary\r
UID:NEW-CHILD\r
X-APPLE-SORT-ORDER:1\r
END:VTODO\r\n"""


class CalDAVTest(TestCase):

    @staticmethod
    def _get_todo(vtodo_raw, parent=None):
        vtodo = vobject.readOne(vtodo_raw)
        todo = Mock()
        todo.instance.vtodo = vtodo
        if parent is None:
            todo.parent.name = 'My Calendar'
        else:
            todo.parent = parent
        return todo

    @staticmethod
    def _setup_backend():
        datastore = Datastore()
        parameters = {'pid': 'favorite', 'service-url': 'color',
                      'username': 'blue', 'password': 'no red', 'period': 1}
        backend = Backend(parameters)
        datastore.register_backend({'backend': backend, 'pid': 'backendid',
                                    'first_run': True})
        return datastore, backend

    @staticmethod
    def _mock_calendar(name='my calendar', url='https://my.fa.ke/calendar'):
        calendar = Mock()
        calendar.name, calendar.url = name, url
        return calendar

    def test_translate_from_vtodo(self):
        datastore, backend = self._setup_backend()
        DESCRIPTION = Translator.fields[1]
        self.assertEqual(DESCRIPTION.dav_name, 'description')
        todo = self._get_todo(VTODO_GRAND_CHILD)
        self.assertEqual(todo.instance.vtodo.serialize(), VTODO_GRAND_CHILD)
        self.assertEqual(date(2020, 12, 24),
                         todo.instance.vtodo.contents['due'][0].value)
        uid = UID_FIELD.get_dav(todo)
        self.assertTrue(isinstance(uid, str), f"should be str is {uid!r}")
        self.assertEqual(uid, UID_FIELD.get_dav(vtodo=todo.instance.vtodo))
        task = Task(uid, Mock())
        Translator.fill_task(todo, task, NAMESPACE, datastore)
        self.assertEqual('date', task.date_due.accuracy.value)
        vtodo = Translator.fill_vtodo(task, todo.parent.name, NAMESPACE)
        for field in Translator.fields:
            if field.dav_name in DAV_IGNORE:
                continue
            self.assertTrue(field.is_equal(task, NAMESPACE, todo), f"{field.get_gtg(task, NAMESPACE)} != {field.get_dav(todo)}")
            self.assertTrue(field.is_equal(task, NAMESPACE, vtodo=vtodo.vtodo), f"{field.get_gtg(task, NAMESPACE)} != {field.get_dav(vtodo=vtodo)}")
        vtodo.vtodo.contents['description'][0].value = 'changed value'
        self.assertTrue(DESCRIPTION.is_equal(task, NAMESPACE, todo), 'same '
                        'hashes should prevent changes on vTodo to be noticed')
        task.content = task.content + 'more content'
        self.assertFalse(DESCRIPTION.is_equal(task, NAMESPACE, todo))

    def test_translate_from_task(self):
        now, today = datetime.now(), date.today()
        task = Task('uuid', Mock())
        task.set_title('holy graal')
        task.content = 'the knights who says ni'
        task.set_recurring(True, 'other-day')
        task.date_start = Date(today)
        task.date_due = 'soon'
        task.set_closed_date(now)
        vtodo = Translator.fill_vtodo(task, 'My Calendar Name', NAMESPACE)
        for field in Translator.fields:
            self.assertTrue(field.is_equal(task, NAMESPACE, vtodo=vtodo.vtodo),
                            f'{field!r} has differing values')
        serialized = vtodo.serialize()
        self.assertTrue(f"DTSTART;VALUE=DATE:{today.strftime('%Y%m%d')}"
                        in serialized, f"missing from {serialized}")
        self.assertTrue(re.search(r"COMPLETED:[0-9]{8}T[0-9]{6}Z",
                                  serialized), f"missing from {serialized}")
        self.assertTrue("DUE;GTGFUZZY=soon" in serialized,
                        f"missing from {serialized}")
        # trying to fill utc only with fuzzy
        task.set_closed_date('someday')
        vtodo = Translator.fill_vtodo(task, 'My Calendar Name', NAMESPACE)
        serialized = vtodo.serialize()
        self.assertTrue("COMPLETED;GTGFUZZY=someday:" in serialized,
                        f"missing from {serialized}")
        # trying to fill utc only with date
        task.set_closed_date(today)
        vtodo = Translator.fill_vtodo(task, 'My Calendar Name', NAMESPACE)
        serialized = vtodo.serialize()
        today_in_utc = now.replace(hour=0, minute=0, second=0)\
            .replace(tzinfo=LOCAL_TIMEZONE).astimezone(UTC)\
            .strftime('%Y%m%dT%H%M%SZ')
        self.assertTrue(f"COMPLETED:{today_in_utc}" in serialized,
                        f"missing {today_in_utc} from {serialized}")
        # emptying date by setting None or no_date
        task.set_closed_date(Date.no_date())
        task.date_due = None
        task.date_start = None
        vtodo = Translator.fill_vtodo(task, 'My Calendar Name', NAMESPACE)
        serialized = vtodo.serialize()
        self.assertTrue("CATEGORIES:" not in serialized)
        self.assertTrue("COMPLETED:" not in serialized)
        self.assertTrue("DUE:" not in serialized)
        self.assertTrue("DTSTART:" not in serialized)

    def test_translate(self):
        datastore = Datastore()
        my_tag = datastore.tags.new('@my-tag')
        my_other_tag = datastore.tags.new('@my-other-tag')
        root_task = datastore.tasks.new('my task')
        child_task = datastore.tasks.new('child-task', parent=root_task.id)

        child_task.title = 'my first child'
        child_task.add_tag(my_tag)
        child_task.add_tag(my_other_tag)
        child_task.content = "@my-tag, @my-other-tag, \n\ntask content"

        child2_task = datastore.tasks.new('done-child-task', parent=root_task.id)
        child2_task.title = 'my done child'
        child2_task.add_tag(my_tag)
        child2_task.add_tag(my_tag)
        child2_task.content = "@my-tag, @my-other-tag, \n\nother task txt"
        child2_task.status = Status.DONE
        root_task.content = (f"@my-tag, @my-other-tag\n\nline\n"
                           f"{{!{child_task.id}!}}\n"
                           f"{{!{child2_task.id}!}}\n")
        self.assertEqual([child_task, child2_task],
                         root_task.children)
        self.assertEqual(root_task, child_task.parent)
        self.assertEqual(None, PARENT_FIELD.get_gtg(root_task, NAMESPACE))
        self.assertEqual([str(child_task.id), str(child2_task.id)],
                         CHILDREN_FIELD.get_gtg(root_task, NAMESPACE))
        self.assertEqual(str(root_task.id),
                         PARENT_FIELD.get_gtg(child_task, NAMESPACE))
        self.assertEqual([], CHILDREN_FIELD.get_gtg(child_task, NAMESPACE))
        root_vtodo = Translator.fill_vtodo(root_task, 'calname', NAMESPACE, datastore=datastore)
        child_vtodo = Translator.fill_vtodo(child_task, 'calname', NAMESPACE, datastore=datastore)
        child2_vtodo = Translator.fill_vtodo(child2_task, 'calname', NAMESPACE, datastore=datastore)
        self.assertEqual(None, PARENT_FIELD.get_dav(vtodo=root_vtodo.vtodo))
        self.assertEqual([str(child_task.id), str(child2_task.id)],
                         CHILDREN_FIELD.get_dav(vtodo=root_vtodo.vtodo))
        self.assertEqual(str(root_task.id),
                         PARENT_FIELD.get_dav(vtodo=child_vtodo.vtodo))
        self.assertEqual([], CHILDREN_FIELD.get_dav(vtodo=child_vtodo.vtodo))
        self.assertTrue('\r\nRELATED-TO;RELTYPE=CHILD:child-task\r\n'
                        in root_vtodo.serialize())
        self.assertTrue('\r\nRELATED-TO;RELTYPE=PARENT:root-task\r\n'
                        in child_vtodo.serialize())
        root_contents = root_vtodo.contents['vtodo'][0].contents
        child_cnt = child_vtodo.contents['vtodo'][0].contents
        child2_cnt = child2_vtodo.contents['vtodo'][0].contents
        for cnt in root_contents, child_cnt, child2_cnt:
            self.assertEqual(['my-tag', 'my-other-tag'],
                             cnt['categories'][0].value)
        self.assertEqual('my first child', child_cnt['summary'][0].value)
        self.assertEqual('my done child', child2_cnt['summary'][0].value)
        self.assertEqual('task content', child_cnt['description'][0].value)
        self.assertEqual('other task txt', child2_cnt['description'][0].value)
        self.assertEqual('line\n[ ] my first child\n[x] my done child',
                         root_contents['description'][0].value)

    @patch('GTG.backends.periodic_import_backend.threading.Timer',
           autospec=MockTimer)
    @patch('GTG.backends.backend_caldav.caldav.DAVClient')
    def test_do_periodic_import(self, dav_client, threading_pid):
        calendar = self._mock_calendar()

        todos = [self._get_todo(VTODO_CHILD_PARENT, calendar),
                 self._get_todo(VTODO_ROOT, calendar),
                 self._get_todo(VTODO_CHILD, calendar),
                 self._get_todo(VTODO_GRAND_CHILD, calendar)]
        calendar.todos.return_value = todos
        dav_client.return_value.principal.return_value.calendars.return_value \
            = [calendar]
        datastore, backend = self._setup_backend()

        self.assertEqual(4, len(datastore.tasks.task_count_all))
        task = datastore.get_task('ROOT')
        self.assertIsNotNone(task)
        self.assertEqual(['CHILD', 'CHILD-PARENT'],
                         [subtask.id for subtask in task.get_subtasks()])
        self.assertEqual(
            0, len(datastore.get_task('CHILD').get_subtasks()))
        self.assertEqual(
            1, len(datastore.get_task('CHILD-PARENT').get_subtasks()))

        def get_todo(uid):
            return next(todo for todo in todos
                        if UID_FIELD.get_dav(todo) == uid)

        for uid, parents, children in (
                ('ROOT', [], ['CHILD', 'CHILD-PARENT']),
                ('CHILD', ['ROOT'], []),
                ('CHILD-PARENT', ['ROOT'], ['GRAND-CHILD'])):
            task = datastore.get_task(uid)
            self.assertEqual(children, CHILDREN_FIELD.get_dav(get_todo(uid)),
                             "children should've been written by sync down")
            self.assertEqual(children, task.get_children(),
                             "children missing from task")
            self.assertEqual(parents, PARENT_FIELD.get_dav(get_todo(uid)),
                             "parent on todo aren't consistent")
            self.assertEqual(parents, task.get_parents(),
                             "parent missing from task")

        calendar.todo_by_uid.return_value = todos[-1]
        todos = todos[:-1]
        child_todo = todos[-1]
        child_todo.instance.vtodo.contents['summary'][0].value = 'new summary'
        calendar.todos.return_value = todos

        # syncing with missing and updated todo, no change
        task = datastore.get_task(child_todo.instance.vtodo.uid.value)
        backend.do_periodic_import()
        self.assertEqual(4, len(datastore.tasks.task_count_all),
                         "no not found raised, no reason to remove tasks")
        self.assertEqual('my child summary', task.get_title(), "title shoul"
                         "dn't have change because sequence wasn't updated")

        # syncing with same data, delete one and edit remaining
        calendar.todo_by_uid.side_effect = NotFoundError
        child_todo.instance.vtodo.contents['sequence'][0].value = '2'
        backend.do_periodic_import()
        self.assertEqual(3, len(datastore.tasks.task_count_all))
        self.assertEqual('new summary', task.get_title())

        # set_task no change, no update
        backend.set_task(task)
        child_todo.save.assert_not_called()
        child_todo.delete.assert_not_called()
        calendar.add_todo.assert_not_called()
        # set_task, with ignorable changes
        task.set_status(Status.DONE)
        backend.set_task(task)
        child_todo.save.assert_called_once()
        calendar.add_todo.assert_not_called()
        child_todo.delete.assert_not_called()
        child_todo.save.reset_mock()
        # no update
        backend.set_task(task)
        child_todo.save.assert_not_called()
        calendar.add_todo.assert_not_called()
        child_todo.delete.assert_not_called()

        # creating task, refused : no tag
        task = datastore.task_factory('NEW-CHILD')
        datastore.push_task(task)
        backend.set_task(task)
        child_todo.save.assert_not_called()
        calendar.add_todo.assert_not_called()
        child_todo.delete.assert_not_called()
        # creating task, accepted, new tag found
        task.add_tag(CATEGORIES.get_calendar_tag(calendar))
        calendar.add_todo.return_value = child_todo
        backend.set_task(task)
        child_todo.save.assert_not_called()
        calendar.add_todo.assert_called_once()
        child_todo.delete.assert_not_called()
        calendar.add_todo.reset_mock()

        backend.remove_task('uid never seen before')
        child_todo.save.assert_not_called()
        calendar.add_todo.assert_not_called()
        child_todo.delete.assert_not_called()

        backend.remove_task('CHILD')
        child_todo.save.assert_not_called()
        calendar.add_todo.assert_not_called()
        child_todo.delete.assert_called_once()

    @patch('GTG.backends.periodic_import_backend.threading.Timer',
           autospec=MockTimer)
    @patch('GTG.backends.backend_caldav.caldav.DAVClient')
    def test_switch_calendar(self, dav_client, threading_pid):
        calendar1 = self._mock_calendar()
        calendar2 = self._mock_calendar('other calendar', 'http://no.whe.re/')

        todo = self._get_todo(VTODO_ROOT, calendar1)
        calendar1.todos.return_value = [todo]
        calendar2.todos.return_value = []
        dav_client.return_value.principal.return_value.calendars.return_value \
            = [calendar1, calendar2]
        datastore, backend = self._setup_backend()
        self.assertEqual(1, len(datastore.tasks.task_count_all))
        task = datastore.get_task(UID_FIELD.get_dav(todo))
        self.assertTrue(CATEGORIES.has_calendar_tag(task, calendar1))
        self.assertFalse(CATEGORIES.has_calendar_tag(task, calendar2))

        task.remove_tag(CATEGORIES.get_calendar_tag(calendar1))
        task.add_tag(CATEGORIES.get_calendar_tag(calendar2))
        self.assertFalse(CATEGORIES.has_calendar_tag(task, calendar1))
        self.assertTrue(CATEGORIES.has_calendar_tag(task, calendar2))

        calendar2.add_todo.return_value = todo
        backend.set_task(task)
        calendar1.add_todo.assert_not_called()
        calendar2.add_todo.assert_called_once()
        todo.delete.assert_called_once()

    @patch('GTG.backends.periodic_import_backend.threading.Timer',
           autospec=MockTimer)
    @patch('GTG.backends.backend_caldav.caldav.DAVClient')
    def test_task_mark_as_done_from_backend(self, dav_client, threading_pid):
        calendar = self._mock_calendar()
        todo = self._get_todo(VTODO_ROOT, calendar)
        calendar.todos.return_value = [todo]
        dav_client.return_value.principal.return_value.calendars.return_value \
            = [calendar]
        datastore, backend = self._setup_backend()
        uid = UID_FIELD.get_dav(todo)
        self.assertEqual(1, len(datastore.tasks.task_count_all))
        task = datastore.get_task(uid)
        self.assertEqual(Status.ACTIVE, task.get_status())
        calendar.todos.assert_called_once()
        calendar.todo_by_uid.assert_not_called()
        calendar.todos.reset_mock()

        todo.instance.vtodo.contents['status'][0].value = 'COMPLETED'
        calendar.todos.return_value = []
        calendar.todo_by_uid.return_value = todo
        backend.do_periodic_import()
        calendar.todos.assert_called_once()
        calendar.todo_by_uid.assert_called_once()

        self.assertEqual(1, len(datastore.tasks.task_count_all))
        task = datastore.get_task(uid)
        self.assertEqual(Status.DONE, task.get_status())

    def test_due_date_caldav_restriction(self):
        task = Task('uid', Mock())
        later = datetime(2021, 11, 24, 21, 52, 45)
        before = later - timedelta(days=1)
        task.date_start = Date(later)
        task.date_due = Date(before)
        field = DueDateField('due', 'date_due')
        self.assertEqual(later, field.get_gtg(task, '').dt_value)

        task.date_start = Date(before)
        task.date_due = Date(later)
        self.assertEqual(later, field.get_gtg(task, '').dt_value)
