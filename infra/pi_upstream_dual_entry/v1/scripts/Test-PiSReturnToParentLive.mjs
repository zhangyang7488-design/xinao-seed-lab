#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const sessionDir = path.resolve(process.argv[2] ?? "");
assert.equal(fs.statSync(sessionDir).isDirectory(), true, `missing session directory: ${sessionDir}`);

const candidates = fs.readdirSync(sessionDir, { withFileTypes: true })
	.filter((entry) => entry.isFile() && entry.name.endsWith(".jsonl"))
	.map((entry) => path.join(sessionDir, entry.name));

let accepted;
for (const sessionPath of candidates) {
	const records = fs.readFileSync(sessionPath, "utf8")
		.split(/\r?\n/)
		.filter(Boolean)
		.map((line) => JSON.parse(line));
	const session = records.find((record) => record.type === "session");
	for (let index = 0; index < records.length; index += 1) {
		const callRecord = records[index];
		const content = Array.isArray(callRecord.message?.content) ? callRecord.message.content : [];
		const call = content.find((item) => item?.type === "toolCall" && item.name === "return_to_parent");
		if (!call) continue;
		const result = records.find((record) =>
			record.parentId === callRecord.id
			&& record.message?.role === "toolResult"
			&& record.message?.toolName === "return_to_parent"
			&& record.message?.toolCallId === call.id,
		);
		if (!result) continue;
		const continuation = records.find((record) =>
			record.parentId === result.id
			&& record.message?.role === "assistant",
		);
		if (!continuation) continue;
		const resultText = Array.isArray(result.message.content)
			? result.message.content.map((item) => item?.text ?? "").join("\n")
			: "";
		const continuationContent = Array.isArray(continuation.message.content) ? continuation.message.content : [];
		const continuationToolNames = continuationContent
			.filter((item) => item?.type === "toolCall")
			.map((item) => item.name);
		const args = call.arguments ?? {};
		assert.equal(callRecord.message.provider, "openai-codex");
		assert.equal(callRecord.message.model, "gpt-5.6-sol");
		assert.equal(continuation.message.provider, "openai-codex");
		assert.equal(continuation.message.model, "gpt-5.6-sol");
		assert.match(resultText, /^LOCAL_BOUNDARY_ONLY/m);
		for (const field of ["local_boundary", "surviving_parent", "next_contact"]) {
			assert.equal(typeof args[field] === "string" && args[field].trim().length > 0, true, `${field} must be non-empty`);
		}
		assert.equal(continuationContent.length > 0, true);
		accepted = {
			schema: "xinao.pi_return_to_parent_live_sol_acceptance.v1",
			status: "live_sol_verified",
			maturity: "not_yet_mature",
			session_id: session?.id,
			session_file: sessionPath,
			provider: callRecord.message.provider,
			model: callRecord.message.model,
			tool_call_id: call.id,
			tool_call_timestamp: callRecord.timestamp,
			tool_result_timestamp: result.timestamp,
			continuation_timestamp: continuation.timestamp,
			actual_provider_tool_call: true,
			local_boundary_named: true,
			surviving_parent_named: true,
			next_contact_named: true,
			tool_result_consumed_before_continuation: true,
			same_run_continued: true,
			continuation_tool_names: continuationToolNames,
		};
	}
}

assert.ok(accepted, "no live Sol return_to_parent call followed by same-run continuation was found");
process.stdout.write(`${JSON.stringify(accepted, null, 2)}\n`);
