const { app, BrowserWindow, ipcMain, screen } = require('electron');
const fs = require('fs');
const http = require('http');
const path = require('path');

// XINAOSurface is a stable two-layer local interface component.
// App side: XinaoSurfaceFrame = top current task intent + bottom event flow.
// Local side: OperatorViewPayload v1, see schemas/operator-view.schema.json.
// New app logic must follow APP_MATURE_GLUE_CONTRACT.md and use mature glue
// for renderer UI, refresh/cache, schema validation, projection, and lists.
const isSmoke = process.argv.includes('--smoke');
const RUNTIME_ROOT = process.env.XINAO_RESEARCH_RUNTIME || 'D:\\XINAO_RESEARCH_RUNTIME';
const APP_DATA_ROOT = path.join(RUNTIME_ROOT, 'state', 'xinao_surface_appdata');
const DEFAULT_WIDTH = 980;
const DEFAULT_HEIGHT = 680;
const MIN_WIDTH = 880;
const MIN_HEIGHT = 590;

const STATUS_ENDPOINT = 'http://127.0.0.1:19102/operator/current-view';
const ENDPOINT_TIMEOUT_MS = 1200;
const STALE_GRACE_MS = 120000;
const PHASE_FEED_MAX = 40;
const CURRENT_TASK_PACKAGE_PATH = process.env.XINAO_SURFACE_TASK_PACKAGE
  || 'C:\\Users\\xx363\\Desktop\\新系统\\TASK_PACKAGE.json';

app.setName('XINAOSurface');
app.setPath('userData', isSmoke ? path.join(APP_DATA_ROOT, 'smoke') : APP_DATA_ROOT);
app.commandLine.appendSwitch('disk-cache-dir', path.join(app.getPath('userData'), 'Cache'));
app.commandLine.appendSwitch('disable-gpu-shader-disk-cache');

const statusFiles = {
  readback: path.join(RUNTIME_ROOT, 'state', 'codex_s_main_execution_loop_tick', 'latest.json'),
  owner: path.join(RUNTIME_ROOT, 'state', 'worker_dispatch_ledger', 'latest.json'),
  projectionOps: path.join(RUNTIME_ROOT, 'state', 'next_frontier_machine_actions', 'latest.json')
};

function boundsPath() {
  return path.join(app.getPath('userData'), 'window-bounds.json');
}

function isBoundsVisible(bounds) {
  const displays = screen.getAllDisplays();
  return displays.some((display) => {
    const area = display.workArea;
    const right = bounds.x + bounds.width;
    const bottom = bounds.y + bounds.height;
    return bounds.x < area.x + area.width
      && right > area.x
      && bounds.y < area.y + area.height
      && bottom > area.y;
  });
}

function readWindowBounds() {
  try {
    const raw = fs.readFileSync(boundsPath(), 'utf8');
    const parsed = JSON.parse(raw);
    const bounds = {
      x: Number(parsed.x),
      y: Number(parsed.y),
      width: Math.max(MIN_WIDTH, Number(parsed.width)),
      height: Math.max(MIN_HEIGHT, Number(parsed.height))
    };
    if (
      Number.isFinite(bounds.x)
      && Number.isFinite(bounds.y)
      && Number.isFinite(bounds.width)
      && Number.isFinite(bounds.height)
      && isBoundsVisible(bounds)
    ) {
      return bounds;
    }
  } catch {
    // Keep default size on first launch or decode errors.
  }
  return { width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT };
}

function saveWindowBounds(win) {
  if (win.isDestroyed() || win.isMinimized() || win.isFullScreen()) return;
  const bounds = win.getBounds();
  fs.mkdirSync(path.dirname(boundsPath()), { recursive: true });
  fs.writeFileSync(boundsPath(), JSON.stringify({
    schema_version: 'xinao.surface.window_bounds.v1',
    saved_at: new Date().toISOString(),
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
    maximized: win.isMaximized()
  }, null, 2));
}

function readJsonIfExists(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch {
    return null;
  }
}

function readTextIfExists(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8');
  } catch {
    return null;
  }
}

function firstText(...values) {
  for (const value of values) {
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (trimmed) return trimmed;
    }
  }
  return '';
}

function toEpoch(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function toChineseBoolean(value) {
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'string') {
    const lower = value.trim().toLowerCase();
    if (['是', 'yes', 'true', '1', 'need', 'required', 'y'].includes(lower)) return '是';
    if (['否', 'no', 'false', '0', 'not_need', 'notrequired', 'not required'].includes(lower)) return '否';
  }
  return '';
}

function toDisplayTime(value, fallback) {
  const epoch = toEpoch(value) || fallback;
  return epoch
    ? new Date(epoch).toLocaleString('zh-CN', { hour12: false })
    : new Date().toLocaleString('zh-CN', { hour12: false });
}

function normalizeChineseText(value, fallback = '未返回中文内容') {
  if (typeof value !== 'string') return fallback;
  const trimmed = value.trim();
  if (!trimmed) return fallback;
  if (hasChineseText(trimmed)) return operatorDisplayCopy(trimmed);
  return `运行记录：${trimmed}`;
}

function hasChineseText(value) {
  return typeof value === 'string' && /[\u4e00-\u9fff]/.test(value);
}

function operatorDisplayCopy(value) {
  return firstText(value)
    .replace(/\bexec\/SDK worker\b/gi, '后端执行器')
    .replace(/\bworker\b/gi, '执行器')
    .replace(/\bpartial\b/gi, '续接')
    .replace(/\bbounded activity\b/gi, '限定动作')
    .replace(/\btask[-_ ]?bound\b/gi, '任务内')
    .replace(/\btask-scoped\b/gi, '任务内')
    .replace(/\btask_id\b/gi, '当前任务编号')
    .replace(/\blatest\.json\b/gi, '最新读回')
    .replace(/\bresult\/latest\b/gi, '结果读回')
    .replace(/\bprojection_scoped_verified\b/gi, '投影已限定验证')
    .replace(/\bradar\b/gi, '投影雷达')
    .replace(/\bops\b/gi, '运维')
    .replace(/\bresult\b/gi, '结果')
    .replace(/\bfresh\b/gi, '新鲜')
    .replace(/\breadback\b/gi, '读回')
    .replace(/\bevidence\b/gi, '证据')
    .replace(/\bsnapshot\b/gi, '快照')
    .replace(/\bingress result\b/gi, '入口结果')
    .replace(/\bRUNNING\b/g, '运行中')
    .replace(/\bPASS\b/g, '通过标记')
    .replace(/\braw JSON\b/gi, '原始数据')
    .replace(/\bJSON\b/g, '结构化数据')
    .replace(/\bAPI\b/g, '接口')
    .replace(/\bpanel\b/gi, '状态盘')
    .replace(/\bowner\b/gi, '任务所有者')
    .replace(/\bTemporal\b/g, '工作流');
}

function taskPackageModeText(value) {
  const mode = firstText(value);
  if (!mode) return 'P0 任务包已锚定';
  if (mode === 'current_system_p0') return 'P0 任务包已锚定';
  return hasChineseText(mode) ? mode : `任务包模式：${mode}`;
}

function surfaceDeployStatusText(payload) {
  if (!payload || typeof payload !== 'object') return '部署状态待刷新';
  const status = firstText(payload.status);
  if (status === 'xinao_surface_deploy_ready') return '已部署并已更新桌面快捷方式';
  if (status === 'xinao_surface_candidate_deploy_ready_shortcut_not_promoted') return '候选包已部署，桌面快捷方式未切换';
  if (status === 'xinao_surface_deploy_blocked') return '部署被阻塞';
  if (status === 'xinao_surface_shortcut_ready') return '桌面快捷方式已更新';
  if (firstText(payload.deployed_exe, payload.exe_path)) return '已部署';
  if (firstText(payload.shortcut_path) && firstText(payload.shortcut_target_after, payload.exe_path)) return '桌面快捷方式已更新';
  return status || '部署状态待刷新';
}

function surfaceDeployImpact(payload) {
  if (!payload || typeof payload !== 'object') return '桌面壳部署证据未返回；不影响后台任务。';
  const exe = firstText(payload.deployed_exe, payload.exe_path);
  const shortcut = firstText(payload.shortcut_path);
  if (exe && shortcut) return `快捷方式：${shortcut}；目标：${exe}`;
  if (exe) return `部署目标：${exe}`;
  return '桌面壳部署证据已读取；不作为后台完成口径。';
}

function readableWorkerPhase(value) {
  const raw = firstText(value);
  if (hasChineseText(raw)) return raw;
  if (/agent/i.test(raw)) return '执行器事件';
  if (/error|warning|stderr/i.test(raw)) return '执行器提醒';
  if (/turn|thread/i.test(raw)) return '执行器运行';
  return '执行器事件';
}

function collectLatestRefs() {
  const readback = readJsonIfExists(statusFiles.readback) || {};
  const owner = readJsonIfExists(statusFiles.owner) || {};
  const projectionOps = readJsonIfExists(statusFiles.projectionOps) || {};
  const taskId = firstText(
    readback.task_id,
    owner.task_id,
    readback.current_task_id,
    owner.current_task_id
  );
  const homepageAssignment = taskId
    ? readJsonIfExists(path.join(
      RUNTIME_ROOT,
      'state',
      'worker_assignment',
      `${taskId}.operator_status_panel_homepage_layers.json`
    )) || {}
    : {};

  return {
    readback,
    owner,
    projectionOps,
    homepageAssignment
  };
}

function humanAssignmentText(value) {
  const text = firstText(value);
  if (!text) return '';
  const marker = '::';
  if (text.includes(marker)) return text.slice(text.lastIndexOf(marker) + marker.length).trim();
  return text;
}

function latestLocalEpoch(refs) {
  const candidates = [
    toEpoch(refs.readback.generated_at),
    toEpoch(refs.readback.updated_at),
    toEpoch(refs.owner.generated_at),
    toEpoch(refs.owner.workflow_started_at),
    toEpoch(refs.projectionOps.generated_at),
    toEpoch(refs.owner.workflow_run_id)
  ];
  const max = Math.max(...candidates.filter((value) => Number.isFinite(value)));
  return Number.isFinite(max) ? max : null;
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function firstNextAction(payload) {
  const actions = payload && Array.isArray(payload.next_frontier) ? payload.next_frontier : [];
  if (actions.length === 0 || !actions[0] || typeof actions[0] !== 'object') return '';
  return firstText(actions[0].action, actions[0].action_id, actions[0].frontier_id);
}

function intValue(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : 0;
}

function firstMarkdownHeading(text) {
  if (typeof text !== 'string') return '';
  const match = text.match(/^#\s+(.+)$/m);
  if (!match) return '';
  return match[1].trim().replace(/^\d+\s+/, '');
}

function loadCurrentTaskPackage() {
  const manifest = readJsonIfExists(CURRENT_TASK_PACKAGE_PATH) || {};
  const packageDir = path.dirname(CURRENT_TASK_PACKAGE_PATH);
  const entrypoint = firstText(manifest.entrypoint);
  const entrypointPath = entrypoint ? path.join(packageDir, entrypoint) : '';
  const entrypointText = entrypointPath ? readTextIfExists(entrypointPath) : '';
  const title = firstMarkdownHeading(entrypointText) || firstText(manifest.package_mode, '当前 P0 任务包');
  return {
    manifest,
    package_path: CURRENT_TASK_PACKAGE_PATH,
    entrypoint,
    entrypoint_path: entrypointPath,
    title,
    intent: `锚定当前任务包 ${path.basename(CURRENT_TASK_PACKAGE_PATH)} / ${entrypoint || '入口未返回'}；按“文本目标 -> 本地真实进度 -> mature carrier 绑定 -> 缺口 -> 下一机器动作”推进。`
  };
}

function normalizePanelLinesToFeed(panelLines, fallbackTime = Date.now()) {
  const now = fallbackTime || Date.now();
  if (!panelLines) return [];
  if (Array.isArray(panelLines)) {
    return normalizePhaseFeed(panelLines, '阶段更新', now);
  }
  if (typeof panelLines !== 'object') return [];

  const rows = [
    {
      phase: '当前意图',
      conclusion: panelLines.status_line_cn || panelLines.current_status_cn || panelLines.status || panelLines.user_visible_summary_cn,
      impact: panelLines.can_user_use_scope_cn || panelLines.next_line_cn || panelLines.next_line
    },
    {
      phase: '卡点',
      conclusion: panelLines.blocked_line_cn || panelLines.blocker || panelLines.named_blocker,
      impact: '影响：卡点信息来自 panel_lines_cn 的最新读回。'
    },
    {
      phase: '下一步',
      conclusion: panelLines.next_line_cn || panelLines.next_machine_action_cn || panelLines.next_action,
      impact: panelLines.next_line_cn || panelLines.next_action || '影响：继续展示下一步指引。'
    },
    {
      phase: '状态摘要',
      conclusion: panelLines.status_line_cn || panelLines.status_line || panelLines.status_cn,
      impact: panelLines.summary || '影响：请以本地状态盘为主。'
    }
  ];

  return rows
    .map((row, index) => normalizeIncomingPhase({
      at: now - index * 1000,
      phase: row.phase,
      conclusion: row.conclusion,
      impact: row.impact
    }, now - index * 1000))
    .filter(Boolean);
}

function normalizeIncomingPhase(item, fallbackTime) {
  if (!item || typeof item !== 'object') return null;
  const at = toEpoch(item.at)
    || toEpoch(item.timestamp)
    || toEpoch(item.generated_at)
    || fallbackTime
    || Date.now();
  const phase = firstText(item.phase, item.phase_cn, item.label, item.title, item.name, item.stage, '阶段更新');
  const conclusion = normalizeChineseText(firstText(item.conclusion, item.summary, item.text, item.message, item.message_cn, item.status, '阶段未返回中文结论'), '');
  const impact = normalizeChineseText(firstText(item.impact, item.impact_cn, item.delta, item.result, item.change, '影响：无明显新增'), '');
  return {
    at: toDisplayTime(at),
    phase,
    conclusion,
    impact,
    _sort_at: Number.isFinite(at) ? at : Date.now()
  };
}

function normalizePhaseFeed(input, fallbackStatus, fallbackTime) {
  if (!Array.isArray(input) || input.length === 0) return [];
  return input
    .map((item, index) => normalizeIncomingPhase(item, fallbackTime + index * 1000))
    .filter(Boolean)
    .filter((item) => Boolean(item.phase) || Boolean(item.conclusion))
    .map((item) => {
      item.conclusion = firstText(item.conclusion, fallbackStatus || '阶段未返回中文结论');
      if (!item.impact) item.impact = '影响：更新状态已同步。';
      return item;
    });
}

function normalizeEndpointPhaseFeed(payload, fallbackStatus, fallbackTime) {
  const sourceFeed = safeArray(payload?.phase_feed);
  if (sourceFeed.length > 0) {
    return normalizePhaseFeed(sourceFeed, fallbackStatus, fallbackTime);
  }
  return [];
}

function parseWorkerEventFeed(filePath, fallbackSourceLabel) {
  const content = readTextIfExists(filePath);
  if (!content) return [];
  const lines = content.split(/\r?\n/).filter(Boolean);
  const items = [];
  const base = Date.now();

  lines.slice(-150).forEach((line, index) => {
    try {
      const event = JSON.parse(line);
      const rawText = firstText(
        event?.item?.text,
        event?.item?.message,
        event?.item?.content,
        event?.message,
        event?.text,
        event?.status
      );
      if (!hasChineseText(rawText)) return;
      const text = normalizeChineseText(rawText, '');
      const rawPhase = firstText(
        event?.item?.type,
        event?.type,
        event?.event,
        'worker 运行事件'
      );
      const phase = readableWorkerPhase(rawPhase);
      const at = toEpoch(event.timestamp) || toEpoch(event.generated_at) || base - index * 1000;
      const rawImpact = firstText(event?.item?.status, event?.status);
      items.push({
        at: toDisplayTime(at),
        phase,
        conclusion: text,
        impact: hasChineseText(rawImpact)
          ? normalizeChineseText(rawImpact)
          : `影响：来自 ${fallbackSourceLabel} 的中文 worker 事件，不需要用户打开日志。`,
        _sort_at: Number.isFinite(at) ? at : base - index * 1000
      });
    } catch {
      // Non-JSON line in event stream; ignore to avoid raw 日志墙.
    }
  });

  return items;
}

function summarizeLocalPhaseFromReadback(readback, refs) {
  const statusLines = readback.panel_lines_cn && typeof readback.panel_lines_cn === 'object'
    ? readback.panel_lines_cn
    : {};
  const base = Date.now();
  const items = [];
  const pushText = (phase, text, impact) => {
    const line = normalizeChineseText(text, '');
    if (!line) return;
    items.push({
      at: toDisplayTime(base - items.length * 1000),
      phase,
      conclusion: line,
      impact: normalizeChineseText(impact, '影响：更新已同步。'),
      _sort_at: base - items.length * 1000
    });
  };

  pushText(
    '当前意图',
    firstText(statusLines.status_line_cn, statusLines.current_status_cn, readback.status_cn, readback.status_line_cn, readback.status_line, '状态面已更新'),
    firstText(readback.can_user_use_scope_cn, readback.next_machine_action_cn, '影响：用户可见状态已刷新。')
  );
  pushText(
    '卡点',
    firstText(statusLines.blocked_line_cn, readback.blocked_line_cn, readback.blocked_at_cn, readback.named_blocker, '未声明'),
    firstText(readback.next_machine_action_cn, statusLines.next_line_cn, '影响：若有卡点将按 next_machine_action 提示。')
  );
  pushText(
    '证据',
    firstText(readback.worker_jsonl_path, readback.worker_final_path, refs.owner.worker_jsonl_path)
      ? 'worker 证据已写入，后续 AI 可按任务证据续接。'
      : 'worker 证据已采集，等待下一次读回补齐。',
    firstText(statusLines.next_line_cn, readback.next_line_cn, '影响：不需要用户打开日志；详细路径保留在折叠详情里。')
  );
  pushText(
    '投影运维',
    firstText(refs.projectionOps?.status_cn, refs.projectionOps?.status, '运维状态已更新'),
    `状态：${firstText(refs.projectionOps?.mode, 'stable')} · ${firstText(refs.projectionOps?.generated_at, '已有局部状态')}`
  );
  return items;
}

function appendContinuations(items, refs, fallbackTimeBase) {
  const continuation = refs.owner?.partial_continuation_dispatch;
  if (!continuation || typeof continuation !== 'object') return;
  const now = fallbackTimeBase || Date.now();
  items.push({
    at: toDisplayTime(toEpoch(continuation.started_at) || toEpoch(continuation.finished_at) || now),
    phase: '续接执行',
    conclusion: normalizeChineseText(
      /[\u4e00-\u9fff]/.test(firstText(
        continuation.status,
        continuation.activity,
        continuation.action,
        continuation.next_required_activity,
        continuation.completion_decision?.status
      ))
        ? firstText(
          continuation.status,
          continuation.activity,
          continuation.action,
          continuation.next_required_activity,
          continuation.completion_decision?.status
        )
        : `续接执行状态：${firstText(continuation.status, continuation.completion_decision?.status, '已派发')}`,
      '已派发下一段执行。'
    ),
    impact: normalizeChineseText(firstText(
      continuation.next_required_activity,
      continuation.command_surface,
      continuation.task_bound_worker ? '当前任务可继续递归执行。' : ''
    ), '影响：继续执行续接，不影响现有主线。'),
    _sort_at: Number.isFinite(toEpoch(continuation.started_at)) ? toEpoch(continuation.started_at) : now
  });

  const continuationJsonl = readTextIfExists(continuation.jsonl_path);
  if (continuationJsonl) {
    const workerItems = parseWorkerEventFeed(continuation.jsonl_path, 'partial continuation');
    items.push(...workerItems);
  }
}

function composePhaseFeed(endpointPayload, localFields, refs) {
  const now = Date.now();
  const endpointFeed = normalizeEndpointPhaseFeed(endpointPayload, localFields.status, now);
  if (endpointFeed.length > 0) {
    return sanitizePhaseFeed(endpointFeed);
  }

  const localFeed = [];
  localFeed.push(...summarizeLocalPhaseFromReadback(refs.readback, refs));
  appendContinuations(localFeed, refs, now);

  const ownerRefs = [refs.readback, refs.owner, refs.projectionOps].filter(Boolean);
  for (const source of ownerRefs) {
    const eventPath = source.worker_jsonl_path;
    if (typeof eventPath === 'string' && eventPath) {
      localFeed.push(...parseWorkerEventFeed(eventPath, 'worker'));
    }
  }

  localFeed.push(...normalizePhaseFeed(localFields.panel_feed, localFields.status, now));
  const sorted = sanitizePhaseFeed(localFeed);
  if (sorted.length > 0) return sorted;
  return [{
    at: '等待刷新',
    phase: '事件流',
    conclusion: '还没有返回阶段事件。',
    impact: '影响：自动刷新继续等待真实事件。'
  }];
}

function sanitizePhaseFeed(list) {
  const normalized = safeArray(list)
    .map((item) => ({
      at: firstText(item?.at, '时间未返回'),
      phase: normalizeChineseText(firstText(item?.phase, '阶段更新'), '阶段更新'),
      conclusion: normalizeChineseText(firstText(item?.conclusion, '阶段结论待更新。'), ''),
      impact: normalizeChineseText(firstText(item?.impact, '影响：状态同步中。'), ''),
      _sort_at: Number.isFinite(item?._sort_at)
        ? item._sort_at
        : toEpoch(item?.at) || Date.now()
    }))
    .filter((item) => item.phase && item.conclusion);

  normalized.sort((a, b) => (b._sort_at || 0) - (a._sort_at || 0));
  const dedup = [];
  const seen = new Set();
  for (const item of normalized) {
    const key = `${item.phase}||${item.conclusion}`;
    if (seen.has(key)) continue;
    seen.add(key);
    dedup.push(item);
    if (dedup.length >= PHASE_FEED_MAX) break;
  }
  return dedup.map(({ at, phase, conclusion, impact }) => ({ at, phase, conclusion, impact }));
}

function sanitizedWithSort(list) {
  return sanitizePhaseFeed(list);
}

function extractLocalFields(refs) {
  const readback = refs.readback;
  const owner = refs.owner;
  const projectionOps = refs.projectionOps;
  const homepageAssignment = refs.homepageAssignment || {};
  const productContract = homepageAssignment.product_contract || {};
  const task = firstText(
    readback.task_id,
    owner.task_id,
    readback.current_task_id,
    owner.current_task_id,
    readback.route_id,
    owner.workflow_id,
    '未绑定当前任务'
  );
  const currentIntent = firstText(
    readback.current_intent,
    readback.intent_cn,
    readback.intent,
    homepageAssignment.user_intent_cn,
    humanAssignmentText(homepageAssignment.semantic_object),
    owner.current_intent,
    owner.intention,
    '交付本地操作员只读状态盘 Mission Control Lite 小窗 exe'
  );
  const currentTransaction = firstText(
    readback.current_transaction,
    readback.current_goal,
    readback.current_goal_cn,
    readback.transaction,
    '双击 XINAOSurface.exe 后，默认看到总意图和最近中文事件流，状态会自动刷新。',
    productContract.required_homepage,
    owner.current_transaction,
    readback.transaction_cn,
    '默认首屏显示上层当前任务总意图和下层事件流。'
  );
  const status = firstText(
    readback.status_cn,
    readback.user_visible_summary_cn,
    readback.status_line_cn,
    readback.headline,
    owner.execution_event_source,
    '未返回状态'
  );
  const blocker = firstText(
    readback.named_blocker,
    readback.blocked_at_cn,
    readback.blocked_line_cn,
    owner.named_blocker,
    '未声明'
  );
  const next = firstText(
    readback.next_machine_action_cn,
    readback.next_line_cn,
    readback.next,
    projectionOps.status_cn,
    '等待下一条机器动作'
  );
  const evidence = firstText(
    readback.worker_jsonl_path,
    readback.worker_final_path,
    owner.workflow_id,
    readback.route,
    owner.execution_surface,
    '等待证据更新'
  );
  const updated = firstText(
    readback.updated_at,
    readback.generated_at,
    owner.generated_at,
    projectionOps.generated_at,
    new Date().toISOString()
  );
  const source = '当前运行态';

  const needUserAction = firstText(
    toChineseBoolean(readback.completion_claim_allowed),
    toChineseBoolean(readback.needs_user_action),
    toChineseBoolean(readback.manual_intervention_needed),
    toChineseBoolean(owner.completion_claim_allowed),
    toChineseBoolean(owner.needs_user_action),
    '否'
  );

  return {
    task,
    current_intent: operatorDisplayCopy(currentIntent),
    current_transaction: operatorDisplayCopy(currentTransaction),
    status: operatorDisplayCopy(status),
    blocker: operatorDisplayCopy(blocker),
    next: operatorDisplayCopy(next),
    evidence,
    updated,
    source,
    need_user_action: needUserAction,
    panel_feed: summarizeLocalPhaseFromReadback(readback, refs)
  };
}

function normalizeEndpointPayload(payload) {
  const task = firstText(
    payload?.current_task_id,
    payload?.task_id,
    payload?.task,
    payload?.taskId,
    payload?.task?.id
  );
  const currentIntent = firstText(
    payload?.current_intent,
    payload?.intent_cn,
    payload?.intent,
    payload?.goal_name,
    payload?.task,
    '当前意图未返回'
  );
  const currentTransaction = firstText(
    payload?.current_transaction,
    payload?.current_goal,
    payload?.goal_cn,
    payload?.transaction_cn,
    payload?.transaction,
    task || '当前事务未返回'
  );
  const status = firstText(
    payload?.status_cn,
    payload?.status,
    payload?.status_text,
    payload?.overall_status,
    payload?.message_cn,
    payload?.message
  );
  const blocker = firstText(
    payload?.named_blocker,
    payload?.blocker_cn,
    payload?.blocker,
    payload?.blocked_at_cn
  );
  const next = firstText(
    payload?.next_cn,
    payload?.next_machine_action_cn,
    payload?.next_action,
    payload?.next_expected_action,
    payload?.next
  );
  const evidenceSummary = payload?.evidence_summary
    ? firstText(
      payload.evidence_summary.evidence_completeness_status,
      Array.isArray(payload.evidence_summary.missing_evidence) && payload.evidence_summary.missing_evidence.length
        ? `缺少证据：${payload.evidence_summary.missing_evidence.join('；')}`
        : ''
    )
    : '';
  const evidence = firstText(
    payload?.evidence,
    payload?.evidence_cn,
    payload?.evidence_path,
    payload?.worker_jsonl_path,
    payload?.worker_final_path,
    evidenceSummary
  );
  const updated = firstText(payload?.updated_at, payload?.generated_at, payload?.timestamp, new Date().toISOString());
  const source = 'operator/current-view';
  const needUserAction = firstText(
    toChineseBoolean(payload?.requires_user_action),
    toChineseBoolean(payload?.needs_user_action),
    toChineseBoolean(payload?.need_user_action),
    '否'
  );
  return {
    task,
    current_intent: operatorDisplayCopy(currentIntent),
    current_transaction: operatorDisplayCopy(currentTransaction),
    status: operatorDisplayCopy(status),
    blocker: operatorDisplayCopy(blocker),
    next: operatorDisplayCopy(next),
    evidence,
    updated,
    source,
    need_user_action: needUserAction,
    panel_feed: normalizePanelLinesToFeed(payload?.panel_lines_cn, toEpoch(payload?.generated_at) || Date.now()),
    phase_feed_raw: safeArray(payload?.phase_feed)
  };
}

function isOperatorViewPayload(payload) {
  return payload
    && typeof payload === 'object'
    && payload.schema_version === 'xinao.surface.operator_view.v1'
    && payload.fields
    && typeof payload.fields === 'object'
    && Array.isArray(payload.fields.phase_feed);
}

function normalizeOperatorViewEndpointPayload(payload) {
  const fields = payload.fields || {};
  return {
    ...payload,
    source: 'operator_endpoint',
    generated_at: firstText(payload.generated_at, new Date().toISOString()),
    data_source: Array.isArray(payload.data_source) ? payload.data_source : [STATUS_ENDPOINT],
    fields: {
      ...fields,
      current_goal: firstText(fields.current_goal, '当前任务'),
      current_intent: firstText(fields.current_intent, '当前意图未返回'),
      current_transaction: firstText(fields.current_transaction, '当前事务未返回'),
      status: firstText(fields.status, 'operator/current-view 已返回'),
      need_user_action: firstText(fields.need_user_action, '否') === '是' ? '是' : '否',
      phase_feed: sanitizePhaseFeed(fields.phase_feed)
    },
    reason: firstText(
      payload.reason,
      '默认工作面只固定当前任务和实时事件流；已读取 operator/current-view 标准 OperatorViewPayload。'
    )
  };
}

function readOperatorStatus() {
  return new Promise((resolve, reject) => {
    const request = http.get(STATUS_ENDPOINT, { timeout: ENDPOINT_TIMEOUT_MS }, (res) => {
      const chunks = [];
      res.on('data', (chunk) => {
        chunks.push(chunk);
      });
      res.on('end', () => {
        if (res.statusCode !== 200) {
          reject(new Error(`operator status endpoint status=${res.statusCode}`));
          return;
        }
        try {
          const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
          resolve(payload);
        } catch (error) {
          reject(error);
        }
      });
    });

    request.on('timeout', () => request.destroy(new Error(`operator status endpoint timeout ${ENDPOINT_TIMEOUT_MS}ms`)));
    request.on('error', reject);
  });
}

async function buildStatusBoard() {
  const taskPackage = loadCurrentTaskPackage();
  const paths = {
    taskPackage: taskPackage.package_path,
    route: path.join(RUNTIME_ROOT, 'state', 'current_route', 'latest.json'),
    mainLoop: path.join(RUNTIME_ROOT, 'state', 'codex_s_main_execution_loop_tick', 'latest.json'),
    workerDispatch: path.join(RUNTIME_ROOT, 'state', 'worker_dispatch_ledger', 'latest.json'),
    workerPool: path.join(RUNTIME_ROOT, 'state', 'modular_dynamic_worker_pool_phase1', 'latest.json'),
    nextFrontier: path.join(RUNTIME_ROOT, 'state', 'next_frontier_machine_actions', 'latest.json'),
    sourceFamily: path.join(RUNTIME_ROOT, 'state', 'source_family_wave_scheduler', 'latest.json'),
    aaq: path.join(RUNTIME_ROOT, 'state', 'artifact_acceptance_queue', 'latest.json'),
    surfaceDeploy: path.join(RUNTIME_ROOT, 'state', 'xinao_surface_deploy', 'latest.json'),
    dpPort: path.join(RUNTIME_ROOT, 'state', 'dp_sidecar_execution_port', 'latest.json'),
    dpProvider: path.join(RUNTIME_ROOT, 'state', 'dp_sidecar_execution_provider', 'latest.json')
  };
  const refs = Object.fromEntries(
    Object.entries(paths).map(([key, file]) => [key, { file, payload: readJsonIfExists(file) || {} }])
  );
  const firstAction = firstNextAction(refs.nextFrontier.payload) || '等待下一条机器动作';
  const mainWave = firstText(
    refs.workerDispatch.payload.wave_id,
    refs.mainLoop.payload.wave_id,
    refs.workerPool.payload.wave_id,
    '当前 wave 未返回'
  );
  const acceptedCount = intValue(refs.aaq.payload.accepted_artifact_count);
  const events = [
    currentRuntimeEvent('当前任务包', taskPackage.package_path, {
      schema_version: taskPackage.manifest.schema_version,
      status: taskPackageModeText(taskPackage.manifest.package_mode),
      entrypoint: taskPackage.entrypoint
    }, `入口已锚定：${taskPackage.entrypoint || '未返回'}`),
    currentRuntimeEvent('333 主链', refs.mainLoop.file, refs.mainLoop.payload, `当前 wave：${mainWave}`),
    currentRuntimeEvent('派工账本', refs.workerDispatch.file, refs.workerDispatch.payload, `默认队列仍在轮询；completion_claim_allowed=${refs.workerDispatch.payload.completion_claim_allowed === false ? '否' : '未知'}`),
    currentRuntimeEvent('后台工人池', refs.workerPool.file, refs.workerPool.payload, `默认工人池：${firstText(refs.workerPool.payload.adoption_state, '运行态未返回')}`),
    currentRuntimeEvent('Source Family', refs.sourceFamily.file, refs.sourceFamily.payload, `源码族调度：${firstText(refs.sourceFamily.payload.adoption_state, '未返回')}`),
    currentRuntimeEvent('AAQ 验收队列', refs.aaq.file, refs.aaq.payload, `已接受 artifact：${acceptedCount}`),
    currentRuntimeEvent(
      '桌面壳部署',
      refs.surfaceDeploy.file,
      refs.surfaceDeploy.payload,
      surfaceDeployImpact(refs.surfaceDeploy.payload),
      { statusText: surfaceDeployStatusText(refs.surfaceDeploy.payload) }
    ),
    currentRuntimeEvent('下一机器动作', refs.nextFrontier.file, refs.nextFrontier.payload, `队头：${firstAction}`),
    currentRuntimeEvent('DP 执行口', refs.dpPort.file, refs.dpPort.payload, `DP/sidecar 最近状态：${firstText(refs.dpPort.payload.status, refs.dpProvider.payload.status, '未返回')}`)
  ];
  const now = Date.now();
  const pinnedSort = new Map([
    ['当前任务包', now + 3000],
    ['下一机器动作', now + 2000],
    ['333 主链', now + 1000]
  ]);
  for (const event of events) {
    if (pinnedSort.has(event.phase)) {
      event._sort_at = pinnedSort.get(event.phase);
    }
  }

  return {
    schema_version: 'xinao.surface.operator_view.v1',
    source: 'local_fallback',
    generated_at: new Date().toISOString(),
    data_source: Object.values(paths),
    fields: {
      current_goal: taskPackage.title,
      current_intent: taskPackage.intent,
      current_transaction: `当前 wave：${mainWave}；下一机器动作：${firstAction}`,
      status: `333 主链运行中；worker=${firstText(refs.workerDispatch.payload.status, '未返回')}；AAQ=${acceptedCount}；停止声明=否。`,
      need_user_action: '否',
      phase_feed: sanitizePhaseFeed(events)
    },
    reason: '默认工作面只固定当前任务和实时事件流；事件来自 D:\\XINAO_RESEARCH_RUNTIME 的 S runtime latest/read-model 聚合。'
  };
}

async function buildOperatorView() {
  const taskPackage = loadCurrentTaskPackage();
  const refs = collectLatestRefs();

  try {
    const endpointPayload = await readOperatorStatus();
    if (isOperatorViewPayload(endpointPayload)) {
      return normalizeOperatorViewEndpointPayload(endpointPayload);
    }
    const fields = normalizeEndpointPayload(endpointPayload);
    const phaseFeed = composePhaseFeed(endpointPayload, fields, refs);
    return {
      schema_version: 'xinao.surface.operator_view.v1',
      source: 'operator_endpoint',
      generated_at: new Date().toISOString(),
      data_source: [STATUS_ENDPOINT],
      fields: {
        current_goal: firstText(fields.task, taskPackage.title, '当前任务'),
        current_intent: firstText(fields.current_intent, taskPackage.intent),
        current_transaction: firstText(fields.current_transaction, taskPackage.intent),
        status: firstText(fields.status, 'operator/current-view 已返回'),
        need_user_action: fields.need_user_action,
        phase_feed: sanitizePhaseFeed(phaseFeed)
      },
      reason: '默认工作面只固定当前任务和实时事件流；优先读取 operator/current-view，失败时回退本地 runtime read-model。'
    };
  } catch {
    return buildStatusBoard();
  }
}

function currentRuntimeEvent(phase, filePath, payload, impact, options = {}) {
  const mtime = fileMtime(filePath);
  const status = firstText(options.statusText, payload.status, payload.adoption_state, payload.schema_version, '状态待刷新');
  const validation = payload.validation && typeof payload.validation === 'object'
    ? payload.validation.passed
    : undefined;
  const validationText = typeof validation === 'boolean' ? `；验证=${validation ? '通过' : '未通过'}` : '';
  const wave = firstText(payload.wave_id, payload.task_id, '');
  return {
    at: mtime ? toDisplayTime(mtime) : '等待刷新',
    phase,
    conclusion: wave ? `${status}${validationText}；${wave}` : `${status}${validationText}`,
    impact,
    _sort_at: mtime || 0
  };
}

function fileMtime(filePath) {
  try {
    return fs.statSync(filePath).mtimeMs;
  } catch {
    return null;
  }
}

function createWindow() {
  const savedBounds = readWindowBounds();
  const win = new BrowserWindow({
    ...savedBounds,
    minWidth: MIN_WIDTH,
    minHeight: MIN_HEIGHT,
    backgroundColor: '#eef1f3',
    frame: false,
    resizable: true,
    show: false,
    title: 'XINAOSurface',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  win.once('ready-to-show', () => {
    win.show();
    if (isSmoke) {
      setTimeout(async () => {
        const image = await win.webContents.capturePage();
        const out = path.join(app.getPath('temp'), 'xinao-surface-smoke.png');
        fs.writeFileSync(out, image.toPNG());
        console.log(JSON.stringify({ screenshot: out, size: image.getSize() }));
        app.quit();
      }, 650);
    }
  });

  win.on('close', () => saveWindowBounds(win));
  win.loadFile(path.join(__dirname, 'renderer-dist', 'index.html'));
  return win;
}

app.whenReady().then(() => {
  const win = createWindow();

  ipcMain.handle('window:minimize', () => win.minimize());
  ipcMain.handle('window:toggle-maximize', () => {
    if (win.isMaximized()) {
      win.unmaximize();
    } else {
      win.maximize();
    }
  });
  ipcMain.handle('window:close', () => win.close());
  ipcMain.handle('status:read', () => buildOperatorView());
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
