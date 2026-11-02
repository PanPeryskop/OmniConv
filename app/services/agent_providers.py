import json
import os
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class AgentStep:
    text: str = ''
    tool_calls: list = field(default_factory=list)


class AgentProvider:
    name = 'base'

    def status(self):
        raise NotImplementedError

    def model(self):
        return ''

    def step(self, messages, tools, on_delta):
        raise NotImplementedError


class LmStudioProvider(AgentProvider):
    name = 'lmstudio'


class AnthropicProvider(AgentProvider):
    name = 'anthropic'


class FakeProvider(AgentProvider):
    name = 'fake'

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0

    def status(self):
        return 'ok'

    def model(self):
        return 'fake'

    def step(self, messages, tools, on_delta):
        script = self.steps[min(self.calls, len(self.steps) - 1)] if self.steps else {'text': ''}
        self.calls += 1
        text = script.get('text', '')
        if text:
            on_delta(text)
        calls = [ToolCall(id=f'call_{self.calls}_{i}', name=c['name'], args=c.get('args', {})) for i, c in enumerate(script.get('tool_calls', []))]
        return AgentStep(text=text, tool_calls=calls)


def provider_from_env():
    kind = os.environ.get('AGENT_PROVIDER', 'lmstudio')
    if kind == 'fake':
        return FakeProvider(json.loads(os.environ.get('AGENT_FAKE_STEPS', '[]')))
    if kind == 'anthropic':
        return AnthropicProvider()
    return LmStudioProvider()
