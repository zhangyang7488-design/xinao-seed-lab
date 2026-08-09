import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const RETURN_SCHEMA = "xinao.pi_return_to_parent.v1";

function cleaned(value: string): string {
	return value.replace(/\s+/g, " ").trim();
}

export default function returnToParent(pi: ExtensionAPI): void {
	// This is a root-subject seam. Bounded Pi children already return through the
	// subagent tool result and must never inherit a second lifecycle authority.
	if (process.env.PI_SUBAGENT_CHILD === "1") return;

	pi.registerTool({
		name: "return_to_parent",
		label: "Return to Parent",
		description:
			"Root Pi only: close the named local scope and continue this same root run from an already-bound surviving parent. Bounded children return normally to their root caller and never use this tool. Call it only when the local question, experiment, action, repository slice, or report is settled but the current legal parent still has a concrete positive-value frontier. It does not create a parent, prove value, queue a user message, or authorize work beyond the current scope.",
		promptSnippet:
			"return_to_parent: cross a local boundary without turning it into parent completion or waiting for another user/Codex prompt",
		promptGuidelines: [
			"Only the root Pi may use this tool. Bounded children finish normally and return through their subagent result. When a local result is complete but an already-bound parent still has a concrete positive-value frontier, call return_to_parent before a terminal answer and continue from its tool result.",
			"Do not call return_to_parent after Stop/Pause, at a real user-only or major external boundary, after parent completion, or when the whole current legal space truly has no positive-value action. It is not a timer, daemon, task generator, or reason to busy-loop.",
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
			if (signal?.aborted) {
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
					automatic_wake: false,
				},
			};
		},
	});
}
