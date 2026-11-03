import re
from dataclasses import dataclass, field

from .llm import LLMService

MODES = {
    'shorter': 'Rewrite the text so it is noticeably shorter but keeps the meaning.',
    'longer': 'Expand the text a little with natural detail, keeping its meaning and tone.',
    'formal': 'Rewrite the text in a more formal, professional tone.',
    'simple': 'Rewrite the text in plain, simple language.',
    'fix': 'Correct spelling, grammar and punctuation. Change nothing else.',
}
RULES = (
    'Keep the language of the original unless told otherwise. Keep line breaks only where the original has them. '
    'Output only the resulting text, without quotes, notes, explanations or Markdown.'
)
SEGMENT_RE = re.compile(r'<<(\d+)>>\s*(.*?)(?=\s*<<\d+>>|\Z)', re.S)
GLOSSARY_RE = re.compile(r'^\s*(?:[-*•]|\d+[.)])?\s*(.+?)\s*(?:=>|->|→)\s*(.+?)\s*$')
TAG_RE = re.compile(r'</?(?:context|translate)>', re.I)
MAX_TEXT = 6000
MAX_CONTEXT = 6000
MAX_GLOSSARY_SOURCE = 8000
MAX_GLOSSARY_TERMS = 40
MAX_TERM = 80


@dataclass
class TranslationContext:
    page: list = field(default_factory=list)
    before: str = ''
    after: str = ''
    glossary: list = field(default_factory=list)

    def __bool__(self):
        return bool(self.page or self.before or self.after or self.glossary)


class AiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def status():
    service = LLMService()
    return service.model_status(LLMService.text_model())


def ask(system_prompt, text):
    reason = status()
    if reason != 'ok':
        raise AiError(f'err_ai_{reason}', 'The language model is not available')
    payload = {'model': LLMService.text_model(), 'system_prompt': system_prompt, 'input': text, 'temperature': 0.3, 'stream': False}
    try:
        result = LLMService()._send_request(payload)
    except Exception as e:
        raise AiError('err_ai_failed', str(e)) from e
    content = next((item.get('content', '') for item in result.get('output', []) if item.get('type') == 'message'), '')
    content = re.sub(r'^```\w*\n?|\n?```$', '', content.strip()).strip()
    if not content:
        raise AiError('err_ai_failed', 'The model returned no text')
    return content


def translate_prompt(language):
    return f'You are a professional translator. Translate the text into {language}. Preserve tone, numbers, names and line breaks. {RULES}'


def rewrite(text, mode, language=None):
    text = (text or '')[:MAX_TEXT]
    if not text.strip():
        return text
    if mode == 'translate':
        if not language:
            raise AiError('err_ai_failed', 'Missing target language')
        return ask(translate_prompt(language), text)
    if mode not in MODES:
        raise AiError('err_ai_failed', 'Unknown mode')
    return ask(f'You edit text taken from a PDF document. {MODES[mode]} {RULES}', text)


def glossary_text(glossary):
    return '\n'.join(f'{term} => {target}' for term, target in glossary)


def page_window(texts, low, high, limit):
    if sum(len(t) + 2 for t in texts) <= limit:
        return '\n\n'.join(texts)
    low, high = max(0, low), min(len(texts) - 1, high)
    picked = list(range(low, high + 1))
    used = sum(len(texts[i]) + 2 for i in picked)
    left, right = low - 1, high + 1
    while left >= 0 or right < len(texts):
        grown = False
        for i in (left, right):
            if 0 <= i < len(texts) and used + len(texts[i]) + 2 <= limit:
                picked.append(i)
                used += len(texts[i]) + 2
                grown = True
        left, right = left - 1, right + 1
        if not grown and used >= limit:
            break
    picked.sort()
    parts = ['…'] if picked[0] > 0 else []
    for previous, i in zip([None] + picked, picked):
        if previous is not None and i != previous + 1:
            parts.append('…')
        parts.append(texts[i])
    if picked[-1] < len(texts) - 1:
        parts.append('…')
    return '\n\n'.join(parts)


def context_text(context, low=0, high=0):
    parts = []
    if context.glossary:
        parts.append(f'Glossary, always use these translations:\n{glossary_text(context.glossary)}')
    if context.before:
        parts.append(f'End of the previous page:\n{context.before}')
    room = MAX_CONTEXT - sum(len(p) for p in parts) - len(context.after)
    if context.page and room > 0:
        parts.append(f'The whole current page:\n{page_window(context.page, low, high, room)}')
    if context.after:
        parts.append(f'Start of the next page:\n{context.after}')
    return '\n\n'.join(parts)


def segments_prompt(language, context):
    prompt = (f'{translate_prompt(language)} The input has numbered segments marked like <<1>>. '
              'Translate every segment separately and keep each marker in front of its translation.')
    if context:
        prompt += (' The <context> section shows the surrounding document only so the translation fits it: never translate, '
                   'repeat or summarize it. Use it to keep terms, grammar and sentences that continue across segments consistent. '
                   'Output only the numbered translations of the segments inside <translate>.')
    return prompt


def segments_input(texts, context, low=0, high=0):
    numbered = '\n\n'.join(f'<<{i}>> {text}' for i, text in enumerate(texts, 1))
    if not context:
        return numbered
    return f'<context>\n{context_text(context, low, high)}\n</context>\n\n<translate>\n{numbered}\n</translate>'


def segments(reply):
    return {int(n): TAG_RE.sub('', body).strip() for n, body in SEGMENT_RE.findall(reply)}


def translate_one(text, language, context=None, low=0, high=0):
    if context:
        found = segments(ask(segments_prompt(language, context), segments_input([text], context, low, high)))
        if found.get(1):
            return found[1]
    return ask(translate_prompt(language), text)


def translate_many(texts, language, context=None, low=0, high=0):
    if not texts:
        return []
    found = segments(ask(segments_prompt(language, context), segments_input(texts, context, low, high)))
    if all(found.get(i) for i in range(1, len(texts) + 1)):
        return [found[i] for i in range(1, len(texts) + 1)]
    return [translate_one(text, language, context, low, high) for text in texts]


def build_glossary(text, language, limit=MAX_GLOSSARY_TERMS):
    text = (text or '')[:MAX_GLOSSARY_SOURCE]
    if sum(c.isalpha() for c in text) < 40:
        return []
    prompt = (f'You prepare a glossary for translating a document into {language}. From the text, list up to {limit} '
              'key terms, names, product names and abbreviations that appear more than once or matter for consistency. '
              f'Write each on its own line as: source term => translation in {language}. Keep names and brands that '
              'should not be translated unchanged on the right side. Output only the list, without notes or headings.')
    try:
        reply = ask(prompt, text)
    except AiError:
        return None
    pairs, seen = [], set()
    for line in reply.splitlines():
        match = GLOSSARY_RE.match(line)
        if not match:
            continue
        term, target = match[1].strip(' "\''), match[2].strip(' "\'')
        if term and target and len(term) <= MAX_TERM and len(target) <= MAX_TERM and term.lower() not in seen:
            seen.add(term.lower())
            pairs.append((term, target))
    return pairs[:limit]


def block_text(block):
    parts = []
    for line in block['lines']:
        parts.append(''.join(span['t'] for span in line['spans']).strip())
        parts.append('\n' if line['brk'] else ' ')
    return ''.join(parts).strip()


def translatable(text):
    return sum(c.isalpha() for c in text) >= 2


def block_op(page, block, text):
    first = dict(block['lines'][0]['spans'][0], t=text, rise=0)
    return {
        'type': 'text', 'page': page,
        'remove': [r for line in block['lines'] for r in line['rects']] + (block.get('extra') or []),
        'rect': block['bbox'], 'baseline': block['baseline'], 'lh': block['lh'], 'align': block['align'],
        'family': 'original', 'grow': all(line['brk'] for line in block['lines']), 'fit': True, 'runs': [first],
    }


def translate_page(layout, page, language, batch=12, context=None, blocks=None):
    candidates = layout['blocks'] if blocks is None else blocks
    blocks = [b for b in candidates if translatable(block_text(b))]
    if context is not None and not context.page:
        context.page = [text for text in (block_text(b) for b in layout['blocks']) if text]
    position = {id(b): i for i, b in enumerate(b for b in layout['blocks'] if block_text(b))}
    ops = []
    for start in range(0, len(blocks), batch):
        chunk = blocks[start:start + batch]
        places = [position.get(id(b), 0) for b in chunk]
        texts = translate_many([block_text(b) for b in chunk], language, context, min(places), max(places))
        for block, text in zip(chunk, texts, strict=True):
            ops.append(block_op(page, block, text))
    return ops


def fix_text(text, language=None):
    if not language:
        return rewrite(text, 'fix')
    text = (text or '')[:MAX_TEXT]
    if not text.strip():
        return text
    return ask(f'You edit text taken from a PDF document written in {language}. {MODES["fix"]} {RULES}', text)
