module.exports = (output, context) => {
  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return { pass: false, score: 0, reason: `Invalid JSON: ${error.message}` };
  }
  const expectedAdmitted = context.vars.expected_admitted === true;
  const expectedReason = context.vars.expected_reason || null;
  const admissionMatches = parsed.admitted === expectedAdmitted;
  const reasonMatches = expectedAdmitted
    ? Array.isArray(parsed.reasons) && parsed.reasons.length === 0
    : Array.isArray(parsed.reasons) && parsed.reasons.includes(expectedReason);
  const pass = admissionMatches && reasonMatches;
  return {
    pass,
    score: pass ? 1 : 0,
    reason: pass
      ? `Admission matched: ${JSON.stringify(parsed)}`
      : `Admission mismatch: ${JSON.stringify({ parsed, expectedAdmitted, expectedReason })}`,
  };
};
