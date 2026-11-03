import os
import time
import unittest
import warnings
from unittest import mock

from app.services.editor_tasks import TASKS, TaskRegistry


def received(socket_client):
    return [event['args'][0] for event in socket_client.get_received() if event['name'] == 'editor_task']


class RegistryThrottleTest(unittest.TestCase):
    def setUp(self):
        self.registry = TaskRegistry(interval=0.1)
        self.seen = []
        self.registry.subscribe(lambda task: self.seen.append(dict(task.public())))
        self.task = self.registry.create('me', 'ocr', 'file', 0)

    def test_burst_is_throttled_and_last_value_delivered(self):
        for step in range(1, 51):
            self.registry.update(self.task.id, progress=step / 50)
        self.assertLessEqual(len(self.seen), 3)
        time.sleep(0.25)
        self.assertEqual(self.seen[-1]['progress'], 1.0)
        self.assertLessEqual(len(self.seen), 4)

    def test_rate_stays_under_ten_per_second(self):
        until = time.monotonic() + 0.6
        step = 0
        while time.monotonic() < until:
            step += 1
            self.registry.update(self.task.id, progress=step / 1000)
            time.sleep(0.004)
        time.sleep(0.2)
        self.assertLessEqual(len(self.seen), 1 + 1 + 7 + 1)
        self.assertEqual(self.seen[-1]['progress'], step / 1000)

    def test_stage_status_and_final_are_never_dropped(self):
        self.registry.update(self.task.id, progress=0.1)
        self.registry.update(self.task.id, progress=0.2)
        self.registry.update(self.task.id, stage='detect')
        self.registry.update(self.task.id, progress=0.3)
        self.registry.update(self.task.id, stage='recognize')
        self.registry.finish(self.task.id)
        stages = [item['stage'] for item in self.seen]
        self.assertIn('detect', stages)
        self.assertIn('recognize', stages)
        self.assertEqual(self.seen[-1]['status'], 'done')
        self.assertEqual(self.seen[-1]['progress'], 1.0)
        count = len(self.seen)
        time.sleep(0.2)
        self.assertEqual(len(self.seen), count)

    def test_updates_after_final_are_ignored(self):
        self.registry.finish(self.task.id, 'failed', {'code': 'err_x', 'message': 'x'})
        self.registry.update(self.task.id, progress=0.5, status='running')
        self.assertEqual(self.registry.get(self.task.id).status, 'failed')
        self.assertIsNone(self.registry.get(self.task.id).progress)

    def test_cancel_sets_flag_for_workers(self):
        self.assertFalse(self.registry.cancel('other', self.task.id))
        self.assertFalse(self.task.cancelled)
        self.assertTrue(self.registry.cancel('me', self.task.id))
        self.assertTrue(self.registry.get(self.task.id).cancelled)
        self.assertEqual(self.seen[-1]['status'], 'cancelled')
        self.assertFalse(self.registry.cancel('me', self.task.id))


class SocketOwnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        warnings.filterwarnings('ignore')
        from app import create_app
        from app.routes.websocket import socketio
        cls.app = create_app()
        cls.socketio = socketio

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {'OMNICONV_TEST_ROUTES': '1'})
        self.env.start()
        self.http = [self.app.test_client(), self.app.test_client()]
        for client in self.http:
            client.get('/api/pdf/edit/tasks')
        self.sockets = [self.socketio.test_client(self.app, flask_test_client=client) for client in self.http]
        self.joins = [socket.emit('editor_join', {}, callback=True) for socket in self.sockets]

    def tearDown(self):
        for socket in self.sockets:
            socket.disconnect()
        self.env.stop()

    def drive(self, client, **body):
        return client.post('/api/pdf/edit/tasks/test', json=body).get_json()['data']

    def test_join_requires_valid_cookie(self):
        self.assertEqual(self.joins, [{'joined': True}, {'joined': True}])
        anonymous = self.socketio.test_client(self.app)
        self.assertEqual(anonymous.emit('editor_join', {}, callback=True), {'joined': False})
        anonymous.disconnect()

    def test_task_events_reach_only_the_owner(self):
        first, second = self.http
        task = self.drive(first, kind='ocr', file_id='f1', page=2)['task']
        self.drive(first, task_id=task['id'], stage='detect', progress=0.4)
        mine = received(self.sockets[0])
        self.assertTrue(mine)
        self.assertTrue(all(item['id'] == task['id'] and 'owner' not in item and 'cancelled' not in item for item in mine))
        self.assertEqual(mine[-1]['stage'], 'detect')
        self.assertEqual(received(self.sockets[1]), [])
        self.assertEqual(second.get('/api/pdf/edit/tasks').get_json()['data']['tasks'], [])
        self.assertEqual(len(first.get('/api/pdf/edit/tasks?file_id=f1').get_json()['data']['tasks']), 1)
        self.assertEqual(first.get('/api/pdf/edit/tasks?file_id=other').get_json()['data']['tasks'], [])

    def test_cancel_only_by_owner(self):
        first, second = self.http
        task = self.drive(first, kind='translate')['task']
        received(self.sockets[0])
        self.assertFalse(second.post(f"/api/pdf/edit/tasks/{task['id']}/cancel").get_json()['data']['cancelled'])
        self.assertFalse(TASKS.get(task['id']).cancelled)
        self.assertTrue(first.post(f"/api/pdf/edit/tasks/{task['id']}/cancel").get_json()['data']['cancelled'])
        self.assertTrue(self.drive(first, task_id=task['id'])['cancelled'])
        self.assertEqual(received(self.sockets[0])[-1]['status'], 'cancelled')
        self.assertEqual(received(self.sockets[1]), [])

    def test_unowned_task_cannot_be_driven(self):
        task = self.drive(self.http[0], kind='save')['task']
        response = self.http[1].post('/api/pdf/edit/tasks/test', json={'task_id': task['id'], 'progress': 1})
        self.assertEqual(response.status_code, 404)

    def test_fileless_tasks_are_listed_with_file_filter(self):
        self.drive(self.http[0], kind='fonts')
        tasks = self.http[0].get('/api/pdf/edit/tasks?file_id=f9').get_json()['data']['tasks']
        self.assertEqual([t['kind'] for t in tasks], ['fonts'])

    def test_test_route_is_off_by_default(self):
        with mock.patch.dict(os.environ, {'OMNICONV_TEST_ROUTES': ''}):
            self.assertEqual(self.http[0].post('/api/pdf/edit/tasks/test', json={}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
