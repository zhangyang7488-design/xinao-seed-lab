import { z } from 'zod';
import jsonata from 'jsonata';

const EventItemSchema = z.object({
  at: z.string().min(1),
  phase: z.string().min(1),
  conclusion: z.string().min(1),
  impact: z.string().min(1)
}).passthrough();

export const OperatorViewPayloadSchema = z.object({
  schema_version: z.literal('xinao.surface.operator_view.v1'),
  source: z.enum(['operator_endpoint', 'local_fallback']),
  generated_at: z.string().min(1),
  reason: z.string().optional(),
  data_source: z.array(z.string()).optional(),
  fields: z.object({
    current_goal: z.string().min(1),
    current_intent: z.string().min(1),
    current_transaction: z.string().min(1),
    status: z.string().min(1),
    need_user_action: z.enum(['是', '否']),
    phase_feed: z.array(EventItemSchema).min(1).max(40)
  }).passthrough()
}).passthrough();

const operatorViewProjection = jsonata(`{
  "headline": fields.current_goal,
  "intent": fields.current_intent,
  "transaction": fields.current_transaction,
  "status": fields.status,
  "needsUser": fields.need_user_action,
  "events": fields.phase_feed
}`);

export async function normalizeOperatorView(payload) {
  const parsed = OperatorViewPayloadSchema.safeParse(payload);
  const stable = parsed.success ? parsed.data : fallbackPayload(payload);
  const projected = await operatorViewProjection.evaluate(stable);
  return {
    ...stable,
    ui: projected
  };
}

function fallbackPayload(payload) {
  return {
    schema_version: 'xinao.surface.operator_view.v1',
    source: payload?.source === 'operator_endpoint' ? 'operator_endpoint' : 'local_fallback',
    generated_at: new Date().toISOString(),
    reason: 'OperatorViewPayload v1 校验失败，已进入稳定回退显示。',
    fields: {
      current_goal: '当前任务暂未返回',
      current_intent: '等待本地接口返回当前意图',
      current_transaction: '等待本地接口返回当前事务',
      status: '接口数据校验失败',
      need_user_action: '否',
      phase_feed: [{
        at: '等待刷新',
        phase: '接口校验',
        conclusion: '返回数据未满足 OperatorViewPayload v1。',
        impact: '影响：界面保持稳定，等待下一次刷新。'
      }]
    }
  };
}
