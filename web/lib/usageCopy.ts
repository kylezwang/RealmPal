/** Guest/free daily counter copy. Only in-depth (Claude) turns spend this. */

export function freeInDepthPromptsLeft(remaining: number): string {
  return remaining === 1
    ? "1 free in-depth response left"
    : `${remaining} free in-depth responses left`;
}

export function freeInDepthPromptsUsed(limit: number): string {
  return `You've used your ${limit} free in-depth responses`;
}

export function freeInDepthPromptsHaveLeft(remaining: number): string {
  return remaining === 1
    ? "You have 1 free in-depth response left"
    : `You have ${remaining} free in-depth responses left`;
}

export function freeInDepthPromptsStillLeftToday(remaining: number): string {
  return remaining === 1
    ? "You still have 1 free in-depth response left today"
    : `You still have ${remaining} free in-depth responses left today`;
}

export const STILL_ASK_GENERAL =
  "Get more in-depth responses by creating an account. You can still ask more general questions such as:";

export function leftoverAskLead(signedIn: boolean): string {
  return signedIn
    ? "Get more in-depth responses with RealmPal Pro. You can still ask more general questions such as:"
    : STILL_ASK_GENERAL;
}
