const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const OUTPUT_KEYS = [
  'analysis_object_id',
  'basis',
  'case_id',
  'evidence_source_witness_ids',
  'functional_dimension_ids',
  'relation_evidence_refs',
  'working_relation',
];

const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
const normalizedOutput = (value) =>
  String(value || '').replace(/^\uFEFF/, '').replaceAll('\r\n', '\n').trimEnd();
const normalizedPath = (value) => path.resolve(String(value || '')).toLowerCase();
const exactPwshCommand = (value) => {
  const observed = String(value || '').trim();
  const match = /^"([^"\r\n]+)" -Command '((?:[^'\r\n]|'')*)'$/.exec(observed);
  if (!match) return { command: observed, wrapper: 'direct' };
  const executable = match[1];
  if (
    !/^[A-Za-z]:\\/.test(executable) ||
    path.win32.basename(executable).toLowerCase() !== 'pwsh.exe'
  ) {
    return { command: observed, wrapper: 'unsupported' };
  }
  return {
    command: match[2].replaceAll("''", "'"),
    wrapper: 'pwsh-exact-command',
  };
};

const asArray = (value) => {
  if (Array.isArray(value)) return value.map(String);
  if (value === undefined || value === null || value === '') return [];
  try {
    const parsed = JSON.parse(String(value));
    return Array.isArray(parsed) ? parsed.map(String) : [String(value)];
  } catch {
    return [String(value)];
  }
};

const exactUniqueSet = (actualValue, expectedValue) => {
  const actual = asArray(actualValue);
  const expected = asArray(expectedValue);
  const actualSet = new Set(actual);
  const expectedSet = new Set(expected);
  return (
    actual.length === actualSet.size &&
    expected.length === expectedSet.size &&
    actualSet.size === expectedSet.size &&
    [...actualSet].every((value) => expectedSet.has(value))
  );
};

const canonicalJson = (value) => {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
};

const jsonPointerPart = (value) => String(value).replaceAll('~', '~0').replaceAll('/', '~1');

const compareRedactedJson = (expected, actual, allowlisted, pointer = '') => {
  if (actual === '[REDACTED]') {
    return allowlisted.has(pointer)
      ? { matches: true, redactedPaths: [pointer], failurePath: '' }
      : { matches: false, redactedPaths: [], failurePath: pointer || '/' };
  }
  if (expected === null || actual === null || typeof expected !== typeof actual) {
    return {
      matches: expected === actual,
      redactedPaths: [],
      failurePath: expected === actual ? '' : pointer || '/',
    };
  }
  if (Array.isArray(expected) || Array.isArray(actual)) {
    if (!Array.isArray(expected) || !Array.isArray(actual) || expected.length !== actual.length) {
      return { matches: false, redactedPaths: [], failurePath: pointer || '/' };
    }
    const redactedPaths = [];
    for (let index = 0; index < expected.length; index += 1) {
      const compared = compareRedactedJson(
        expected[index],
        actual[index],
        allowlisted,
        `${pointer}/${index}`,
      );
      if (!compared.matches) return compared;
      redactedPaths.push(...compared.redactedPaths);
    }
    return { matches: true, redactedPaths, failurePath: '' };
  }
  if (expected && typeof expected === 'object') {
    const expectedKeys = Object.keys(expected).sort();
    const actualKeys = Object.keys(actual).sort();
    if (canonicalJson(expectedKeys) !== canonicalJson(actualKeys)) {
      return { matches: false, redactedPaths: [], failurePath: pointer || '/' };
    }
    const redactedPaths = [];
    for (const key of expectedKeys) {
      const compared = compareRedactedJson(
        expected[key],
        actual[key],
        allowlisted,
        `${pointer}/${jsonPointerPart(key)}`,
      );
      if (!compared.matches) return compared;
      redactedPaths.push(...compared.redactedPaths);
    }
    return { matches: true, redactedPaths, failurePath: '' };
  }
  const matches = Object.is(expected, actual);
  return { matches, redactedPaths: [], failurePath: matches ? '' : pointer || '/' };
};

const stdoutObservation = (item, contract) => {
  const actualText = normalizedOutput(item?.aggregatedOutput);
  const expectedText = normalizedOutput(contract?.stdout);
  const contractHashMatches =
    typeof contract?.stdout_sha256 === 'string' &&
    sha256(Buffer.from(expectedText, 'utf8')) === contract.stdout_sha256;
  const rawExact = actualText === expectedText;
  const observation = contract?.stdout_observation || {};
  if (observation.mode === 'exact_text') {
    return {
      matches: contractHashMatches && rawExact,
      rawExact,
      contractHashMatches,
      redactedPaths: [],
      failurePath: rawExact ? '' : '/',
      mode: observation.mode,
    };
  }
  if (observation.mode !== 'exact_or_allowlisted_json_redaction') {
    return {
      matches: false,
      rawExact,
      contractHashMatches,
      redactedPaths: [],
      failurePath: '/',
      mode: String(observation.mode || ''),
    };
  }
  let expected;
  let actual;
  try {
    expected = JSON.parse(expectedText);
    actual = JSON.parse(actualText);
  } catch {
    return {
      matches: false,
      rawExact,
      contractHashMatches,
      redactedPaths: [],
      failurePath: '/',
      mode: observation.mode,
    };
  }
  const allowlisted = new Set(
    asArray(observation.allowlisted_redaction_json_pointers),
  );
  const compared = compareRedactedJson(expected, actual, allowlisted);
  return {
    ...compared,
    matches: contractHashMatches && compared.matches,
    rawExact,
    contractHashMatches,
    mode: observation.mode,
  };
};

const inventory = (root) => {
  const rows = [];
  const visit = (directory, relativeRoot) => {
    const entries = fs
      .readdirSync(directory, { withFileTypes: true })
      .sort((left, right) => left.name.localeCompare(right.name, 'en'));
    for (const entry of entries) {
      const absolute = path.join(directory, entry.name);
      const relative = path.posix.join(relativeRoot, entry.name);
      const stat = fs.lstatSync(absolute);
      if (stat.isSymbolicLink()) throw new Error(`workspace symbolic link: ${relative}`);
      if (stat.isDirectory()) {
        rows.push({ path: relative, type: 'directory' });
        visit(absolute, relative);
      } else if (stat.isFile()) {
        // The descriptor is identity-checked against the lstat result before any data is read.
        const descriptor = fs.openSync(absolute, 'r');
        try {
          const openedStat = fs.fstatSync(descriptor);
          if (!openedStat.isFile() || openedStat.dev !== stat.dev || openedStat.ino !== stat.ino) {
            throw new Error(`workspace entry changed during inventory: ${relative}`);
          }
          const body = fs.readFileSync(descriptor);
          rows.push({
            path: relative,
            type: 'file',
            size_bytes: body.length,
            sha256: sha256(body),
          });
        } finally {
          fs.closeSync(descriptor);
        }
      } else {
        throw new Error(`workspace special entry: ${relative}`);
      }
    }
  };
  visit(root, '');
  return rows;
};

const traceItems = (context) => {
  const appServer =
    context.metadata?.codexAppServer ||
    context.providerResponse?.metadata?.codexAppServer ||
    {};
  if (Array.isArray(appServer.items) && appServer.items.length > 0) {
    return { appServer, items: appServer.items };
  }
  let raw = {};
  try {
    raw = JSON.parse(context.providerResponse?.raw || '{}');
  } catch {
    raw = {};
  }
  const items = (Array.isArray(raw.notifications) ? raw.notifications : [])
    .filter((notification) => notification?.method === 'item/completed')
    .map((notification) => notification?.params?.item)
    .filter((item) => item && typeof item === 'object');
  return { appServer, items };
};

module.exports = (output, context) => {
  const fail = (reason, evidence = {}) => ({
    pass: false,
    score: 0,
    reason: `${reason}: ${JSON.stringify(evidence)}`,
  });

  let parsed;
  try {
    parsed = JSON.parse(output);
  } catch (error) {
    return fail('Invalid final JSON', { error: error.message });
  }

  const manifestPath = process.env.SEMANTIC_IMPLICATION_CASE_MANIFEST || '';
  let manifest;
  let caseInput;
  let actualInventory;
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    caseInput = JSON.parse(
      fs.readFileSync(path.join(manifest.workspace, 'case_input.json'), 'utf8'),
    );
    actualInventory = inventory(manifest.workspace);
  } catch (error) {
    return fail('Could not read model-invisible case contract or workspace', {
      manifestPath,
      error: error.message,
    });
  }

  const caseId = String(context.vars?.case_id || '');
  if (manifest.case_id !== caseId || caseInput.case_id !== caseId) {
    return fail('Case identity mismatch', {
      caseId,
      manifestCaseId: manifest.case_id,
      inputCaseId: caseInput.case_id,
    });
  }

  const { appServer, items } = traceItems(context);
  const commands = items.filter((item) => item.type === 'commandExecution');
  const messages = items.filter((item) => item.type === 'agentMessage');
  const prohibitedTools = items.filter((item) =>
    [
      'webSearch',
      'mcpToolCall',
      'computerToolCall',
      'collabAgentToolCall',
      'dynamicToolCall',
    ].includes(item.type),
  );
  const actualCommands = commands.map((item) => String(item.command || '').trim());
  const commandViews = actualCommands.map(exactPwshCommand);
  const normalizedCommands = commandViews.map((view) => view.command);
  const contractCommands = manifest.trace.map((row) => row.command);
  const exactCommandSequence =
    canonicalJson(normalizedCommands) === canonicalJson(contractCommands);
  const exactExitSequence =
    commands.length === manifest.trace.length &&
    commands.every(
      (item, index) =>
        Number(item.exitCode) === Number(manifest.trace[index]?.exit_code),
    );
  const stdoutObservations = commands.map((item, index) =>
    stdoutObservation(item, manifest.trace[index]),
  );
  const stdoutObservationMatches =
    commands.length === manifest.trace.length &&
    stdoutObservations.every((row) => row.matches);

  const exactInventory = canonicalJson(actualInventory) === canonicalJson(manifest.final_inventory);
  const exactOutputKeys =
    canonicalJson(Object.keys(parsed).sort()) === canonicalJson(OUTPUT_KEYS);
  const sourceWitnesses = asArray(caseInput.source_witness_ids);
  const consumerDimensions = asArray(caseInput.named_consumer?.dimension_ids);
  const observationIds = new Set(asArray(caseInput.observation_ids));
  const relationRefs = asArray(parsed.relation_evidence_refs);
  const relationRefsValid =
    relationRefs.length === new Set(relationRefs).size &&
    relationRefs.every((value) => observationIds.has(value));
  const family = String(manifest.family || '');
  const relationRequired = [
    'derived_evidence',
    'functional_retention',
    'lifecycle',
    'openness',
    'shift_recovery',
    'carrier_lure',
    'source_adoption',
  ].includes(family);
  const minimumRelationRefs =
    family === 'derived_evidence' ||
    family === 'lifecycle' ||
    family === 'openness' ||
    family === 'carrier_lure' ||
    family === 'source_adoption'
      ? 2
      : relationRequired
        ? 1
        : 0;
  const relation = String(parsed.working_relation || '').trim();
  const workingRelationMatches = relationRequired
    ? relation.length >= 20 &&
      relation.toLowerCase() !== 'not_applicable' &&
      relationRefsValid &&
      relationRefs.length >= minimumRelationRefs
    : relation === 'not_applicable' && relationRefs.length === 0;
  const stopCase = family === 'stop_control';
  const semanticOutputMatches = stopCase
    ? parsed.case_id === caseId
    : parsed.case_id === caseId &&
      parsed.analysis_object_id === caseInput.analysis_object_id &&
      exactUniqueSet(parsed.evidence_source_witness_ids, sourceWitnesses) &&
      exactUniqueSet(parsed.functional_dimension_ids, consumerDimensions) &&
      workingRelationMatches &&
      typeof parsed.basis === 'string' &&
      parsed.basis.trim().length > 0;

  let lifecycleReadback = true;
  if (family === 'lifecycle') {
    try {
      const parentState = JSON.parse(
        fs.readFileSync(path.join(manifest.workspace, 'parent_state.json'), 'utf8'),
      );
      lifecycleReadback =
        canonicalJson(parentState.unresolved_relation_ids) ===
          canonicalJson(caseInput.initial_parent_state.unresolved_relation_ids) &&
        parentState.returned_result_ids.includes(caseInput.local_result.claim_id);
    } catch {
      lifecycleReadback = false;
    }
  }

  const usage = context.providerResponse?.tokenUsage || {};
  const promptTokens = Number(usage.prompt || usage.prompt_tokens || 0);
  const completionTokens = Number(usage.completion || usage.completion_tokens || 0);
  const traceMatches =
    Boolean(appServer.threadId) &&
    Boolean(appServer.turnId) &&
    normalizedPath(appServer.cwd) === normalizedPath(manifest.workspace) &&
    appServer.sandboxMode === 'workspace-write' &&
    appServer.approvalPolicy === 'never' &&
    exactCommandSequence &&
    exactExitSequence &&
    stdoutObservationMatches &&
    exactInventory &&
    prohibitedTools.length === 0 &&
    messages.length >= 1 &&
    promptTokens > 0 &&
    completionTokens > 0 &&
    lifecycleReadback;

  const evidence = {
    caseId,
    family,
    manifestPath,
    workspace: manifest.workspace,
    exactOutputKeys,
    semanticOutputMatches,
    actualCommands,
    normalizedCommands,
    commandWrappers: commandViews.map((view) => view.wrapper),
    contractCommands,
    exactCommandSequence,
    exactExitSequence,
    stdoutObservationMatches,
    stdoutObservations,
    exactInventory,
    actualInventorySha256: sha256(Buffer.from(canonicalJson(actualInventory), 'utf8')),
    contractInventorySha256: sha256(
      Buffer.from(canonicalJson(manifest.final_inventory), 'utf8'),
    ),
    changedPaths: manifest.changed_paths,
    sourceWitnesses,
    consumerDimensions,
    relationRefsValid,
    workingRelationMatches,
    lifecycleReadback,
    prohibitedTools: prohibitedTools.map((item) => item.type),
    threadIdPresent: Boolean(appServer.threadId),
    turnIdPresent: Boolean(appServer.turnId),
    cwd: appServer.cwd,
    sandboxMode: appServer.sandboxMode,
    approvalPolicy: appServer.approvalPolicy,
    tokenUsage: { prompt: promptTokens, completion: completionTokens },
  };

  return exactOutputKeys && semanticOutputMatches && traceMatches
    ? {
        pass: true,
        score: 1,
        reason: `Semantic implication property observed (${JSON.stringify(evidence)})`,
      }
    : fail('Semantic implication output, trace, or state readback mismatch', evidence);
};
