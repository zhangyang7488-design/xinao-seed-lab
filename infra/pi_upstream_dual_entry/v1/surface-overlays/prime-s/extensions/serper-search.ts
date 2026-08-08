import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const PROFILE = process.env.XINAO_PI_PROFILE ?? "";
const AGENT_DIR = process.env.PI_CODING_AGENT_DIR ?? "";
const CREDENTIAL_PATH = join(AGENT_DIR, "credentials", "serper.json");
const ENDPOINT = "https://google.serper.dev/search";
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const REQUEST_TIMEOUT_MS = 30_000;

type SerperCredential = {
	schema?: unknown;
	provider?: unknown;
	enabled?: unknown;
	apiKey?: unknown;
};

type SerperOrganicResult = {
	title?: unknown;
	link?: unknown;
	snippet?: unknown;
	position?: unknown;
};

type SerperResponse = {
	searchParameters?: { q?: unknown };
	answerBox?: { answer?: unknown; snippet?: unknown; title?: unknown; link?: unknown };
	knowledgeGraph?: { title?: unknown; type?: unknown; description?: unknown; website?: unknown };
	organic?: SerperOrganicResult[];
	peopleAlsoAsk?: Array<{ question?: unknown; snippet?: unknown; link?: unknown }>;
};

function text(value: unknown): string | undefined {
	if (typeof value !== "string") return undefined;
	const trimmed = value.replace(/\s+/g, " ").trim();
	return trimmed.length > 0 ? trimmed : undefined;
}

function readCredential(): string {
	if (!existsSync(CREDENTIAL_PATH)) throw new Error("SERPER_CREDENTIAL_NOT_CONFIGURED");
	let parsed: SerperCredential;
	try {
		parsed = JSON.parse(readFileSync(CREDENTIAL_PATH, "utf8")) as SerperCredential;
	} catch {
		throw new Error("SERPER_CREDENTIAL_INVALID_JSON");
	}
	if (
		parsed.schema !== "xinao.pi_serper_credential.v1" ||
		parsed.provider !== "serper" ||
		parsed.enabled !== true
	) {
		throw new Error("SERPER_CREDENTIAL_IDENTITY_MISMATCH");
	}
	const apiKey = text(parsed.apiKey);
	if (!apiKey) throw new Error("SERPER_CREDENTIAL_VALUE_MISSING");
	return apiKey;
}

function formatResponse(query: string, response: SerperResponse, limit: number): { output: string; resultCount: number } {
	const lines = [`Serper results for: ${query}`];
	const answer = text(response.answerBox?.answer) ?? text(response.answerBox?.snippet);
	if (answer) {
		lines.push("", `Answer: ${answer}`);
		const answerLink = text(response.answerBox?.link);
		if (answerLink) lines.push(`Source: ${answerLink}`);
	}
	const knowledge = response.knowledgeGraph;
	if (knowledge) {
		const title = text(knowledge.title);
		const description = text(knowledge.description);
		if (title || description) {
			lines.push("", `Knowledge: ${[title, text(knowledge.type)].filter(Boolean).join(" — ")}`);
			if (description) lines.push(description);
			const website = text(knowledge.website);
			if (website) lines.push(`Website: ${website}`);
		}
	}
	const organic = Array.isArray(response.organic) ? response.organic.slice(0, limit) : [];
	if (organic.length === 0) lines.push("", "No organic results returned.");
	for (let index = 0; index < organic.length; index += 1) {
		const item = organic[index];
		const title = text(item.title) ?? "Untitled result";
		const link = text(item.link) ?? "";
		const snippet = text(item.snippet);
		lines.push("", `[${index + 1}] ${title}`);
		if (link) lines.push(link);
		if (snippet) lines.push(snippet);
	}
	const questions = Array.isArray(response.peopleAlsoAsk) ? response.peopleAlsoAsk.slice(0, 3) : [];
	if (questions.length > 0) {
		lines.push("", "Related questions:");
		for (const item of questions) {
			const question = text(item.question);
			if (question) lines.push(`- ${question}`);
		}
	}
	return { output: lines.join("\n"), resultCount: organic.length };
}

export default function serperSearch(pi: ExtensionAPI): void {
	if (PROFILE !== "prime-s" || AGENT_DIR.length === 0 || !existsSync(CREDENTIAL_PATH)) return;

	pi.registerTool({
		name: "web_search",
		label: "Serper Search",
		description:
			"Search Google through the PiS profile's configured Serper credential. This is a strict single-provider tool: provider, authentication, quota, network, and response errors are returned directly and never trigger another search provider.",
		parameters: Type.Object({
			query: Type.String({ minLength: 1, maxLength: 500, description: "Search query" }),
			num: Type.Optional(Type.Integer({ minimum: 1, maximum: 10, description: "Number of organic results (default 8)" })),
			country: Type.Optional(Type.String({ minLength: 2, maxLength: 2, description: "Two-letter country code, such as us or cn" })),
			language: Type.Optional(Type.String({ minLength: 2, maxLength: 8, description: "Language code, such as en or zh-cn" })),
		}),
		async execute(_toolCallId, params, signal) {
			const query = params.query.trim();
			if (!query) throw new Error("SERPER_QUERY_REQUIRED");
			const num = params.num ?? 8;
			const apiKey = readCredential();
			const controller = new AbortController();
			const timeout = setTimeout(() => controller.abort(new Error("SERPER_REQUEST_TIMEOUT")), REQUEST_TIMEOUT_MS);
			const abort = () => controller.abort(signal.reason);
			if (signal.aborted) abort();
			else signal.addEventListener("abort", abort, { once: true });
			try {
				const body: Record<string, unknown> = { q: query, num };
				if (params.country) body.gl = params.country.toLowerCase();
				if (params.language) body.hl = params.language.toLowerCase();
				const response = await fetch(ENDPOINT, {
					method: "POST",
					headers: { "X-API-KEY": apiKey, "Content-Type": "application/json" },
					body: JSON.stringify(body),
					signal: controller.signal,
				});
				if (response.status === 401 || response.status === 403) throw new Error("SERPER_AUTH_REJECTED");
				if (response.status === 402 || response.status === 429) throw new Error("SERPER_QUOTA_REJECTED");
				if (!response.ok) throw new Error(`SERPER_HTTP_ERROR_${response.status}`);
				const raw = await response.text();
				if (Buffer.byteLength(raw, "utf8") > MAX_RESPONSE_BYTES) throw new Error("SERPER_RESPONSE_TOO_LARGE");
				let parsed: SerperResponse;
				try { parsed = JSON.parse(raw) as SerperResponse; }
				catch { throw new Error("SERPER_RESPONSE_INVALID_JSON"); }
				const formatted = formatResponse(query, parsed, num);
				return {
					content: [{ type: "text", text: formatted.output }],
					details: { provider: "serper", query, resultCount: formatted.resultCount, strictProvider: true },
				};
			} finally {
				clearTimeout(timeout);
				signal.removeEventListener("abort", abort);
			}
		},
	});
}
