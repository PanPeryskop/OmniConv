import unittest
import warnings

from app.services.agent_providers import FakeProvider
from app.services.editor_tasks import TaskRegistry
from app.services.pdf_agent_tools import page_base


class Wp0Test(unittest.TestCase):
    def test_task_registry_lifecycle_and_isolation(self):
        registry = TaskRegistry()
        seen = []
        registry.subscribe(seen.append)
        task = registry.create('me', 'ocr', 'file', 2)
        registry.update(task.id, stage='detect', progress=0.4)
        self.assertEqual(registry.get(task.id).status, 'running')
        self.assertEqual(registry.list('someone'), [])
        self.assertFalse(registry.cancel('someone', task.id))
        self.assertTrue(registry.cancel('me', task.id))
        self.assertTrue(registry.get(task.id).cancelled)
        self.assertNotIn('owner', task.public())
        self.assertGreaterEqual(len(seen), 3)

    def test_fake_provider_replays_steps(self):
        provider = FakeProvider([{'tool_calls': [{'name': 'read_page', 'args': {'page': 0}}]}, {'text': 'Gotowe'}])
        deltas = []
        first = provider.step([], [], deltas.append)
        second = provider.step([], [], deltas.append)
        self.assertEqual(first.tool_calls[0].name, 'read_page')
        self.assertEqual(second.text, 'Gotowe')
        self.assertEqual(deltas, ['Gotowe'])

    def test_page_base(self):
        ops = [{'page': 1, 'g': 3}, {'page': 0, 'g': 4}, {'page': 1, 'g': 5}]
        self.assertEqual(page_base(ops, 1), {'count': 2, 'last_g': 5})
        self.assertEqual(page_base(ops, 2), {'count': 0, 'last_g': None})

    def test_routes_are_registered(self):
        warnings.filterwarnings('ignore')
        from app import create_app
        client = create_app().test_client()
        self.assertEqual(client.get('/api/pdf/edit/tasks').status_code, 200)
        self.assertEqual(client.get('/api/pdf/edit/agent/status').status_code, 501)


if __name__ == '__main__':
    unittest.main()
