#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const sessionDir = path.resolve(process.argv[2] ?? "");
const expectedProvider = process.argv[3] ?? "openai-codex";
const expectedModel = process.argv[4] ?? "gpt-5.6-sol";
assert.equal(fs.statSync(sessionDir).isDirectory(), true, `missing session directory: ${sessionDir}`);

const candidates = fs.readdirSync(sessionDir, { withFileTypes: true })
	.filter((entry) => entry.isFile() && entry.name.endsWith(".jsonl"))
	.map((entry) => path.join(sessionDir, entry.name));

function isDescendant(record, ancestorId, byId) {
	let cursor = record;
	const visited = new Set();
	while (cursor?.parentId && !visited.has(cursor.parentId)) {
		if (cursor.parentId === ancestorId) return true;
		visited.add(cursor.parentId);
		cursor = byId.get(cursor.parentId);
	}
	return false;
}

function cleaned(value) {
	return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

let accepted;
for (const sessionPath of candidates) {
	const records = fs.readFileSync(sessionPath, "utf8")
		.split(/\r?\n/)
		.filter(Boolean)
		.map((line) => JSON.parse(line));
	const session = records.find((record) => record.type === "session");
	const byId = new Map(records.filter((record) => record.id).map((record) => [record.id, record]));
	for (let index = 0; index < records.length; index += 1) {
		const callRecord = records[index];
		const content = Array.isArray(callRecord.message?.content) ? callRecord.message.content : [];
		const call = content.find((item) => item?.type === "toolCall" && item.name === "return_to_parent");
		if (!call) continue;
		const rawArgs = call.arguments ?? {};
		const normalizedArgs = {
			local_boundary: cleaned(rawArgs.local_boundary),
			surviving_parent: cleaned(rawArgs.surviving_parent),
			next_contact: cleaned(rawArgs.next_contact),
		};
		if (Object.values(normalizedArgs).some((value) => !value)) continue;
		const matchingResults = records.filter((record) =>
			record.parentId === callRecord.id
			&& record.message?.role === "toolResult"
			&& record.message?.toolName === "return_to_parent"
			&& record.message?.toolCallId === call.id,
		);
		if (matchingResults.length > 1) {
			throw new Error(`RETURN_TO_PARENT_LIVE_TOOL_RESULT_AMBIGUOUS: tool_call_id=${call.id}`);
		}
		const result = matchingResults[0];
		if (!result) continue;
		const resultDetails = result.message?.details;
		if (
			resultDetails?.schema !== "xinao.pi_return_to_parent.v3"
			|| resultDetails.local_boundary !== normalizedArgs.local_boundary
			|| resultDetails.surviving_parent !== normalizedArgs.surviving_parent
			|| resultDetails.next_contact !== normalizedArgs.next_contact
		) continue;
		const resultIndex = records.indexOf(result);
		const descendantArms = records
			.map((record, recordIndex) => ({ record, recordIndex }))
			.filter(({ record, recordIndex }) =>
				recordIndex > resultIndex
				&& record.type === "custom_message"
				&& record.customType === "xinao-return-to-parent-continuation"
				&& record.details?.schema === "xinao.pi_return_to_parent_continuation.v2"
				&& isDescendant(record, result.id, byId),
			);
		const matchingArms = descendantArms.filter(({ record }) =>
			record.details?.local_boundary === normalizedArgs.local_boundary
			&& record.details?.surviving_parent === normalizedArgs.surviving_parent
			&& record.details?.armed_first_contact === normalizedArgs.next_contact,
		);
		if (matchingArms.length > 1) {
			throw new Error(`RETURN_TO_PARENT_LIVE_ARM_AMBIGUOUS: tool_call_id=${call.id}`);
		}
		if (matchingArms.length === 0) continue;
		if (descendantArms[0]?.record.id !== matchingArms[0].record.id) {
			throw new Error(`RETURN_TO_PARENT_LIVE_ARM_NOT_FIRST: tool_call_id=${call.id}`);
		}
		const continuationArm = matchingArms[0].record;
		const firstRunFinal = byId.get(continuationArm.parentId);
		const continuation = records.find((record) =>
			record.parentId === continuationArm.id
			&& record.message?.role === "assistant",
		);
		if (!firstRunFinal || !continuation) continue;
		const resultText = Array.isArray(result.message.content)
			? result.message.content.map((item) => item?.text ?? "").join("\n")
			: "";
		const continuationContent = Array.isArray(continuation.message.content) ? continuation.message.content : [];
		const continuationToolNames = continuationContent
			.filter((item) => item?.type === "toolCall")
			.map((item) => item.name);
		assert.equal(callRecord.message.provider, expectedProvider);
		assert.equal(callRecord.message.model, expectedModel);
		assert.equal(firstRunFinal.message?.role, "assistant");
		assert.equal(firstRunFinal.message?.stopReason, "stop");
		assert.equal(continuation.message.provider, expectedProvider);
		assert.equal(continuation.message.model, expectedModel);
		assert.match(resultText, /^LOCAL_BOUNDARY_ONLY/m);
		assert.match(continuationArm.content, /^ROOT_PARENT_CONTINUATION_ONE_SHOT/m);
		assert.match(continuationArm.content, /may already have been consumed/i);
		assert.match(continuationArm.content, /Do not mechanically repeat/i);
		assert.equal(continuationArm.details?.one_shot, true);
		assert.equal(typeof continuationArm.details?.arm_id === "string" && continuationArm.details.arm_id.length > 0, true);
		assert.equal(continuationArm.details?.next_contact_may_already_be_consumed, true);
		assert.equal(continuationArm.details?.abort_fenced, true);
		assert.equal(continuationArm.details?.provider_context_visibility, "single_current_arm");
		assert.equal(continuationContent.length > 0, true);
		accepted = {
			schema: "xinao.pi_return_to_parent_live_sol_acceptance.v3",
			status: "live_sol_native_continuation_abort_fenced_verified",
			maturity: "not_yet_mature",
			session_id: session?.id,
			session_file: sessionPath,
			provider: callRecord.message.provider,
			model: callRecord.message.model,
			tool_call_id: call.id,
			tool_call_timestamp: callRecord.timestamp,
			tool_result_timestamp: result.timestamp,
			first_run_final_timestamp: firstRunFinal.timestamp,
			continuation_arm_timestamp: continuationArm.timestamp,
			continuation_provider_timestamp: continuation.timestamp,
			actual_provider_tool_call: true,
			normalized_argument_binding: true,
			matching_tool_result_unique: true,
			matching_arm_first_and_unique: true,
			local_boundary_named: true,
			surviving_parent_named: true,
			next_contact_named: true,
			tool_result_consumed_before_first_run_final: true,
			first_run_reached_terminal_assistant_before_native_follow_up: true,
			native_custom_follow_up_triggered_second_provider: true,
			one_shot: true,
			arm_id: continuationArm.details.arm_id,
			next_contact_may_already_be_consumed: true,
			abort_fenced: true,
			provider_context_visibility: "single_current_arm",
			continuation_tool_names: continuationToolNames,
		};
	}
}

assert.ok(accepted, "no live Sol return_to_parent call reached a terminal assistant and then triggered the native one-shot continuation");
process.stdout.write(`${JSON.stringify(accepted, null, 2)}\n`);
