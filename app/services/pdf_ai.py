import re

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
MAX_TEXT = 6000


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


def translate_many(texts, language):
    if not texts:
        return []
    numbered = '\n\n'.join(f'<<{i}>> {text}' for i, text in enumerate(texts, 1))
    prompt = (f'{translate_prompt(language)} The input has numbered segments marked like <<1>>. '
              'Translate every segment separately and keep each marker in front of its translation.')
    found = {int(n): body.strip() for n, body in SEGMENT_RE.findall(ask(prompt, numbered))}
    if all(found.get(i) for i in range(1, len(texts) + 1)):
        return [found[i] for i in range(1, len(texts) + 1)]
    return [ask(translate_prompt(language), text) for text in texts]


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


def translate_page(layout, page, language, batch=12):
    blocks = [b for b in layout['blocks'] if translatable(block_text(b))]
    ops = []
    for start in range(0, len(blocks), batch):
        chunk = blocks[start:start + batch]
        for block, text in zip(chunk, translate_many([block_text(b) for b in chunk], language), strict=True):
            ops.append(block_op(page, block, text))
    return ops
