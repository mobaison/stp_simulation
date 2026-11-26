import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import HTTPException


def clean_latex(text: str) -> str:
    if not text:
        return ''
    # 1. Remove LaTeX text commands \text{...} -> ...
    text = re.sub(r'\\text\{([^}]*)\}', r'\1', text)
    # 2. Replace standard LaTeX symbols with plain text equivalents
    for sym, rep in [
        (r'\approx', '~'),
        (r'\le', '<='),
        (r'\ge', '>='),
        (r'\times', 'x'),
        (r'\pm', '+/-'),
        (r'\cdot', '·'),
        (r'\degree', '°'),
        (r'\neq', '!='),
        (r'\to', '->'),
        (r'\sim', '~'),
    ]:
        text = text.replace(sym, rep)
    # 3. Unwrap math dollars ($...$ or $$...$$)
    text = re.sub(r'\$\$([^\$]+)\$\$', r'\1', text)
    text = re.sub(r'\$([^\$]+)\$', r'\1', text)
    # 4. Clean stray partial LaTeX remnants or broken tokens (e.g. '):t{ mg/L}', '\te')
    text = re.sub(r':\s*t\{[^}]*\}', ':', text)
    text = re.sub(r'\\te\b', '', text)
    text = re.sub(r'\\t\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\([a-zA-Z]+)', r'\1', text)
    # 5. Clean lone remaining dollar signs
    text = text.replace('$', '')
    return text.strip()


def query_gemini(key: str, message: str, history: list, instruction: str) -> str:
    contents = [{'role': h.role, 'parts': [{'text': h.text}]} for h in history]
    contents.append({'role': 'user', 'parts': [{'text': message}]})
    model = quote(os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite'), safe='')
    request = Request(
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
        headers={'Content-Type': 'application/json', 'x-goog-api-key': key},
        data=json.dumps({
            'systemInstruction': {'parts': [{'text': instruction}]},
            'contents': contents,
            'generationConfig': {'maxOutputTokens': 2048}
        }).encode('utf-8')
    )
    with urlopen(request, timeout=25) as response:
        parts = json.load(response)['candidates'][0]['content']['parts']
        reply = '\n'.join(p.get('text', '') for p in parts if not p.get('thought')).strip()
        if reply:
            return reply
    raise ValueError('Gemini returned an empty response.')


def query_groq(key: str, message: str, history: list, instruction: str) -> str:
    messages = [{'role': 'system', 'content': instruction}]
    for h in history:
        role = 'assistant' if h.role == 'model' else 'user'
        messages.append({'role': role, 'content': h.text})
    messages.append({'role': 'user', 'content': message})

    preferred_model = os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b').strip() or 'openai/gpt-oss-120b'
    candidate_models = [preferred_model]
    for fallback in ['openai/gpt-oss-120b', 'openai/gpt-oss-20b', 'qwen/qwen3.8-27b']:
        if fallback not in candidate_models:
            candidate_models.append(fallback)

    last_exc = None
    for model in candidate_models:
        request = Request(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {key}',
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
            data=json.dumps({
                'model': model,
                'messages': messages,
                'temperature': 0.3,
                'max_tokens': 2048,
            }).encode('utf-8')
        )
        try:
            with urlopen(request, timeout=25) as response:
                data = json.load(response)
                choices = data.get('choices', [])
                if choices:
                    reply = choices[0].get('message', {}).get('content', '').strip()
                    if reply:
                        return reply
        except HTTPError as exc:
            last_exc = exc
            if exc.code == 404:
                continue
            raise
        except Exception as exc:
            last_exc = exc
            continue

    if last_exc:
        raise last_exc
    raise ValueError('Groq returned an empty response.')


def answer(message, history, snapshot, controls, return_provider=False):
    gemini_key = os.getenv('GEMINI_API_KEY', '').strip()
    groq_key = os.getenv('GROQ_API_KEY', '').strip()
    if not gemini_key and not groq_key:
        raise HTTPException(503, 'Set GEMINI_API_KEY or GROQ_API_KEY in backend/.env and restart the backend.')

    context = {k: v for k, v in snapshot.items() if k != 'history'}
    instruction = (
        'You are the expert Plant Operations AI Assistant for this educational BNR–MBR wastewater treatment plant digital twin. '
        'Reference the current simulated values, units, and plant operational state provided below. '
        'CRITICAL FORMATTING INSTRUCTIONS: '
        '1. Format your response in clean, high-readability Markdown. '
        '2. NEVER output raw LaTeX syntax (do NOT use $, $$, \\text{}, \\approx, \\le, \\ge, etc.). '
        '3. Always write units and numbers in plain text (e.g., write "49.0 s", "35.0 mg/L", "~34.9 mg/L", "2.25 m", "1900 GPM", "<= 5 mg/L"). '
        '4. Use clean bullet points, bold section headers, and concise operational diagnostics. '
        '5. Distinguish observed sensor readings from hypotheses. Treat reference figures as project assumptions. '
        '6. Describe only controls present in the supplied configuration. You cannot change controls directly. '
        'Tank quality and effluent_quality are in mg/L. Use effluent_quality for '
        'the most recent discharge interval. Null means there was no discharge sample. '
        'Last applied controls and state: '
        + json.dumps([controls, context])
    )

    errors = []
    # 1. Attempt Gemini if key is provided
    if gemini_key:
        try:
            reply = query_gemini(gemini_key, message, history, instruction)
            if reply:
                reply = clean_latex(reply)
                return (reply, 'Gemini') if return_provider else reply
        except HTTPError as exc:
            errors.append(f'Gemini HTTP {exc.code}')
        except Exception as exc:
            errors.append(f'Gemini ({type(exc).__name__})')

    # 2. Attempt Groq fallback if key is provided
    if groq_key:
        try:
            reply = query_groq(groq_key, message, history, instruction)
            if reply:
                reply = clean_latex(reply)
                provider = 'Groq (fallback)' if gemini_key else 'Groq'
                return (reply, provider) if return_provider else reply
        except HTTPError as exc:
            errors.append(f'Groq HTTP {exc.code}')
        except Exception as exc:
            errors.append(f'Groq ({type(exc).__name__})')

    err_summary = '; '.join(errors) if errors else 'No response from model'
    raise HTTPException(503, f'AI assistant unavailable: {err_summary}. Check model, keys and quotas in backend/.env.')
