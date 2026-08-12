import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const RETURN_SCHEMA = "xinao.pi_return_to_parent.v5";
const CONTINUATION_SCHEMA = "xinao.pi_return_to_parent_continuation.v4";

interface ContinuationArm {
	armId: string;
	sequence: number;
	localBoundary: string;
	activityContextRef: string;
	returnedFact: string;
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

function trimmed(value: string): string {
	return value.trim();
}

export default function returnToParent(pi: ExtensionAPI): void {
	// This is a root-only transport seam. Bounded Pi children already return
	// through the subagent tool result.
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
			const signalMatches = (
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
		// must not leave a latent delivery for a later unrelated prompt.
		const arm = armed;
		armed = undefined;
		if (!arm || shuttingDown) return;
		continuationContextGrant = undefined;

		const signal = ctx.signal;
		const lastAssistant = [...event.messages]
			.reverse()
			.find((message) => message.role === "assistant");
		// Only an explicit, ordinary terminal stop is clean. Length/max-token,
		// deferred, toolUse, pending, error, and aborted exits cannot auto-deliver.
		if (!signal || signal !== arm.runSignal || signal.aborted || !lastAssistant || lastAssistant.stopReason !== "stop") return;
		continuationContextGrant = { armId: arm.armId, sequence: arm.sequence, sourceSignal: signal };

		pi.sendMessage(
			{
				customType: "xinao-return-to-parent-continuation",
				display: true,
				content: [
					"ROOT_ACTIVITY_RETURN_ONE_SHOT",
					`Local boundary: ${arm.localBoundary}`,
					`Activity context ref: ${arm.activityContextRef}`,
					`Returned fact: ${arm.returnedFact}`,
					"This one-shot transport is spent.",
				].join("\n"),
					details: {
						schema: CONTINUATION_SCHEMA,
						arm_id: arm.armId,
						arm_sequence: arm.sequence,
						local_boundary: arm.localBoundary,
						activity_context_ref: arm.activityContextRef,
						returned_fact: arm.returnedFact,
						one_shot: true,
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
			"Root Pi only: transport one bounded local fact across one clean terminal turn boundary. Bounded children return through their caller and never use this tool.",
		promptSnippet:
			"return_to_parent: one-shot transport for a bounded local fact",
		promptGuidelines: [
			"Only the root Pi may use this tool. Supply the bounded local boundary, an opaque activity context reference, and the exact returned fact.",
			"One clean stopReason=stop may deliver one native follow-up. Abort, error, length, shutdown, unrelated prompt, and resumed history stay fenced.",
		],
		parameters: Type.Object(
			{
				local_boundary: Type.String({
					minLength: 1,
					maxLength: 1600,
					description: "A caller-named bounded local scope identifier or description.",
				}),
				activity_context_ref: Type.String({
					minLength: 1,
					maxLength: 2400,
					description: "An opaque reference to the activity context in which the fact was produced.",
				}),
				returned_fact: Type.String({
					minLength: 1,
					maxLength: 1600,
					description: "The exact bounded fact to transport as text or serialized JSON.",
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
			const activityContextRef = cleaned(params.activity_context_ref);
			const returnedFact = trimmed(params.returned_fact);
			if (!localBoundary || !activityContextRef || !returnedFact) {
				throw new Error("RETURN_TO_PARENT_FIELDS_REQUIRED_AFTER_NORMALIZATION");
			}
			armed = {
				armId: randomUUID(),
				sequence: ++armSequence,
				localBoundary,
				activityContextRef,
				returnedFact,
				runSignal: signal,
			};
			return {
				content: [
					{
						type: "text",
						text: [
							"LOCAL_FACT_RETURN_ARMED",
							`Local boundary: ${localBoundary}`,
							`Activity context ref: ${activityContextRef}`,
							`Returned fact: ${returnedFact}`,
						].join("\n"),
					},
				],
				details: {
					schema: RETURN_SCHEMA,
					local_boundary: localBoundary,
					activity_context_ref: activityContextRef,
					returned_fact: returnedFact,
					arm_id: armed.armId,
					arm_sequence: armed.sequence,
					one_shot_follow_up_armed: true,
					abort_fenced: true,
					clean_terminal_stop_required: true,
				},
			};
		},
	});
}
