"""Regression tests for AI chat structured-response parsing."""
import json
import subprocess
import textwrap
from pathlib import Path


def test_generator_extract_json_skips_non_json_braces_around_fenced_payload():
    from agents.generator.agent import _extract_json

    text = textwrap.dedent(r'''
        I will generate a problem. Example notation: {not json}.

        ```json
        {
          "title": "Trace Python Output",
          "description": "Explain this code:\n```python\nprint({\"a\": 1})\n```",
          "programming_language": "python",
          "solution": "print(1)",
          "test_cases": [
            {"input": "", "expected_output": "1", "is_hidden": false, "weight": 1.0}
          ]
        }
        ```

        Done: {also not json}.
    ''')

    parsed = _extract_json(text)

    assert parsed is not None
    assert parsed["title"] == "Trace Python Output"
    assert "```python" in parsed["description"]


def test_ai_chat_parser_handles_inner_code_fences_and_surrounding_braces():
    text = r'''
Preamble {not json}

```json
{
  "question": {
    "title": "Trace Python Output",
    "description": "Explain this code:\n```python\nprint({\"a\": 1})\n```",
    "programming_language": "python",
    "solution": "print(1)",
    "test_cases": [
      {"input": "", "expected_output": "1", "is_hidden": false, "weight": 1.0}
    ]
  }
}
```

Trailing {not json}
'''
    script = """
const parser = require('./app/static/js/ai_chat_parsing.js');
const text = __TEXT__;
const parsed = parser.parseGeneratorOutput(text);
if (!parsed || parsed.title !== 'Trace Python Output' || !parsed.description.includes('```python')) {
  console.error(JSON.stringify(parsed));
  process.exit(1);
}
""".replace("__TEXT__", json.dumps(text))
    result = subprocess.run(
        ["node", "-e", script],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_ai_chat_renders_reviewer_json_as_card():
    review = {
        "overall_score": "B",
        "summary": "Mostly correct with one edge-case issue.",
        "issues": [{
            "severity": "warning",
            "line": 3,
            "category": "correctness",
            "message": "Missing empty input handling.",
            "suggestion": "Check for empty input before indexing.",
        }],
        "strengths": ["Clear loop structure"],
        "complexity": {"time": "O(n)", "space": "O(1)"},
    }
    script = """
const parser = require('./app/static/js/ai_chat_parsing.js');
function htmlEscape(value) {
  return String(value || '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}
function makeElement() {
  const el = {
    className: '',
    style: {},
    children: [],
    scrollTop: 0,
    scrollHeight: 0,
    appendChild(child) { this.children.push(child); child.parentNode = this; return child; },
    remove() {},
    addEventListener() {},
    querySelector() { return makeElement(); },
    querySelectorAll() { return []; },
    focus() {},
  };
  let text = '';
  let html = '';
  Object.defineProperty(el, 'textContent', {
    get() { return text; },
    set(value) { text = String(value || ''); html = htmlEscape(text); },
  });
  Object.defineProperty(el, 'innerHTML', {
    get() { return html; },
    set(value) { html = String(value || ''); },
  });
  return el;
}
const elements = {};
global.window = {
  __AI_CONTEXT: {},
  __AI_CHAT_ENABLE_TEST_HOOKS: true,
  CodeRunnerAIChatParsing: parser,
};
global.document = {
  getElementById(id) { return elements[id] || (elements[id] = makeElement()); },
  querySelectorAll() { return []; },
  createElement() { return makeElement(); },
};
global.localStorage = { getItem() { return null; } };
global.sessionStorage = { getItem() { return null; }, removeItem() {}, setItem() {} };
global.fetch = async () => ({ ok: true, json: async () => ({ items: [] }) });
global.confirm = () => true;
require('./app/static/js/ai_chat.js');
const text = '```json\\n' + JSON.stringify(__REVIEW__) + '\\n```';
const card = window.__AI_CHAT_TEST_HOOKS.renderStructuredCard(text, 'reviewer', null);
if (!card || card.className !== 'review-card' || !card.innerHTML.includes('Code Review')) {
  console.error(card && card.className, card && card.innerHTML);
  process.exit(1);
}
""".replace("__REVIEW__", json.dumps(review))
    result = subprocess.run(
        ["node", "-e", script],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
