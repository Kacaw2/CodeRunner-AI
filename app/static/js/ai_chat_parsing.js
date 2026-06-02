(function (root) {
  function extractFirstJsonObject(text) {
    if (!text) return null;

    for (let start = 0; start < text.length; start++) {
      if (text[start] !== "{") continue;

      let depth = 0;
      let inString = false;
      let escaped = false;

      for (let pos = start; pos < text.length; pos++) {
        const ch = text[pos];

        if (inString) {
          if (escaped) {
            escaped = false;
          } else if (ch === "\\") {
            escaped = true;
          } else if (ch === '"') {
            inString = false;
          }
          continue;
        }

        if (ch === '"') {
          inString = true;
        } else if (ch === "{") {
          depth++;
        } else if (ch === "}") {
          depth--;
          if (depth === 0) {
            try {
              const parsed = JSON.parse(text.slice(start, pos + 1));
              if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
                return parsed;
              }
            } catch (_) {
              break;
            }
            break;
          }
        }
      }
    }

    return null;
  }

  function parseGeneratorOutput(text) {
    const obj = extractFirstJsonObject(text);
    if (!obj) return null;
    const data = obj.question || obj;
    if (data && data.title && data.test_cases) return data;
    return null;
  }

  function parseReviewerOutput(text) {
    const obj = extractFirstJsonObject(text);
    if (!obj) return null;
    if (obj.overall_score && obj.summary && Array.isArray(obj.issues)) return obj;
    return null;
  }

  const api = {
    extractFirstJsonObject,
    parseGeneratorOutput,
    parseReviewerOutput,
  };

  root.CodeRunnerAIChatParsing = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
