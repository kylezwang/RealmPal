/**
 * [skin:Class|Skin Name|Clothing|Accessory] tokens from the skin visualizer.
 */

export interface SkinSpec {
  className: string;
  skinName: string;
  clothing: string;
  accessory: string;
}

const SKIN_TOKEN = /\[skin:([^\]\n]+)\]/i;

export function parseSkinToken(content: string): SkinSpec | null {
  const match = content.match(SKIN_TOKEN);
  if (!match) return null;
  const parts = match[1].split("|").map((part) => part.trim());
  const className = parts[0] || "";
  const skinName = parts[1] || "";
  if (!className && !skinName) return null;
  return {
    className,
    skinName,
    clothing: parts[2] || "",
    accessory: parts[3] || "",
  };
}

export function stripSkinToken(content: string): string {
  return content.replace(SKIN_TOKEN, "").replace(/\n{3,}/g, "\n\n").trim();
}

export function inferSkinVisualize(prompt: string | undefined): boolean {
  if (!prompt) return false;
  if (/\bskin count\b|\bskins?\s+armor\b/i.test(prompt)) return false;
  if (/\b(?:all\s+)?(?:shiny|divine)\b/i.test(prompt) && /\b(?:set|loadout)\b/i.test(prompt)) {
    return false;
  }
  return (
    /\b(?:skins?\s+visuali[sz]e|visuali[sz]e\s+(?:this\s+|the\s+|my\s+)?(?:skin|outfit)|skin\s+visuali[sz]er?)\b/i.test(
      prompt,
    ) ||
    /\b(?:show|preview|render)\b.{0,120}\b(?:skin|outfit|dye|cloth)\b/i.test(prompt) ||
    /\blook like with\b.{0,80}\b(?:cloth|dye)\b/i.test(prompt) ||
    /\b(?:large|small)\s+\S.+\s+cloth\b/i.test(prompt) ||
    /\b(?:clothing|accessory)\s+dye\b/i.test(prompt) ||
    /\b(?:swap|switch|flip)\b.{0,80}\b(?:cloth|dye|clothing|accessory)\b/i.test(prompt)
  );
}
