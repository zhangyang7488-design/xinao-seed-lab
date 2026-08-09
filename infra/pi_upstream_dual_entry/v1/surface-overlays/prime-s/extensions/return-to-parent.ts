import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const RETURN_SCHEMA = "xinao.pi_return_to_parent.v3";
const CONTINUATION_SCHEMA = "xinao.pi_return_to_parent_continuation.v2";

interface ContinuationArm {
	armId: string;
	sequence: number;
	localBoundary: string;
	survivingParent: string;
	nextContact: string;
	runSignal: AbortSignal | undefined;
}

interface ContinuationContextGrant {
	armId: string;
	sequence: number;
	sourceSignal: AbortSignal;
	candidateRunSignal?: AbortSignal;
	continuationRunSignal?: AbortSignal;
}

function cleaned(value: string): string {
	return value.replace(/\s+/g, " ").trim();
}

export default function returnToParent(pi: ExtensionAPI): void {
	// This is a root-subject seam. Bounded Pi children already return through the
	// subagent tool result and must never inherit a second lifecycle authority.
	if (process.env.PI_SUBAGENT_CHILD === "1") return;
	// The extension must not expose an unsafe half-install. Start sets this only
	// after the native abort-fence compatibility has applied or verified cleanly.
	if (process.env.XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE !== "1") return;

	let armSequence = 0;
	let armed: ContinuationArm | undefined;
	let continuationContextGrant: ContinuationContextGrant | undefined;
	let shuttingDown = false;

	pi.on("session_start", () => {
		shuttingDown = false;
		armed = undefined;
		continuationContextGrant = undefined;
	});

	pi.on("session_shutdown", () => {
		shuttingDown = true;
		armed = undefined;
		continuationContextGrant = undefined;
	});

	pi.on("agent_start", (_event, ctx) => {
		const grant = continuationContextGrant;
		if (!grant) return;
		if (grant.sourceSignal.aborted) {
			continuationContextGrant = undefined;
			return;
		}
		if (!grant.continuationRunSignal) grant.candidateRunSignal = ctx.signal;
	});

	pi.on("context", (event, ctx) => {
		const grant = continuationContextGrant;
		let admittedCurrentGrant = false;
		const messages = event.messages.filter((message) => {
			if (message.role !== "custom" || message.customType !== "xinao-return-to-parent-continuation") return true;
			const details = message.details as { arm_id?: unknown; arm_sequence?: unknown } | undefined;
			const currentSignal = ctx.signal;
			if (!currentSignal) return false;
			const signalMatches = currentSignal !== undefined && (
				grant?.continuationRunSignal === currentSignal
				|| (!grant?.continuationRunSignal && grant?.candidateRunSignal === currentSignal)
			);
			const admitted = !admittedCurrentGrant
				&& grant !== undefined
				&& !grant.sourceSignal.aborted
				&& !currentSignal.aborted
				&& signalMatches
				&& details?.arm_id === grant.armId
				&& details?.arm_sequence === grant.sequence;
			if (admitted) {
				admittedCurrentGrant = true;
				grant.continuationRunSignal ??= currentSignal;
			}
			return admitted;
		});
		// Once matched, the tagged arm remains visible to every provider context in
		// this same continuation agent run. agent_end spends the grant; other run
		// signals, resumed history, stopped runs, and duplicate copies stay filtered.
		if (
			grant?.sourceSignal.aborted
			|| grant?.candidateRunSignal?.aborted
			|| grant?.continuationRunSignal?.aborted
		) continuationContextGrant = undefined;
		return { messages };
	});

	pi.on("agent_end", (event, ctx) => {
		const endingGrant = continuationContextGrant;
		if (endingGrant?.continuationRunSignal === ctx.signal) {
			continuationContextGrant = undefined;
		} else if (endingGrant?.candidateRunSignal === ctx.signal) {
			if (ctx.signal?.aborted) continuationContextGrant = undefined;
			else endingGrant.candidateRunSignal = undefined;
		}
		// Consume before checking any exit condition. A failed/aborted/shutdown run
		// must not leave a latent continuation for a later unrelated prompt.
		const arm = armed;
		armed = undefined;
		if (!arm || shuttingDown) return;
		continuationContextGrant = undefined;

		const signal = ctx.signal;
		const lastAssistant = [...event.messages]
			.reverse()
			.find((message) => message.role === "assistant");
		// Only an explicit, ordinary terminal stop is clean. Length/max-token,
		// deferred, toolUse, pending, error, and aborted exits cannot auto-continue.
		if (!signal || signal !== arm.runSignal || signal.aborted || !lastAssistant || lastAssistant.stopReason !== "stop") return;
		continuationContextGrant = { armId: arm.armId, sequence: arm.sequence, sourceSignal: signal };

		pi.sendMessage(
			{
				customType: "xinao-return-to-parent-continuation",
				display: true,
				content: [
					"ROOT_PARENT_CONTINUATION_ONE_SHOT",
					"A root-local boundary explicitly armed this one additional cognition turn.",
					`Settled local scope: ${arm.localBoundary}`,
					`Surviving parent: ${arm.survivingParent}`,
					"The contact below was the first concrete frontier named when the arm was set. It may already have been consumed by the run that just ended:",
					`Armed first contact: ${arm.nextContact}`,
					"Put every new effect and finding from that just-ended run back into the surviving parent and recompute the whole currently legal parent now. Do not mechanically repeat the armed contact. Directly take a further concrete positive-value contact only if one still exists. If the whole current legal space now truly has no positive-value action, or Stop/Pause/authority/effect boundaries apply, settle honestly without another continuation.",
					"This one-shot arm is now spent. Crossing another local boundary requires another explicit return_to_parent call by the root Pi.",
				].join("\n"),
					details: {
						schema: CONTINUATION_SCHEMA,
						arm_id: arm.armId,
						arm_sequence: arm.sequence,
					local_boundary: arm.localBoundary,
					surviving_parent: arm.survivingParent,
					armed_first_contact: arm.nextContact,
					one_shot: true,
					next_contact_may_already_be_consumed: true,
					abort_fenced: true,
					provider_context_visibility: "single_current_arm",
				},
			},
			{ deliverAs: "followUp", triggerTurn: true },
		);
	});

	pi.registerTool({
		name: "return_to_parent",
		label: "Return to Parent",
		description:
			"Root Pi only: close the named local scope and continue this same root run from an already-bound surviving parent. Bounded children return normally to their root caller and never use this tool. Call it only when the local question, experiment, action, repository slice, or report is settled but the current legal parent still has a concrete positive-value frontier. It does not create a parent, prove value, queue a user message, or authorize work beyond the current scope.",
		promptSnippet:
			"return_to_parent: cross a local boundary without turning it into parent completion or waiting for another user/Codex prompt",
		promptGuidelines: [
			"Only the root Pi may use this tool. Bounded children finish normally and return through their subagent result. When a local result is complete but an already-bound parent still has a concrete positive-value frontier, call return_to_parent before a terminal answer and continue from its tool result. The call also arms exactly one native follow-up after this root run ends cleanly, so the whole parent is recomputed with every effect produced after the call.",
			"The armed next_contact is first-contact evidence, not a task to repeat blindly: the current run may already consume it. A later local boundary needs another explicit root call. Do not call after Stop/Pause, at a real user-only or major external boundary, after parent completion, or when the whole current legal space truly has no positive-value action. This is not a timer, daemon, task generator, or reason to busy-loop.",
		],
		parameters: Type.Object(
			{
				local_boundary: Type.String({
					minLength: 1,
					maxLength: 1600,
					description: "The bounded local scope that has just settled; never name the whole parent here unless it is genuinely complete.",
				}),
				surviving_parent: Type.String({
					minLength: 1,
					maxLength: 2400,
					description: "The already-existing parent result or reality that remains live under current words and facts.",
				}),
				next_contact: Type.String({
					minLength: 1,
					maxLength: 1600,
					description: "The concrete unresolved reality, evidence, consumer, or action frontier to contact next without inventing a new task.",
				}),
			},
			{ additionalProperties: false },
		),
		executionMode: "sequential",
		async execute(_toolCallId, params, signal) {
			if (shuttingDown || signal?.aborted) {
				const error = new Error("RETURN_TO_PARENT_ABORTED");
				error.name = "AbortError";
				throw error;
			}

			const localBoundary = cleaned(params.local_boundary);
			const survivingParent = cleaned(params.surviving_parent);
			const nextContact = cleaned(params.next_contact);
			if (!localBoundary || !survivingParent || !nextContact) {
				throw new Error("RETURN_TO_PARENT_FIELDS_REQUIRED_AFTER_NORMALIZATION");
			}
			armed = {
				armId: randomUUID(),
				sequence: ++armSequence,
				localBoundary,
				survivingParent,
				nextContact,
				runSignal: signal,
			};
			return {
				content: [
					{
						type: "text",
						text: [
							"LOCAL_BOUNDARY_ONLY",
							`Settled local scope: ${localBoundary}`,
							`Surviving parent: ${survivingParent}`,
							`Return now to: ${nextContact}`,
							"Continue this same root run from the whole relevant parent. Recompute after the local result instead of reporting it as parent completion. Current Stop/Pause, authority, effect, and true whole-space no-action boundaries remain unchanged.",
						].join("\n"),
					},
				],
				details: {
					schema: RETURN_SCHEMA,
					local_boundary: localBoundary,
					surviving_parent: survivingParent,
					next_contact: nextContact,
					queued_message: false,
					automatic_wake: true,
					continuation_mode: "one_shot_agent_end_follow_up_abort_fenced",
					continuation_armed: true,
				},
			};
		},
	});
}
