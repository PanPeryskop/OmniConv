import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ToolContext:
    path: str
    file_id: str
    ops: list
    working_ops: list
    scope: dict
    emit: Callable = lambda event, data: None


@dataclass
class ToolResult:
    content: dict
    proposals: list = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable


def block_id(page, index, block):
    text = ''.join(span['t'] for line in block['lines'] for span in line['spans'])
    digest = hashlib.sha1((text + repr(block['bbox'])).encode('utf-8')).hexdigest()[:6]
    return f'p{page}b{index}-{digest}'


def page_base(ops, page):
    page_ops = [op for op in ops if op.get('page') == page]
    return {'count': len(page_ops), 'last_g': page_ops[-1].get('g') if page_ops else None}


def make_proposal(kind, page, title, ops, base, before='', after='', reason='', rects=None, depends_on=None):
    return {
        'id': 'prp_' + secrets.token_urlsafe(8), 'kind': kind, 'page': page, 'title': title, 'reason': reason,
        'before': before, 'after': after, 'rects': rects or [], 'ops': ops, 'base': base, 'depends_on': depends_on or [],
    }


TOOLS = {}


def register(spec):
    TOOLS[spec.name] = spec
    return spec


def tool_specs():
    return list(TOOLS.values())
