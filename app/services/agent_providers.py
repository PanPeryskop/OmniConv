import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field

import requests

from .llm import LLMService

STREAM_CHUNK = 64
LMSTUDIO_TIMEOUT = (5, 600)
FENCE_RE = re.compile(r'```(?:json)?\s*(.*?)```', re.S)
JSON_MODE_PROMPT = (
    'Tools are available, but this model has to call them through plain JSON. To call a tool, reply with only one JSON '
    'object and nothing else: {"tool": "<name>", "args": {...}}. After each call you receive the result in the next '
    'message. To answer the user without a tool, reply with plain text.\n\nTools:\n'
)
JSON_TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool, 'null': type(None)}


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    error: str = ''


@dataclass
class AgentStep:
    text: str = ''
    tool_calls: list = field(default_factory=list)
    finish_reason: str = ''


class ProviderError(Exception):
    def __init__(self, code, message=''):
        super().__init__(message or code)
        self.code = code


class StepStopped(Exception):
    pass


def call_id():
    return 'call_' + secrets.token_hex(6)


def matches_type(kind, value):
    if kind == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    expected = JSON_TYPES.get(kind)
    return expected is None or isinstance(value, expected)


def coerce(kind, value):
    if kind in ('integer', 'number') and isinstance(value, (str, float)) and not isinstance(value, bool):
        try:
            number = float(value.strip()) if isinstance(value, str) else value
        except ValueError:
            return value
        if kind == 'number':
            return number
        return int(number) if number.is_integer() else value
    if kind == 'array' and not isinstance(value, (list, dict)) and value is not None:
        return [value]
    if kind == 'boolean' and value in ('true', 'false'):
        return value == 'true'
    return value


def check_schema(schema, value, path):
    if not isinstance(schema, dict):
        return value, []
    kinds = schema.get('type')
    kinds = kinds if isinstance(kinds, list) else [kinds] if kinds else []
    if kinds and not any(matches_type(kind, value) for kind in kinds):
        for kind in kinds:
            candidate = coerce(kind, value)
            if matches_type(kind, candidate):
                value = candidate
                break
        else:
            return value, [f'{path}: expected {"/".join(kinds)}']
    errors = []
    if 'enum' in schema and value not in schema['enum']:
        errors.append(f'{path}: must be one of {", ".join(map(str, schema["enum"]))}')
    if isinstance(value, dict):
        properties = schema.get('properties') or {}
        required = schema.get('required') or []
        value = {k: v for k, v in value.items() if v is not None or k in required}
        errors += [f'{path}.{key}: required' for key in required if key not in value]
        if schema.get('additionalProperties') is False:
            errors += [f'{path}.{key}: unexpected' for key in value if key not in properties]
        for key, sub in properties.items():
            if key in value:
                value[key], sub_errors = check_schema(sub, value[key], f'{path}.{key}')
                errors += sub_errors
    if isinstance(value, list) and isinstance(schema.get('items'), dict):
        items = []
        for index, item in enumerate(value):
            item, sub_errors = check_schema(schema['items'], item, f'{path}[{index}]')
            items.append(item)
            errors += sub_errors
        value = items
    if matches_type('number', value):
        if 'minimum' in schema and value < schema['minimum']:
            errors.append(f'{path}: must be >= {schema["minimum"]}')
        if 'maximum' in schema and value > schema['maximum']:
            errors.append(f'{path}: must be <= {schema["maximum"]}')
    return value, errors


def validate_args(schema, args):
    if not isinstance(args, dict):
        return {}, ['args: expected object']
    value, errors = check_schema(schema or {'type': 'object'}, args, 'args')
    return (value if isinstance(value, dict) else {}), errors


def json_tool_call(text, tools):
    specs = {spec.name: spec for spec in tools}
    fenced = FENCE_RE.search(text or '')
    body = fenced.group(1) if fenced else (text or '')
    start, end = body.find('{'), body.rfind('}')
    if start < 0 or end <= start:
        return None, text
    try:
        data = json.loads(body[start:end + 1])
    except ValueError:
        return None, text
    if not isinstance(data, dict):
        return None, text
    name = data.get('tool') or data.get('name')
    args = data.get('args', data.get('arguments', {}))
    if isinstance(args, str):
        try:
            args = json.loads(args or '{}')
        except ValueError:
            return None, text
    if name not in specs or not isinstance(args, dict):
        return None, text
    args, errors = validate_args(specs[name].parameters, args)
    rest = text[:fenced.start()] if fenced else body[:start]
    return ToolCall(id=call_id(), name=name, args=args, error='; '.join(errors)), rest.strip()


def parse_arguments(arguments, truncated=False):
    if isinstance(arguments, dict):
        return arguments, ''
    try:
        args = json.loads(arguments or '{}')
    except ValueError:
        return {}, 'tool arguments were cut off' if truncated else 'tool arguments are not valid JSON'
    return (args, '') if isinstance(args, dict) else ({}, 'tool arguments must be a JSON object')


def fold_messages(messages):
    system, history, notes = [], [], []
    for message in messages:
        if message['role'] == 'system':
            (notes if history or system else system).append(message['content'])
            continue
        if message['role'] == 'user' and notes:
            message = dict(message, content='\n'.join(notes + [message['content']]))
            notes = []
        history.append(message)
    if notes:
        history.append({'role': 'user', 'content': '\n'.join(notes)})
    return '\n\n'.join(system), history


def stream_lines(response, should_stop):
    for line in response.iter_lines(chunk_size=STREAM_CHUNK):
        if should_stop and should_stop():
            raise StepStopped()
        if not line:
            continue
        line = line.decode('utf-8', 'replace') if isinstance(line, bytes) else line
        if not line.startswith('data:'):
            continue
        data = line[5:].strip()
        if data == '[DONE]':
            return
        try:
            yield json.loads(data)
        except ValueError:
            continue


def tool_listing(tools):
    return '\n'.join(f'- {spec.name}: {spec.description} Args schema: {json.dumps(spec.parameters, ensure_ascii=False)}' for spec in tools)


class AgentProvider:
    name = 'base'

    def status(self):
        raise NotImplementedError

    def model(self):
        return ''

    def step(self, messages, tools, on_delta, should_stop=None):
        raise NotImplementedError


class LmStudioProvider(AgentProvider):
    name = 'lmstudio'
    json_models = set()

    def model(self):
        return os.environ.get('LLM_AGENT_MODEL') or LLMService.text_model()

    def status(self):
        return LLMService().model_status(self.model())

    def wire(self, system, history, tools, json_mode):
        if json_mode and tools:
            system = f'{system}\n\n{JSON_MODE_PROMPT}{tool_listing(tools)}'
        wire = [{'role': 'system', 'content': system}]

        def push(message):
            last = wire[-1]
            if message['role'] == 'user' and last['role'] == 'user':
                last['content'] = f'{last["content"]}\n\n{message["content"]}'
            else:
                wire.append(message)

        for message in history:
            role = message['role']
            calls = message.get('tool_calls') or []
            if role == 'assistant' and json_mode:
                parts = [message.get('content') or ''] + [json.dumps({'tool': c['name'], 'args': c['args']}, ensure_ascii=False) for c in calls]
                push({'role': 'assistant', 'content': '\n'.join(p for p in parts if p)})
            elif role == 'assistant':
                item = {'role': 'assistant', 'content': message.get('content') or ''}
                if calls:
                    item['tool_calls'] = [
                        {'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': json.dumps(c['args'], ensure_ascii=False)}}
                        for c in calls
                    ]
                push(item)
            elif role == 'tool' and json_mode:
                push({'role': 'user', 'content': f'Result of {message.get("name", "tool")}: {message["content"]}'})
            elif role == 'tool':
                push({'role': 'tool', 'tool_call_id': message['tool_call_id'], 'content': message['content']})
            else:
                push({'role': 'user', 'content': message['content']})
        return wire

    def step(self, messages, tools, on_delta, should_stop=None):
        service = LLMService()
        model = service.resolve_model(self.model())
        system, history = fold_messages(messages)
        for _attempt in range(2):
            json_mode = model in self.json_models
            payload = {'model': model, 'messages': self.wire(system, history, tools, json_mode), 'stream': True, 'temperature': 0.2}
            if tools and not json_mode:
                payload['tools'] = [{'type': 'function', 'function': {'name': t.name, 'description': t.description, 'parameters': t.parameters}} for t in tools]
                payload['tool_choice'] = 'auto'
            try:
                with LLMService.using(model):
                    service.ensure_model_ready(model)
                    with requests.post(f'{service.base_url}/v1/chat/completions', json=payload, stream=True, timeout=LMSTUDIO_TIMEOUT) as response:
                        if response.status_code == 400 and 'tools' in payload and 'tool' in response.text.lower():
                            self.json_models.add(model)
                            continue
                        if response.status_code == 404:
                            raise ProviderError('err_ai_llm_model_missing', response.text[:300])
                        if response.status_code >= 400:
                            raise ProviderError('err_agent_failed', f'HTTP {response.status_code}: {response.text[:300]}')
                        return self.read(response, tools, on_delta, should_stop)
            except (requests.ConnectionError, requests.Timeout) as e:
                raise ProviderError('err_ai_llm_offline', str(e)) from e
            except requests.RequestException as e:
                raise ProviderError('err_agent_failed', str(e)) from e
        raise ProviderError('err_agent_failed', 'The model rejected the tool definitions')

    def read(self, response, tools, on_delta, should_stop):
        content, slots, finish = '', {}, ''
        sent, hold = 0, None
        for chunk in stream_lines(response, should_stop):
            if chunk.get('error'):
                raise ProviderError('err_agent_failed', json.dumps(chunk['error'])[:300])
            for choice in chunk.get('choices') or []:
                delta = choice.get('delta') or {}
                piece = delta.get('content')
                if piece:
                    content += piece
                    if hold is None and content.strip():
                        hold = content.lstrip()[0] in '{`'
                    if hold is False:
                        on_delta(content[sent:])
                        sent = len(content)
                for part in delta.get('tool_calls') or []:
                    slot = slots.setdefault(part.get('index', len(slots)), {'id': '', 'name': '', 'arguments': ''})
                    slot['id'] = part.get('id') or slot['id']
                    function = part.get('function') or {}
                    name = function.get('name')
                    if name and name != slot['name']:
                        slot['name'] += name
                    arguments = function.get('arguments')
                    if isinstance(arguments, dict):
                        slot['arguments'] = arguments
                    elif arguments:
                        slot['arguments'] += arguments
                finish = choice.get('finish_reason') or finish
        calls = []
        for _index, slot in sorted(slots.items()):
            args, error = parse_arguments(slot['arguments'], finish == 'length')
            calls.append(ToolCall(id=slot['id'] or call_id(), name=slot['name'], args=args, error=error))
        if not calls and tools:
            call, rest = json_tool_call(content, tools)
            if call:
                calls, content = [call], rest
        if hold and not calls and content:
            on_delta(content)
        return AgentStep(text=content.strip(), tool_calls=calls, finish_reason=finish)


class FakeProvider(AgentProvider):
    name = 'fake'

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0

    def status(self):
        return 'ok'

    def model(self):
        return 'fake'

    def step(self, messages, tools, on_delta, should_stop=None):
        script = self.steps[min(self.calls, len(self.steps) - 1)] if self.steps else {'text': ''}
        self.calls += 1
        if script.get('error'):
            raise ProviderError(script['error'], script.get('message', ''))
        text = script.get('text', '')
        delay = float(script.get('delay') or 0)
        pieces = re.findall(r'\S+\s*', text) if delay else [text]
        for piece in pieces:
            if should_stop and should_stop():
                raise StepStopped()
            if delay:
                time.sleep(delay)
            if piece:
                on_delta(piece)
        if should_stop and should_stop():
            raise StepStopped()
        calls = [ToolCall(id=f'call_{self.calls}_{i}', name=c['name'], args=c.get('args', {})) for i, c in enumerate(script.get('tool_calls', []))]
        return AgentStep(text=text, tool_calls=calls)


def provider_from_env():
    kind = os.environ.get('AGENT_PROVIDER', 'lmstudio')
    if kind == 'fake':
        return FakeProvider(json.loads(os.environ.get('AGENT_FAKE_STEPS', '[]')))
    return LmStudioProvider()
