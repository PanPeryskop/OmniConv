import json
import os
import re
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = 'ministral-3-8b-instruct-2512'
SEGMENT_RE = re.compile(r'<<(\d+)>>\s*(.*?)(?=\s*<<\d+>>|\Z)', re.S)


def load_rules():
    path = os.environ.get('FAKE_LM_RULES')
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def last_user(messages):
    for message in reversed(messages):
        if message.get('role') == 'user':
            content = message.get('content')
            return content if isinstance(content, str) else json.dumps(content)
    return ''


def assistant_turns(messages):
    count = 0
    for message in reversed(messages):
        if message.get('role') == 'user':
            break
        if message.get('role') == 'assistant':
            count += 1
    return count


def scripted_step(messages):
    text = last_user(messages)
    for rule in load_rules():
        if re.search(rule.get('match', ''), text, re.I | re.S):
            steps = rule.get('steps', [])
            if not steps:
                break
            return steps[min(assistant_turns(messages), len(steps) - 1)]
    return {'text': 'OK.'}


def native_reply(payload):
    text = payload.get('input', '')
    system = payload.get('system_prompt', '')
    if '<<1>>' in text:
        return '\n\n'.join(f'<<{n}>> EN: {body.strip()}' for n, body in SEGMENT_RE.findall(text))
    if 'Correct spelling' in system:
        return text.replace('wykladu', 'wykładu').replace('Zazolc', 'Zażółć').replace('teskt', 'tekst')
    if 'shorter' in system:
        return ' '.join(text.split()[:5]) + '.'
    return 'EN: ' + text


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        length = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(length) or b'{}')

    def do_GET(self):
        if self.path.startswith('/api/v1/models') or self.path.startswith('/v1/models'):
            return self.send_json({'models': [{'key': MODEL, 'loaded_instances': [{'id': 'fake'}]}], 'data': [{'id': MODEL}]})
        self.send_json({'error': 'not found'}, 404)

    def do_POST(self):
        payload = self.body()
        if self.path.startswith('/api/v1/models/unload'):
            return self.send_json({})
        if self.path.startswith('/api/v1/chat'):
            return self.send_json({'output': [{'type': 'message', 'content': native_reply(payload)}]})
        if self.path.startswith('/v1/chat/completions'):
            return self.completions(payload)
        self.send_json({'error': 'not found'}, 404)

    def completions(self, payload):
        step = scripted_step(payload.get('messages', []))
        calls = [{'id': f'call_{uuid.uuid4().hex[:8]}', 'type': 'function',
                  'function': {'name': c['name'], 'arguments': json.dumps(c.get('args', {}), ensure_ascii=False)}}
                 for c in step.get('tool_calls', [])]
        text = step.get('text', '')
        if not payload.get('stream'):
            message = {'role': 'assistant', 'content': text or None}
            if calls:
                message['tool_calls'] = calls
            return self.send_json({'id': 'fake', 'model': MODEL, 'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls' if calls else 'stop'}]})
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'close')
        self.end_headers()
        chunks = [{'role': 'assistant', 'content': piece} for piece in re.findall(r'\S+\s*', text)]
        for i, call in enumerate(calls):
            head = {'index': i, 'id': call['id'], 'type': 'function', 'function': {'name': call['function']['name'], 'arguments': ''}}
            chunks.append({'tool_calls': [head]})
            arguments = call['function']['arguments']
            for start in range(0, len(arguments), 12):
                chunks.append({'tool_calls': [{'index': i, 'function': {'arguments': arguments[start:start + 12]}}]})
        for delta in chunks:
            self.wfile.write(f'data: {json.dumps({"choices": [{"index": 0, "delta": delta}]})}\n\n'.encode())
        finish = {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls' if calls else 'stop'}]}
        self.wfile.write(f'data: {json.dumps(finish)}\n\ndata: [DONE]\n\n'.encode())
        self.close_connection = True

    def log_message(self, *args):
        pass


def main(port=1234):
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1234)
