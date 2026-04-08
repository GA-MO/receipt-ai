import type { AiAnalysis, FraudFlag, FraudResult } from "../api/client";

export function parseFraudData(raw: string | null): FraudResult {
  if (!raw) return { flags: [], ai_analysis: null };
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return { flags: parsed, ai_analysis: null };
    }
    return {
      flags: parsed.flags ?? [],
      ai_analysis: parsed.ai_analysis ?? null,
    };
  } catch {
    return { flags: [], ai_analysis: null };
  }
}

export function parseFraudFlags(raw: string | null): FraudFlag[] {
  return parseFraudData(raw).flags;
}

export function parseAiAnalysis(raw: string | null): AiAnalysis | null {
  return parseFraudData(raw).ai_analysis;
}

export function riskScoreColor(score: number): string {
  if (score >= 0.6) return "red";
  if (score >= 0.3) return "yellow";
  return "green";
}

export function riskScoreLabel(score: number): string {
  if (score >= 0.6) return "เสี่ยงสูง";
  if (score >= 0.3) return "เสี่ยงปานกลาง";
  return "เสี่ยงต่ำ";
}
