module.exports = (output, context) => {
  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return { pass: false, score: 0, reason: `Invalid JSON: ${error.message}` };
  }

  const expectedValid = context.vars.expected_valid === true;
  const expectedKind = context.vars.expected_kind || null;
  const validMatches = parsed.valid === expectedValid;
  const kindMatches = expectedValid ? parsed.kind === expectedKind : parsed.error === 'invalid_handoff';
  const pass = validMatches && kindMatches;
  return {
    pass,
    score: pass ? 1 : 0,
    reason: pass
      ? `Typed handoff case matched: ${JSON.stringify(parsed)}`
      : `Unexpected typed handoff result: ${JSON.stringify({ parsed, expectedValid, expectedKind })}`,
  };
};
